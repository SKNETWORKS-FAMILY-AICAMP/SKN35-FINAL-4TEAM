"""① 풀이별 Docker MCP stdio. 명령·이미지·마운트는 신뢰한 운영 설정만 사용합니다.

컨테이너 수명은 Docker daemon이 관리하므로 CLI 프로세스 종료와 별도로 제거합니다.
만료 임대 회수는 scope/job/lease/trial 라벨이 모두 맞는 컨테이너만 정리합니다.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import subprocess
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from uuid import uuid4

from psycopg import sql

from slotagent.common.db_names import col, table
from slotagent.engine.eng_stdio import StdioTools, _duration
from slotagent.engine.loop import ToolEnvironmentError

LABEL = "io.slotagent."
SAFE_ENV = {"LANG", "LC_ALL", "TZ", "PYTHONUTF8"}


def _token(value):
    return isinstance(value, str) and bool(value) and not any(c in value for c in ("\0", "\n", "\r", ","))


def _bind_syntax(source):
    if not _token(source):
        raise ValueError("bind 경로 문자열이 필요합니다.")
    normalized = source.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    windows = PureWindowsPath(source)
    if ".." in parts or not (PurePosixPath(source).is_absolute() or windows.is_absolute()):
        raise ValueError("bind 경로는 상위 이동 없는 절대 경로여야 합니다.")
    tail = normalized[2:] if re.match(r"^[a-zA-Z]:", normalized) else normalized
    tail = str(PurePosixPath(tail)).casefold()
    if tail in {"/", "/var/run", "/run"} or tail.startswith(("/var/run/", "/run/")):
        raise ValueError("루트·런타임 제어 경로는 데이터 루트나 원본으로 사용할 수 없습니다.")
    if "docker.sock" in normalized.casefold() or "docker_engine" in normalized.casefold():
        raise ValueError("Docker 제어 소켓은 데이터로 사용할 수 없습니다.")


def _checked_path(value, *, directory=False):
    _bind_syntax(value)
    windows = PureWindowsPath(value)
    if os.name == "nt":
        if not re.fullmatch(r"[a-zA-Z]:", windows.drive) or not windows.is_absolute():
            raise ValueError("워커에서 검사 가능한 로컬 드라이브 경로만 허용합니다.")
        if any(part.endswith((".", " ")) or ":" in part for part in windows.parts[1:]):
            raise ValueError("Windows 경로 별칭은 허용하지 않습니다.")
    elif "\\" in value or windows.drive or value.startswith("//"):
        raise ValueError("워커와 같은 파일 시스템의 절대 경로만 허용합니다.")
    path = Path(value)
    try:
        # resolve 전에 모든 조상을 lstat: 링크·junction을 따라간 뒤 허용하지 않습니다.
        current = Path(path.anchor)
        for part in (None, *path.parts[1:]):
            if part is not None:
                current = current / part
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise ValueError("bind 경로와 조상에 링크·reparse point를 허용하지 않습니다.")
        resolved = path.resolve(strict=True)
        if not (stat.S_ISDIR(metadata.st_mode) or (not directory and stat.S_ISREG(metadata.st_mode))):
            raise ValueError("데이터 원본은 일반 파일 또는 디렉터리여야 합니다.")
        return resolved
    except (OSError, RuntimeError):
        raise ValueError("워커에서 bind 경로와 링크 여부를 확인할 수 없습니다.") from None


def validate_bind_source(source, allowed_roots):
    """실제 실행 경계에서 원본과 모든 허용 루트를 검사합니다. 문자열 접두사를 쓰지 않습니다."""
    if not allowed_roots:
        raise ValueError("bind에는 명시적인 데이터 허용 루트가 필요합니다.")
    roots = tuple(_checked_path(root, directory=True) for root in allowed_roots)
    path = _checked_path(source)
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError("bind 원본이 허용 데이터 루트 밖에 있습니다.")
    return str(path)


@dataclass(frozen=True)
class ReadOnlyMount:
    source: str
    target: str
    kind: str = "bind"

    def __post_init__(self):
        target = PurePosixPath(self.target)
        if not _token(self.source) or not _token(self.target) or self.kind not in {"bind", "volume"}:
            raise ValueError("읽기 전용 데이터 마운트 설정이 올바르지 않습니다.")
        if not target.is_absolute() or ".." in target.parts or str(target) == "/":
            raise ValueError("마운트 대상은 명시적인 컨테이너 절대 경로여야 합니다.")
        if target.parts[1] in {"proc", "sys", "dev", "run", "etc", "app"} or str(target).startswith("/var/run"):
            raise ValueError("컨테이너 제어·실행 경로에는 데이터를 마운트하지 않습니다.")
        if self.kind == "volume" and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", self.source):
            raise ValueError("명시적인 Docker 데이터 볼륨 이름이 필요합니다.")
        if self.kind == "bind" and not (
            PurePosixPath(self.source).is_absolute() or PureWindowsPath(self.source).is_absolute()
        ):
            raise ValueError("bind 데이터 원본은 Docker 호스트의 절대 경로여야 합니다.")
        if "docker.sock" in self.source or "docker_engine" in self.source:
            raise ValueError("MCP 컨테이너에 Docker 제어 소켓을 마운트할 수 없습니다.")
        if self.kind == "bind":
            _bind_syntax(self.source)

    def argument(self):
        return f"type={self.kind},source={self.source},target={self.target},readonly"


@dataclass(frozen=True)
class DockerServer:
    image: str
    arguments: tuple[str, ...] = ()
    mounts: tuple[ReadOnlyMount, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    entrypoint: str | None = None
    memory_mb: int = 128
    cpus: float = 1
    pids_limit: int = 64
    allowed_data_roots: tuple[str, ...] = ()

    def __post_init__(self):
        if not _token(self.image) or self.image.startswith("-") or any(c.isspace() for c in self.image):
            raise ValueError("고정할 Docker 이미지 이름 또는 digest가 필요합니다.")
        if any(not isinstance(arg, str) or "\0" in arg for arg in self.arguments):
            raise ValueError("서버 인자는 문자열 목록이어야 합니다.")
        if any(not isinstance(mount, ReadOnlyMount) for mount in self.mounts):
            raise ValueError("읽기 전용 마운트만 허용합니다.")
        if not isinstance(self.environment, dict) or any(
            key not in SAFE_ENV or not isinstance(value, str) or "\0" in value
            for key, value in self.environment.items()
        ):
            raise ValueError("컨테이너 환경에는 명시적인 언어·시간대·인코딩 설정만 허용합니다.")
        if self.entrypoint is not None and (not _token(self.entrypoint) or not self.entrypoint.startswith("/")):
            raise ValueError("entrypoint는 명시적인 컨테이너 절대 경로여야 합니다.")
        if isinstance(self.memory_mb, bool) or not isinstance(self.memory_mb, int) or not 16 <= self.memory_mb <= 65536:
            raise ValueError("메모리 상한은 16~65536 MiB 정수여야 합니다.")
        if (
            isinstance(self.pids_limit, bool)
            or not isinstance(self.pids_limit, int)
            or not 1 <= self.pids_limit <= 4096
        ):
            raise ValueError("PID 상한은 1~4096 정수여야 합니다.")
        if (
            isinstance(self.cpus, bool)
            or not isinstance(self.cpus, (float, int))
            or not math.isfinite(self.cpus)
            or not 0 < self.cpus <= 64
        ):
            raise ValueError("CPU 상한은 0 초과 64 이하의 유한한 수여야 합니다.")
        object.__setattr__(self, "arguments", tuple(self.arguments))
        object.__setattr__(self, "mounts", tuple(self.mounts))
        if isinstance(self.allowed_data_roots, str):
            raise ValueError("데이터 루트는 경로 목록이어야 합니다.")
        for root in self.allowed_data_roots:
            _bind_syntax(root)
        object.__setattr__(self, "allowed_data_roots", tuple(self.allowed_data_roots))
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))


class DockerControl:
    """Docker CLI는 워커 쪽에서만 실행합니다. 제어 명령에도 시간 상한을 둡니다."""

    def __init__(self, executable=None, *, timeout_sec=10):
        self.executable = executable or shutil.which("docker") or "docker"
        self.timeout_sec = _duration(timeout_sec)
        # Docker 접속/컨텍스트 경로는 호스트 CLI에만 필요하며 컨테이너 env로 넘기지 않습니다.
        keys = {
            "PATH",
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "SystemRoot",
            "WINDIR",
            "TEMP",
            "TMP",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }
        self.environment = {key: os.environ[key] for key in keys if key in os.environ}

    def run(self, *arguments, check=True):
        try:
            result = subprocess.run(
                [self.executable, *arguments],
                capture_output=True,
                timeout=self.timeout_sec,
                env=self.environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ToolEnvironmentError() from None
        if check and result.returncode != 0:
            raise ToolEnvironmentError()
        return result

    def image_id(self, image):
        identifier = self.run("image", "inspect", "--format", "{{.Id}}", image).stdout.decode().strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", identifier):
            raise ToolEnvironmentError()
        return identifier

    def bind_paths_visible(self):
        """원격 daemon·컨테이너 워커의 서로 다른 경로 공간은 추정해서 허용하지 않습니다."""
        endpoint = self.environment.get("DOCKER_HOST", "")
        if endpoint and not endpoint.startswith(("npipe://", "unix://")):
            return False
        if os.name != "nt" and (Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()):
            return False
        if self.environment.get("DOCKER_CONTEXT") or not endpoint:
            endpoint = self.run("context", "inspect", "--format", "{{.Endpoints.docker.Host}}").stdout.decode().strip()
        return endpoint.startswith("npipe:////./pipe/") if os.name == "nt" else endpoint.startswith("unix:///")

    def containers(self, scope):
        template = '{"id":{{json .ID}},"name":{{json .Names}},"job":{{json (.Label "io.slotagent.job")}},"lease":{{json (.Label "io.slotagent.lease")}},"trial":{{json (.Label "io.slotagent.trial")}}}'
        output = self.run(
            "ps",
            "-a",
            "--filter",
            f"label={LABEL}scope={scope}",
            "--filter",
            f"label={LABEL}kind=mcp",
            "--format",
            template,
        ).stdout
        if len(output) > 1024 * 1024:
            raise ToolEnvironmentError()
        try:
            rows = [json.loads(line) for line in output.decode().splitlines()]
            if len(rows) > 1024 or any(not re.fullmatch(r"[a-f0-9]{12,64}", row["id"]) for row in rows):
                raise ValueError
            return rows
        except (ValueError, KeyError, TypeError):
            raise ToolEnvironmentError() from None

    def remove(self, scope, identifiers):
        if not identifiers:
            return
        self.run("rm", "-f", *identifiers, check=False)
        # --rm과 명시적 rm의 경합은 남은 대상을 다시 확인해서 구별합니다.
        remaining = {row["id"] for row in self.containers(scope)}
        if remaining.intersection(identifiers):
            raise ToolEnvironmentError()

    def remove_name(self, scope, name):
        self.remove(scope, [row["id"] for row in self.containers(scope) if row["name"] == name])


def docker_run_argv(executable, server, image_id, scope, execution, name):
    """설정을 argv로 옮기는 순수 함수. bind 실행 허가는 DockerStdioTools에서 별도로 검사합니다."""
    labels = {
        "scope": scope,
        "kind": "mcp",
        "trial": str(execution["trial_id"]),
        "attempt": str(execution["attempt"]),
        "job": str(execution["job_id"]),
        "lease": str(execution["lease_attempt"]),
    }
    argv = [
        executable,
        "run",
        "-i",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network",
        "none",
        "--init",
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        f"{server.memory_mb}m",
        "--memory-swap",
        f"{server.memory_mb}m",
        "--cpus",
        str(server.cpus),
        "--pids-limit",
        str(server.pids_limit),
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
    ]
    for key, value in labels.items():
        argv.extend(("--label", f"{LABEL}{key}={value}"))
    for mount in server.mounts:
        argv.extend(("--mount", mount.argument()))
    # Docker 클라이언트의 proxy 자동 주입도 빈 값으로 막습니다.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY"):
        argv.extend(("--env", f"{key}=", "--env", f"{key.lower()}="))
    for key, value in server.environment.items():
        argv.extend(("--env", f"{key}={value}"))
    if server.entrypoint is not None:
        argv.extend(("--entrypoint", server.entrypoint))
    argv.extend((image_id, *server.arguments))
    return argv


class DockerStdioTools(StdioTools):
    """stdio 프레이밍은 기존 연결을 재사용하고 daemon 컨테이너 수명은 별도로 닫습니다."""

    def __init__(self, control, server, tools, *, scope, execution, timeout_sec, cancel_signals):
        self.control, self.scope = control, scope
        self.container_name = f"sa-mcp-t{execution['trial_id']}-a{execution['attempt']}-{uuid4().hex}"
        self._docker_cleaned = False
        self._server, self._execution = server, dict(execution)
        checked = self._checked_server()
        self._image = control.image_id(server.image)
        argv = docker_run_argv(control.executable, checked, self._image, scope, execution, self.container_name)
        super().__init__(argv, tools, timeout_sec=timeout_sec, cancel_signals=cancel_signals)
        self.environment.update(control.environment)

    def _checked_server(self):
        if not any(mount.kind == "bind" for mount in self._server.mounts):
            return self._server
        try:
            mounts = tuple(
                replace(mount, source=validate_bind_source(mount.source, self._server.allowed_data_roots))
                if mount.kind == "bind"
                else mount
                for mount in self._server.mounts
            )
            if not self.control.bind_paths_visible():
                raise ValueError("Docker 호스트와 워커의 경로가 같은지 확인할 수 없습니다.")
            return replace(self._server, mounts=mounts, environment=dict(self._server.environment))
        except ValueError:
            raise ToolEnvironmentError() from None

    def start(self):
        if self.state == "new":
            try:
                checked = self._checked_server()
            except ToolEnvironmentError:
                self._transition("closed")
                self._docker_cleaned = True
                raise
            self.command = docker_run_argv(
                self.control.executable, checked, self._image, self.scope, self._execution, self.container_name
            )
        return super().start()

    def close(self):
        if self._docker_cleaned:
            return
        errors = []
        # CLI 종료 전후로 확인해 run 시작과 close가 경합한 경우에도 제거합니다.
        for action in (
            lambda: self.control.remove_name(self.scope, self.container_name),
            super().close,
            lambda: self.control.remove_name(self.scope, self.container_name),
        ):
            try:
                action()
            except Exception as exc:
                errors.append(exc)
        if errors:
            failure = ToolEnvironmentError()
            for error in errors:
                failure.add_note(type(error).__name__)
            raise failure from None
        self._docker_cleaned = True


class DockerStdioConfig:
    def __init__(self, servers, *, scope, docker=None, timeout_sec=5, control_timeout_sec=10):
        if (
            not isinstance(servers, dict)
            or not servers
            or any(not isinstance(s, DockerServer) for s in servers.values())
        ):
            raise ValueError("서버 이름별 Docker 이미지 설정이 필요합니다.")
        if not isinstance(scope, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", scope):
            raise ValueError("같은 실행 환경의 워커가 공유할 고유 scope가 필요합니다.")
        self.servers, self.scope = MappingProxyType(dict(servers)), scope
        self.timeout_sec = _duration(timeout_sec)
        self.control = DockerControl(docker, timeout_sec=control_timeout_sec)

    @contextmanager
    def open(self, snapshot, *, execution=None, cancel_signals=()):
        if not isinstance(execution, dict) or any(
            isinstance(execution.get(key), bool) or not isinstance(execution.get(key), int) or execution[key] < 1
            for key in ("trial_id", "attempt", "job_id", "lease_attempt")
        ):
            raise ValueError("고아 컨테이너 회수를 위해 풀이·현재 임대 식별자가 필요합니다.")
        grouped = {}
        declared = {server["name"]: server for server in snapshot["mcp_servers"]}
        for tool in snapshot["tools"]:
            if tool["access"] != "read":
                continue
            if not tool["origin"].startswith("mcp:"):
                raise NotImplementedError("Docker 연결은 MCP 조회 도구만 지원합니다.")
            name = tool["origin"][4:]
            if name not in self.servers or name not in declared or declared[name].get("transport", "stdio") != "stdio":
                raise ValueError("후보 서버에 맞는 Docker stdio 설정이 없습니다.")
            grouped.setdefault(name, []).append(tool)
        if not grouped:
            raise ValueError("연결할 MCP 조회 도구가 없습니다.")
        with ExitStack() as stack:
            routes = {}
            for name, tools in grouped.items():
                client = stack.enter_context(
                    DockerStdioTools(
                        self.control,
                        self.servers[name],
                        tools,
                        scope=self.scope,
                        execution=execution,
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

    def reclaim_expired(self, jobs, *, conn=None):
        containers = self.control.containers(self.scope)
        if not containers:
            return
        if conn is not None:
            # CLI 사망 뒤 생성 요청이 늦게 완료된 경우도 다음 회수 때 정리합니다.
            # 임대는 컨테이너 시작 전에 커밋되며 attempts는 감소하지 않습니다.
            try:
                identifiers = list({int(row["job"]) for row in containers})
                if any(int(row["lease"]) < 1 or int(row["trial"]) < 1 for row in containers):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise ToolEnvironmentError() from None
            fields = {
                name: sql.Identifier(col("jobs", name))
                for name in (
                    "id",
                    "kind",
                    "payload",
                    "attempts",
                    "status",
                    "lease_until",
                )
            }
            records = conn.execute(
                sql.SQL(
                    "SELECT {id},{kind},{payload},{attempts},{status},{lease_until}>clock_timestamp() "
                    "FROM {jobs} WHERE {id}=ANY(%s)"
                ).format(jobs=sql.Identifier(table("jobs")), **fields),
                (identifiers,),
            ).fetchall()
            current = {record[0]: record[1:] for record in records}
            stale = []
            for row in containers:
                record = current.get(int(row["job"]))
                valid = record is not None and (
                    record[0] == "run_trial"
                    and str(record[1].get("trial_id")) == row["trial"]
                    and record[2] == int(row["lease"])
                    and record[3] == "leased"
                    and record[4]
                )
                if not valid:
                    stale.append(row["id"])
            self.control.remove(self.scope, stale)
            return
        tokens = {
            (
                str(job[col("jobs", "id")]),
                str(job[col("jobs", "attempts")]),
                str(job[col("jobs", "payload")]["trial_id"]),
            )
            for job in jobs
            if job[col("jobs", "kind")] == "run_trial"
        }
        if tokens:
            expired = [row["id"] for row in containers if (row["job"], row["lease"], row["trial"]) in tokens]
            self.control.remove(self.scope, expired)
