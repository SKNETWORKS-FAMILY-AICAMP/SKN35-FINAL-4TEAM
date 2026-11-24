"""① 실제 자식 프로세스로 stdio 경계와 제품 DB 저장을 검증합니다."""

import copy
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event

import psycopg
import pytest
from conftest import load
from psycopg import sql
from test_eng_queue import clean_queue as clean_queue
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.common.db_names import col, table
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine import advance
from slotagent.engine import eng_stdio as stdio
from slotagent.engine.eng_stdio import StdioTools
from slotagent.engine.loop import RunCancelled, ToolEnvironmentError
from slotagent.workers.eng_main import run_once


@pytest.fixture
def definitions():
    data = load("slot_and_candidates.json")
    snapshot = merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][0])
    return [t for t in snapshot["tools"] if t["access"] == "read" and t["origin"] == "mcp:github"]


def session(definitions, mode="ok", *, inventory=None, server_options=None, **kwargs):
    tools = (
        inventory
        if inventory is not None
        else [{"name": t["name"], "inputSchema": t["parameters"]} for t in definitions]
    )
    config = json.dumps({"tools": tools, "mode": mode, **(server_options or {})})
    return StdioTools(
        [sys.executable, "-u", str(Path(__file__).with_name("eng_stdio_server.py")), config],
        definitions,
        **kwargs,
    )


ARGS = {"owner": "acme", "repo": "ops-service", "state": "open"}


def assert_closed(client):
    assert client.state == "closed"
    assert client.process is None or client.process.poll() is not None
    assert client._io is None or not client._io.is_alive()


def test_start_failure(definitions):
    client = StdioTools(["eng-executable-does-not-exist"], definitions)
    with pytest.raises(ToolEnvironmentError):
        client.start()
    assert_closed(client)


def test_initialize_timeout(definitions):
    client = session(definitions, "init_timeout", timeout_sec=0.4)
    before = time.monotonic()
    with pytest.raises(ToolEnvironmentError, match="env_mcp_server_down"):
        client.start()
    assert time.monotonic() - before < 4
    assert_closed(client)


@pytest.mark.parametrize("kind", ["empty", "missing", "duplicate", "schema"])
def test_tool_inventory_rejected(definitions, kind):
    tools = [{"name": t["name"], "inputSchema": t["parameters"]} for t in definitions]
    if kind == "empty":
        tools = []
    elif kind == "missing":
        tools.pop()
    elif kind == "duplicate":
        tools.append(tools[0])
    else:
        tools[0] = {**tools[0], "inputSchema": {"type": "object"}}
    client = session(definitions, inventory=tools)
    with pytest.raises(ToolEnvironmentError):
        client.start()
    assert_closed(client)


@pytest.mark.parametrize("mode", ["bad_json", "empty", "wrong_id", "bad_content", "exit"])
def test_bad_response_closes_session(definitions, mode):
    client = session(definitions, mode)
    with client:
        with pytest.raises(ToolEnvironmentError):
            client("list_issues", ARGS, 2)
        assert_closed(client)
        with pytest.raises(ValueError):
            client("list_issues", ARGS, 2)


@pytest.mark.parametrize("command", [None, [], [""], "python"])
def test_invalid_command(command, definitions):
    with pytest.raises(ValueError):
        StdioTools(command, definitions)


@pytest.mark.parametrize(
    "name,args,timeout",
    [
        ("unknown", {}, 1),
        ("list_issues", None, 1),
        ("list_issues", {}, 1),
        ("list_issues", ARGS, 0),
        ("list_issues", ARGS, float("nan")),
    ],
)
def test_invalid_input_not_sent(definitions, name, args, timeout):
    with session(definitions) as client:
        seq = client._sequence
        with pytest.raises(ValueError):
            client(name, args, timeout)
        assert client._sequence == seq
        assert client("list_issues", ARGS, 2).startswith("[")


def test_concurrent_call_rejected(definitions):
    with session(definitions, "call_timeout") as client, ThreadPoolExecutor(1) as pool:
        pending = pool.submit(client, "list_issues", ARGS, 0.4)
        assert client.request_sent.wait(2)
        with pytest.raises(ValueError, match="동시"):
            client("list_issues", ARGS, 1)
        with pytest.raises(ToolEnvironmentError, match="env_mcp_server_down"):
            pending.result(timeout=4)
        assert_closed(client)


def test_cancel_during_call(definitions):
    cancelled = Event()
    with session(definitions, "call_timeout", cancelled=cancelled.is_set) as client, ThreadPoolExecutor(1) as pool:
        pending = pool.submit(client, "list_issues", ARGS, 5)
        assert client.request_sent.wait(2)
        cancelled.set()
        with pytest.raises(RunCancelled):
            pending.result(timeout=4)
        assert_closed(client)


def test_text_content_and_stderr(definitions, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "eng-test-sentinel")
    with session(definitions, "stderr") as client:
        assert "OPENAI_API_KEY" not in client.environment
        assert json.loads(client("list_issues", ARGS, 2)) == [{"number": 145}, {"number": 148}]
    assert_closed(client)


def test_cancel_during_call_restores_trial(experiment, engine_db, definitions):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    cancelled = Event()
    with session(definitions, "call_timeout", cancelled=cancelled.is_set) as client, ThreadPoolExecutor(1) as pool:
        deps = dependencies(client)
        deps.cancelled = cancelled.is_set
        pending = pool.submit(run_once, connect_to(engine_db), "stdio", deps=deps)
        assert client.request_sent.wait(3)
        cancelled.set()
        with pytest.raises(RunCancelled):
            pending.result(timeout=5)
    assert_closed(client)
    assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", 2)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("queued",)]
    assert rows(conn, "spans", ["seq"], "trial_id", trial) == []
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 1


def test_lease_loss_during_call_is_fenced(experiment, engine_db, definitions):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    with session(definitions, "call_timeout", timeout_sec=1) as client, ThreadPoolExecutor(1) as pool:
        pending = pool.submit(run_once, connect_to(engine_db), "stdio", deps=dependencies(client))
        assert client.request_sent.wait(3)
        conn.execute(
            sql.SQL("UPDATE {} SET {}=clock_timestamp()-interval '1 second' WHERE {}=%s").format(
                sql.Identifier(table("jobs")),
                sql.Identifier(col("jobs", "lease_until")),
                sql.Identifier(col("jobs", "id")),
            ),
            (job,),
        )
        assert queue.reclaim(conn) == 1
        with pytest.raises(queue.LeaseLost):
            pending.result(timeout=5)
    assert_closed(client)
    assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", 2)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("queued",)]
    assert rows(conn, "spans", ["seq"], "trial_id", trial) == []
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 1


def rows(conn, entity, fields, key, value):
    query = sql.SQL("SELECT {} FROM {} WHERE {}=%s").format(
        sql.SQL(",").join(sql.Identifier(col(entity, field)) for field in fields),
        sql.Identifier(table(entity)),
        sql.Identifier(col(entity, key)),
    )
    return conn.execute(query, (value,)).fetchall()


def enqueue(conn, trial):
    return advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": trial})


def connect_to(uri):
    return lambda: psycopg.connect(uri, autocommit=True)


def test_trial_round_trip(experiment, engine_db, definitions):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    with session(definitions) as client:
        deps = dependencies(client)
        assert run_once(connect_to(engine_db), "stdio", deps=deps)
        seq = client._sequence
        from slotagent.engine.worker import run_trial

        assert run_trial(conn, trial, deps=deps) is None
        assert client._sequence == seq
        assert len(deps.model.requests) == 2
        assert json.loads(deps.model.requests[1]["messages"][-1]["content"]) == [{"number": 145}, {"number": 148}]
    assert_closed(client)
    assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("finished", 1)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("done",)]
    assert len(rows(conn, "spans", ["seq"], "trial_id", trial)) == 3
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 2


@pytest.mark.parametrize("mode,reason", [("exit", "env_mcp_server_down"), ("call_timeout", "env_mcp_server_down")])
def test_call_failure_is_saved(experiment, engine_db, definitions, mode, reason):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    with session(definitions, mode, timeout_sec=0.5, startup_timeout_sec=5) as client:
        deps = dependencies(client)
        assert run_once(connect_to(engine_db), "stdio", deps=deps)
        assert len(deps.model.requests) == 1
    assert_closed(client)
    assert rows(conn, "trials", ["status", "outcome_reason"], "id", trial) == [("error", reason)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("done",)]
    assert len(rows(conn, "spans", ["seq"], "trial_id", trial)) == 2
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 1


def test_start_failure_retry_limit(experiment, engine_db, definitions):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    for attempt in range(1, 4):
        # 준비 단계 실패는 후보 결과로 채점하지 않고 작업 재시도 경로로 올립니다.
        with closing(StdioTools(["eng-executable-does-not-exist"], definitions)) as client:
            deps = dependencies()

            class PreparedModel:
                is_fake = True

                def chat(self, **kwargs):
                    client.start()
                    raise AssertionError("시작 실패 후 모델 호출 금지")

            deps.model = PreparedModel()
            with pytest.raises(ToolEnvironmentError):
                run_once(connect_to(engine_db), "stdio", deps=deps)
        assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", attempt + 1)]
    assert rows(conn, "jobs", ["status", "attempts"], "id", job) == [("failed", 3)]
    assert queue.lease(conn, "stdio") is None
    assert rows(conn, "cost_ledger", ["id"], "ref_id", trial) == []


def test_handoff_failure_keeps_cost(experiment, engine_db, definitions, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)

    def fail(*args):
        raise RuntimeError("인계 실패")

    monkeypatch.setattr(advance, "on_trial_finished", fail)
    with session(definitions) as client:
        with pytest.raises(RuntimeError, match="인계 실패"):
            run_once(connect_to(engine_db), "stdio", deps=dependencies(client))
    assert_closed(client)
    assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", 2)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("queued",)]
    assert rows(conn, "spans", ["seq"], "trial_id", trial) == []
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 2


def pid_alive(pid):
    """외부 패키지 없이 프로세스 종료를 확인합니다. 권한 오류는 생존으로 취급합니다."""
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.WaitForSingleObject.restype = ctypes.c_ulong
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            assert kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Linux의 좀비는 더 이상 파이프나 실행 상태를 유지하지 않습니다.
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists() and stat.read_text().rsplit(")", 1)[1].strip().startswith("Z"):
        return False
    return True


def wait_dead(pid, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return
        time.sleep(0.02)
    raise AssertionError(f"프로세스가 종료되지 않았습니다: {pid}")


def emergency_kill(pid):
    """검증 실패 시에도 테스트 서버를 남기지 않습니다."""
    if pid_alive(pid):
        os.kill(pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)


def tree_session(definitions, tmp_path, mode="ok", **kwargs):
    pid_file = tmp_path / "server.pid"
    return session(
        definitions, mode, server_options={"grandchild": True, "pid_file": str(pid_file), **kwargs}
    ), pid_file


def test_process_tree_close(definitions, tmp_path):
    client, pid_file = tree_session(definitions, tmp_path)
    with client:
        pid = int(pid_file.read_text())
        try:
            assert json.loads(client("list_issues", ARGS, 2))[0]["number"] == 145
            client.close()
            wait_dead(pid)
            assert_closed(client)
        finally:
            emergency_kill(pid)


def test_exited_launcher_tree_close(definitions, tmp_path):
    client, pid_file = tree_session(definitions, tmp_path, launcher_exit=True)
    with client:
        pid = int(pid_file.read_text())
        try:
            client.process.wait(timeout=3)
            assert pid_alive(pid)
            client.close()
            wait_dead(pid)
            assert_closed(client)
        finally:
            emergency_kill(pid)


@pytest.mark.parametrize("kind", ["timeout", "cancel"])
def test_process_tree_abort(definitions, tmp_path, kind):
    cancelled = Event()
    client, pid_file = tree_session(definitions, tmp_path, "call_timeout")
    client.cancelled = cancelled.is_set
    with client, ThreadPoolExecutor(1) as pool:
        pid = int(pid_file.read_text())
        try:
            pending = pool.submit(client, "list_issues", ARGS, 0.5 if kind == "timeout" else 5)
            assert client.request_sent.wait(2)
            if kind == "cancel":
                cancelled.set()
            with pytest.raises(ToolEnvironmentError if kind == "timeout" else RunCancelled):
                pending.result(timeout=5)
            wait_dead(pid)
            assert_closed(client)
        finally:
            emergency_kill(pid)


@pytest.mark.skipif(os.name != "nt", reason="POSIX 프로세스 그룹은 부모 사망 시 자동 종료 기능이 없습니다.")
def test_worker_kill_closes_job_tree(definitions, tmp_path):
    client, pid_file = tree_session(definitions, tmp_path)
    ready_file = tmp_path / "ready"
    worker_code = (
        "import json,sys,time; from pathlib import Path; "
        "from slotagent.engine.eng_stdio import StdioTools; "
        "c=StdioTools(json.loads(sys.argv[1]),json.loads(sys.argv[2])); "
        "c.start(); Path(sys.argv[3]).write_text(str(c.process.pid)); time.sleep(30)"
    )
    worker_env = {**os.environ, "PYTHONPATH": str(Path(stdio.__file__).resolve().parents[2])}
    worker = subprocess.Popen(
        [sys.executable, "-c", worker_code, json.dumps(client.command), json.dumps(definitions), str(ready_file)],
        env=worker_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 8
        while not ready_file.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready_file.exists(), "별도 워커가 시작 검사를 완료하지 못했습니다."
        pid = int(pid_file.read_text())
        launcher = int(ready_file.read_text())
        worker.kill()
        worker.wait(timeout=3)
        wait_dead(pid)
        wait_dead(launcher)
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=3)
        if pid_file.exists():
            emergency_kill(int(pid_file.read_text()))
        if ready_file.exists():
            emergency_kill(int(ready_file.read_text()))


@pytest.mark.skipif(os.name != "nt", reason="Windows Job API 실패 경로")
@pytest.mark.parametrize("stage", ["create", "configure", "assign", "resume"])
def test_job_setup_failure(definitions, monkeypatch, stage):
    def fail(*args, **kwargs):
        raise OSError("모의 Job 설정 실패")

    target = stdio._WindowsJob
    monkeypatch.setattr(
        target, {"create": "_create", "configure": "_configure", "assign": "assign", "resume": "resume"}[stage], fail
    )
    client = session(definitions)
    with pytest.raises(ToolEnvironmentError):
        client.start()
    assert_closed(client)
    assert client._job is None or client._job.handle is None


def test_close_failure_still_closes_tree(definitions, tmp_path):
    client, pid_file = tree_session(definitions, tmp_path)
    client.start()
    pid = int(pid_file.read_text())

    class StuckIO:
        def join(self, **kwargs):
            raise RuntimeError("모의 IO 정리 실패")

        def is_alive(self):
            return False

    client._io = StuckIO()
    try:
        with pytest.raises(RuntimeError, match="정리"):
            client.close()
        assert client.state == "closed"
        wait_dead(pid)
        assert client.process.poll() is not None
        assert client._job is None or client._job.handle is None
        client.close()
    finally:
        emergency_kill(pid)


def test_tree_termination_failure_still_closes(definitions, monkeypatch):
    client = session(definitions)
    client.start()
    terminate = client._terminate_tree
    checked = []
    verify = client._verify_tree_stopped

    def fail_after_terminate():
        terminate()
        raise OSError("모의 트리 종료 오류")

    def verify_stopped():
        checked.append(True)
        verify()

    monkeypatch.setattr(client, "_terminate_tree", fail_after_terminate)
    monkeypatch.setattr(client, "_verify_tree_stopped", verify_stopped)
    with pytest.raises(RuntimeError, match="정리"):
        client.close()
    assert checked == [True]
    assert client.state == "closed"
    assert client.process.poll() is not None
    assert client._job is None or client._job.handle is None
    client.close()


def test_top_level_schema_keyword_ignored(definitions):
    expected = copy.deepcopy(definitions)
    expected[0]["parameters"]["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    tools = [{"name": t["name"], "inputSchema": copy.deepcopy(t["parameters"])} for t in expected]
    tools[0]["inputSchema"]["$schema"] = "http://json-schema.org/draft-07/schema#"
    original = copy.deepcopy(expected)
    with session(expected, inventory=tools):
        assert expected == original


@pytest.mark.parametrize("kind", ["properties", "nested_schema"])
def test_other_schema_differences_rejected(definitions, kind):
    tools = [{"name": t["name"], "inputSchema": copy.deepcopy(t["parameters"])} for t in definitions]
    if kind == "properties":
        tools[0]["inputSchema"]["properties"]["eng_extra"] = {"type": "string"}
    else:
        tools[0]["inputSchema"]["properties"]["owner"]["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    with pytest.raises(ToolEnvironmentError):
        with session(definitions, inventory=tools):
            raise AssertionError("최상위 $schema 외 차이는 거절해야 합니다.")


@pytest.mark.parametrize("signal_index", [0, 1])
def test_combined_cancel_signals(definitions, signal_index):
    signals = [Event(), Event()]
    with session(definitions, "call_timeout", cancel_signals=tuple(s.is_set for s in signals)) as client:
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(client, "list_issues", ARGS, 5)
            assert client.request_sent.wait(2)
            signals[signal_index].set()
            with pytest.raises(RunCancelled):
                pending.result(timeout=4)
        assert_closed(client)


def test_iserror_then_success_and_trace(definitions):
    from slotagent.common import contracts
    from slotagent.common.llm import FakeModel, Reply, ToolCall
    from slotagent.engine.loop import Dependencies, run_agent

    data = load("slot_and_candidates.json")
    snapshot = merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][0])
    model = FakeModel([
        Reply(tool_calls=(ToolCall("first", "list_issues", json.dumps(ARGS)),)),
        Reply(tool_calls=(ToolCall("second", "list_issues", json.dumps(ARGS)),)),
        Reply(text="다시 조회했습니다."),
    ])
    with session(definitions, "tool_error_once") as client:
        result = run_agent(snapshot, "이슈 조회", 1, Dependencies(model, client), prereg=load("experiment.json")["prereg"])
        assert client.state == "ready"
        assert result.outcome == "completed"
        assert len(model.requests) == 3
        spans = [s for s in result.trace["spans"] if s["kind"] == "tool"]
        assert spans[0]["error"] == "tool_error"
        assert spans[0]["tool_result"] == "failed"
        assert "error" not in spans[1]
        assert model.requests[1]["messages"][-1]["content"] == "failed"
        assert not any(s.get("error", "").startswith("env_") for s in result.trace["spans"])
        assert "outcome_reason" not in result.trace
        contracts.validate("trace", result.trace)
