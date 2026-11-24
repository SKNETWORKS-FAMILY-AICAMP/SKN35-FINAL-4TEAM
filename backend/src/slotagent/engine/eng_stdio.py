"""① 로컬 검증용 조회 전용 MCP stdio 연결. Docker·팩 환경 검증은 별도 단계입니다.

명령은 신뢰한 호출자가 argv로 명시하며 스냅샷·모델 출력에서 명령을 만들지 않습니다.
MCP 2025-11-25의 initialize/tools/list/tools/call과 TextContent만 지원합니다.
stdio: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
연결 자체의 재시도는 없고 실패한 세션은 다시 사용할 수 없습니다.
"""

from __future__ import annotations

import copy
import ctypes
import json
import math
import os
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import ExitStack, contextmanager
from threading import Event, Lock, Thread

from jsonschema import Draft202012Validator

from slotagent.common import contracts
from slotagent.engine.loop import RunCancelled, ToolEnvironmentError, ToolExecutionError

VERSION = "2025-11-25"
MAX_MESSAGE = 1024 * 1024
MAX_MESSAGES = 128
TREE_WAIT_SEC = 2.0


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobAccounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


class _WindowsJob:
    """비상속·익명 Job. 등록 전 자식은 suspended라 손자를 만들 수 없습니다.

    Popen은 주 스레드 핸들을 닫으므로 문서화된 Toolhelp/OpenThread/ResumeThread를 씁니다.
    Popen 직후 등록 전 워커가 사망하면 정지된 자식이 남을 수 있는 틈은 남습니다.
    """

    def __init__(self):
        self.handle = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword, boolean, pointer = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p
        signatures = {
            "CreateJobObjectW": ([pointer, ctypes.c_wchar_p], handle),
            "SetInformationJobObject": ([handle, ctypes.c_int, pointer, dword], boolean),
            "AssignProcessToJobObject": ([handle, handle], boolean),
            "TerminateJobObject": ([handle, dword], boolean),
            "QueryInformationJobObject": ([handle, ctypes.c_int, pointer, dword, pointer], boolean),
            "CloseHandle": ([handle], boolean),
            "CreateToolhelp32Snapshot": ([dword, dword], handle),
            "Thread32First": ([handle, ctypes.POINTER(_ThreadEntry)], boolean),
            "Thread32Next": ([handle, ctypes.POINTER(_ThreadEntry)], boolean),
            "OpenThread": ([dword, boolean, dword], handle),
            "ResumeThread": ([handle], dword),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        self.handle = self._create()
        try:
            self._configure()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def _create(self):
        # NULL 보안 속성은 핸들 상속을 금지합니다. 워커 사망 시 마지막 핸들이 닫힙니다.
        return self._check(self.kernel.CreateJobObjectW(None, None))

    def _configure(self):
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self._check(self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))

    def assign(self, process):
        self._check(self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)))

    def resume(self, process):
        snapshot = self.kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            for _ in range(65536):
                if not found:
                    raise OSError("정지한 자식의 주 스레드를 확인하지 못했습니다.")
                if entry.th32OwnerProcessID == process.pid:
                    thread = self._check(self.kernel.OpenThread(2, False, entry.th32ThreadID))
                    try:
                        if self.kernel.ResumeThread(thread) != 1:
                            raise OSError("정지한 자식의 주 스레드를 재개하지 못했습니다.")
                        return
                    finally:
                        self._check(self.kernel.CloseHandle(thread))
                found = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("주 스레드 검색 상한을 넘었습니다.")
        finally:
            self._check(self.kernel.CloseHandle(snapshot))

    def terminate(self):
        self._check(self.kernel.TerminateJobObject(self.handle, 1))

    def active_processes(self):
        info = _JobAccounting()
        self._check(
            self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None)
        )
        return info.ActiveProcesses

    def close(self):
        if self.handle is not None:
            self._check(self.kernel.CloseHandle(self.handle))
            self.handle = None


def _duration(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("제한 시간은 유한한 양수여야 합니다.")
    return value


class StdioTools:
    """풀이 시도마다 새 인스턴스를 만들고 with 또는 finally에서 close합니다.

    start를 모델 호출 전에 수행합니다. 확인한 후보 도구만 호출할 수 있으며 서버의
    추가 도구는 모델에 노출하지 않습니다. 한 세션의 동시 호출은 오류로 거부합니다.
    """

    def __init__(
        self,
        command,
        tools,
        *,
        timeout_sec=5.0,
        cancelled: Callable[[], bool] = lambda: False,
        cancel_signals=(),
    ):
        if (
            not isinstance(command, (list, tuple))
            or not command
            or any(not isinstance(arg, str) or not arg.strip() or "\0" in arg for arg in command)
        ):
            raise ValueError("신뢰한 실행 파일과 인자를 argv 목록으로 지정하세요.")
        if not isinstance(tools, list) or not tools:
            raise ValueError("검사할 후보 도구가 필요합니다.")
        origins = set()
        self.tools = {}
        for tool in copy.deepcopy(tools):
            contracts.validate("common", tool, part="tool_def")
            if tool["access"] != "read" or not tool["origin"].startswith("mcp:"):
                raise ValueError("MCP 조회 도구만 연결할 수 있습니다.")
            if tool["name"] in self.tools:
                raise ValueError("후보 도구 이름이 중복됐습니다.")
            Draft202012Validator.check_schema(tool["parameters"])
            self.tools[tool["name"]] = tool
            origins.add(tool["origin"])
        if len(origins) != 1:
            raise ValueError("한 세션에는 같은 MCP 서버의 도구만 지정하세요.")
        self.command = list(command)
        self.timeout_sec = _duration(timeout_sec)
        self.cancelled = cancelled
        self.cancel_signals = tuple(cancel_signals)
        if not callable(cancelled) or any(not callable(callback) for callback in self.cancel_signals):
            raise ValueError("취소 신호는 호출 가능한 함수여야 합니다.")
        # 제공자 키·DATABASE_URL 등 부모의 환경을 상속하지 않습니다.
        self.environment = {
            key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ
        }
        self.environment["PYTHONUTF8"] = "1"
        self.process = None
        self._job = None
        self._state = "new"
        self._sequence = 0
        self._lock = Lock()
        self._io = None
        self.request_sent = Event()

    @property
    def state(self):
        return self._state

    def _cancelled(self):
        return self.cancelled() or any(callback() for callback in self.cancel_signals)

    def _transition(self, target):
        allowed = {
            "new": {"starting", "closed"},
            "starting": {"ready", "broken", "closed"},
            "ready": {"broken", "closed"},
            "broken": {"closed"},
            "closed": set(),
        }
        if target not in allowed[self.state]:
            raise ValueError(f"허용되지 않은 stdio 상태 전이: {self.state} → {target}")
        self._state = target

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.close()
        except Exception as cleanup_error:
            if exc is None:
                raise
            exc.add_note(f"stdio 정리 실패: {type(cleanup_error).__name__}")

    def start(self):
        if not self._lock.acquire(blocking=False):
            raise ValueError("한 stdio 세션의 동시 요청은 지원하지 않습니다.")
        try:
            if self.state != "new":
                raise ValueError("새 세션만 시작할 수 있습니다.")
            self._transition("starting")
            try:
                deadline = time.monotonic() + self.timeout_sec
                if self._cancelled():
                    raise RunCancelled("MCP 시작이 취소됐습니다.")
                if os.name == "nt":
                    self._job = _WindowsJob()
                self.process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=self.environment,
                    shell=False,
                    creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) | 0x4) if os.name == "nt" else 0,
                    start_new_session=os.name != "nt",
                )
                if self._job is not None:
                    self._job.assign(self.process)
                    self._job.resume(self.process)
                result = self._rpc(
                    "initialize",
                    {
                        "protocolVersion": VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "slotagent-local", "version": "0.1"},
                    },
                    deadline,
                )
                if (
                    result.get("protocolVersion") != VERSION
                    or not isinstance(result.get("capabilities"), dict)
                    or not isinstance(result["capabilities"].get("tools"), dict)
                    or not isinstance(result.get("serverInfo"), dict)
                ):
                    raise ToolEnvironmentError()
                inventory = self._rpc("tools/list", {}, deadline, initialized=True)
                listed = inventory.get("tools")
                if not isinstance(listed, list) or not listed or inventory.get("nextCursor"):
                    # 최소 연결 단계에서는 페이지를 무한히 읽지 않고 지원 범위를 명시합니다.
                    raise ToolEnvironmentError()
                actual = {}
                for entry in listed:
                    if (
                        not isinstance(entry, dict)
                        or not isinstance(entry.get("name"), str)
                        or entry["name"] in actual
                        or not isinstance(entry.get("inputSchema"), dict)
                    ):
                        raise ToolEnvironmentError()
                    actual[entry["name"]] = entry["inputSchema"]

                def comparable(schema):
                    return {key: value for key, value in schema.items() if key != "$schema"}

                if any(
                    name not in actual or comparable(actual[name]) != comparable(tool["parameters"])
                    for name, tool in self.tools.items()
                ):
                    raise ToolEnvironmentError()
                self._transition("ready")
                self.request_sent.clear()
            except OSError:
                self._abort()
                raise ToolEnvironmentError() from None
            except BaseException:
                self._abort()
                raise
        finally:
            self._lock.release()

    def __call__(self, name, arguments, timeout_sec):
        seconds = min(_duration(timeout_sec), self.timeout_sec)
        if not isinstance(name, str) or name not in self.tools or not isinstance(arguments, dict):
            raise ValueError("후보에 있는 도구와 객체 인자가 필요합니다.")
        if list(Draft202012Validator(self.tools[name]["parameters"]).iter_errors(arguments)):
            raise ValueError("도구 인자가 입력 스키마와 다릅니다.")
        if not self._lock.acquire(blocking=False):
            raise ValueError("한 stdio 세션의 동시 요청은 지원하지 않습니다.")
        try:
            if self.state != "ready":
                raise ValueError("시작 검사를 통과한 세션만 호출할 수 있습니다.")
            try:
                result = self._rpc("tools/call", {"name": name, "arguments": arguments}, time.monotonic() + seconds)
                content = result.get("content")
                is_error = result.get("isError", False)
                if not isinstance(is_error, bool) or not isinstance(content, list) or not content:
                    raise ToolEnvironmentError()
                if any(
                    not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str)
                    for block in content
                ):
                    raise ToolEnvironmentError()
                text = "\n".join(block["text"] for block in content)
                if not text.strip():
                    raise ToolEnvironmentError()
                if is_error:
                    raise ToolExecutionError(text)
                return text
            except ToolExecutionError:
                raise
            except BaseException:
                self._abort()
                raise
        finally:
            self._lock.release()

    def _rpc(self, method, params, deadline, *, initialized=False):
        self._sequence += 1
        request_id = self._sequence
        request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        if initialized:
            payload = b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n' + payload
        if len(payload) > MAX_MESSAGE:
            raise ValueError("MCP 요청 크기 상한을 넘었습니다.")
        done, output = Event(), []
        self.request_sent.clear()

        def exchange():
            try:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
                self.request_sent.set()
                for _ in range(MAX_MESSAGES):
                    line = self.process.stdout.readline(MAX_MESSAGE + 1)
                    if not line or len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                        raise ToolEnvironmentError()
                    message = json.loads(line)
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                        raise ToolEnvironmentError()
                    if "id" not in message and isinstance(message.get("method"), str):
                        continue
                    if (
                        type(message.get("id")) is not int
                        or message["id"] != request_id
                        or "error" in message
                        or not isinstance(message.get("result"), dict)
                    ):
                        raise ToolEnvironmentError()
                    output.append(message["result"])
                    return
                raise ToolEnvironmentError()
            except Exception:
                # 외부 오류 원문은 키·경로 등을 담을 수 있어 모델에 전달하지 않습니다.
                output.append(ToolEnvironmentError())
            finally:
                done.set()

        self._io = Thread(target=exchange, name="eng-stdio", daemon=True)
        self._io.start()
        while True:
            if self._cancelled():
                raise RunCancelled("MCP 응답 대기가 취소됐습니다.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # MCP 초기화·호출 무응답은 풀이 자체의 시간 초과와 구분합니다.
                raise ToolEnvironmentError(reason="env_mcp_server_down")
            if done.wait(min(remaining, 0.02)):
                if isinstance(output[0], Exception):
                    raise output[0]
                return output[0]

    def _abort(self):
        self._transition("broken")
        self.close()

    def _terminate_tree(self):
        if self._job is not None and self._job.handle is not None:
            self._job.terminate()
        if self.process is not None:
            if os.name != "nt":
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    # 이미 빈 그룹은 정리가 끝난 상태이며 뒤의 확인 단계도 수행합니다.
                    return
            elif self.process.poll() is None:
                # Job 등록 실패로 아직 Job 밖에 있는 suspended 자식도 반드시 종료합니다.
                self.process.kill()

    def _verify_tree_stopped(self):
        deadline = time.monotonic() + TREE_WAIT_SEC
        if self.process is not None:
            self.process.wait(timeout=TREE_WAIT_SEC)
        if self._job is not None and self._job.handle is not None:
            while self._job.active_processes():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Job 안의 프로세스가 종료되지 않았습니다.")
                time.sleep(0.01)

    def close(self):
        if self.state == "closed":
            return
        errors = []

        def attempt(action):
            try:
                action()
            except Exception as exc:
                errors.append(exc)

        try:
            attempt(self._terminate_tree)
            # 한 정리 단계가 실패해도 Job 핸들은 반드시 닫고 프로세스 종료 확인을 시도합니다.
            attempt(self._verify_tree_stopped)
            if self._job is not None:
                attempt(self._job.close)
            if self.process is not None:
                attempt(lambda: self.process.wait(timeout=TREE_WAIT_SEC))
            if self._io is not None:
                attempt(lambda: self._io.join(timeout=0.5))
                alive = self._io.is_alive()
                if alive:
                    errors.append(RuntimeError("stdio IO 스레드를 정리하지 못했습니다."))
            else:
                alive = False
            # 살아 있는 스레드가 잡은 파이프 lock을 기다리며 무한 정지하지 않습니다.
            if self.process is not None and not alive:
                attempt(self.process.stdin.close)
                attempt(self.process.stdout.close)
        finally:
            self._transition("closed")
        if errors:
            failure = RuntimeError("stdio 트리 정리에 실패했습니다.")
            for error in errors:
                failure.add_note(type(error).__name__)
            raise failure from errors[0]


class LocalStdioConfig:
    """운영자가 신뢰한 로컬 명령만 등록합니다. 후보/모델에서 명령을 추정하지 않습니다.

    워커는 풀이 시작 검사 뒤 open을 호출하며, 각 attempt에 새 세션을 만듭니다.
    Docker·팩 metadata 검증은 이 로컬 연결 설정에 포함하지 않습니다.
    """

    def __init__(self, commands, *, timeout_sec=5.0):
        if not isinstance(commands, dict) or not commands:
            raise ValueError("서버 이름별 신뢰한 argv 설정이 필요합니다.")
        self.commands = {}
        for name, command in commands.items():
            if not isinstance(name, str) or not name or not isinstance(command, (list, tuple)) or not command:
                raise ValueError("서버 이름과 argv 목록이 필요합니다.")
            if any(not isinstance(arg, str) or not arg.strip() or "\0" in arg for arg in command):
                raise ValueError("실행 파일과 인자는 비어 있지 않은 문자열이어야 합니다.")
            self.commands[name] = tuple(command)
        self.timeout_sec = _duration(timeout_sec)

    @contextmanager
    def open(self, snapshot, *, cancel_signals=(), execution=None):
        grouped = {}
        declared = {server["name"]: server for server in snapshot["mcp_servers"]}
        for tool in snapshot["tools"]:
            if tool["access"] != "read":
                continue
            if not tool["origin"].startswith("mcp:"):
                raise NotImplementedError("로컬 stdio 연결은 MCP 조회 도구만 지원합니다.")
            name = tool["origin"][4:]
            if name not in self.commands or name not in declared or declared[name].get("transport", "stdio") != "stdio":
                raise ValueError("후보 MCP 서버에 맞는 신뢰한 stdio 명령이 없습니다.")
            grouped.setdefault(name, []).append(tool)
        if not grouped:
            raise ValueError("연결할 MCP 조회 도구가 없습니다.")
        with ExitStack() as stack:
            routes = {}
            for name, tools in grouped.items():
                client = stack.enter_context(
                    StdioTools(
                        self.commands[name],
                        tools,
                        timeout_sec=self.timeout_sec,
                        cancel_signals=cancel_signals,
                    )
                )
                routes.update((tool["name"], client) for tool in tools)

            def call_tool(name, arguments, timeout_sec):
                if name not in routes:
                    raise ValueError("이 풀이에 연결하지 않은 도구입니다.")
                return routes[name](name, arguments, timeout_sec)

            yield call_tool
