"""① 워커가 직접 여는 stdio 세션과 임대 상실·복구를 확인합니다."""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from conftest import load
from psycopg import sql
from test_eng_queue import clean_queue as clean_queue
from test_eng_stdio import ARGS, connect_to, enqueue, rows
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.common.db_names import col, table
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine import advance, eng_stdio
from slotagent.engine.loop import RunCancelled, ToolEnvironmentError
from slotagent.workers.eng_main import run_once


@pytest.fixture
def observed_clients(monkeypatch):
    clients, ready = [], Event()
    original = eng_stdio.StdioTools

    class Observed(original):
        def start(self):
            super().start()
            clients.append(self)
            ready.set()

    monkeypatch.setattr(eng_stdio, "StdioTools", Observed)
    return clients, ready


def config(mode="ok", timeout_sec=5):
    from pathlib import Path

    data = load("slot_and_candidates.json")
    snap = merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][0])
    tools = [{"name": t["name"], "inputSchema": t["parameters"]} for t in snap["tools"] if t["access"] == "read"]
    argv = [
        sys.executable,
        "-u",
        str(Path(__file__).with_name("eng_stdio_server.py")),
        json.dumps({"tools": tools, "mode": mode}),
    ]
    return eng_stdio.LocalStdioConfig({"github": argv}, timeout_sec=timeout_sec)


def test_worker_creates_and_closes_stdio_session(experiment, engine_db, observed_clients):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    deps = dependencies(lambda *args: pytest.fail("주입한 가짜 라우터를 부르면 안 됩니다."))
    assert run_once(connect_to(engine_db), "stdio", deps=deps, stdio=config())
    clients, _ = observed_clients
    assert len(clients) == 1
    assert clients[0].state == "closed" and clients[0].process.poll() is not None
    assert rows(conn, "trials", ["status"], "id", trial) == [("finished",)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("done",)]
    assert len(rows(conn, "spans", ["seq"], "trial_id", trial)) == 3
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 2


def test_worker_session_is_per_trial(experiment, engine_db, observed_clients):
    conn, ids = experiment
    for trial in ids["trials"]:
        enqueue(conn, trial)
        assert run_once(connect_to(engine_db), "stdio", deps=dependencies(), stdio=config())
    clients, _ = observed_clients
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert all(c.state == "closed" and c.process.poll() is not None for c in clients)


def test_worker_setup_failure_is_recovered(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    bad = eng_stdio.LocalStdioConfig({"github": ["eng-does-not-exist"]})
    for attempt in range(1, 4):
        deps = dependencies()
        with pytest.raises(ToolEnvironmentError):
            run_once(connect_to(engine_db), "stdio", deps=deps, stdio=bad)
        assert not deps.model.requests
        assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", attempt + 1)]
    assert rows(conn, "jobs", ["status", "attempts"], "id", job) == [("failed", 3)]
    assert rows(conn, "cost_ledger", ["id"], "ref_id", trial) == []


def test_worker_lost_interrupts_stdio_wait(experiment, engine_db, observed_clients, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = enqueue(conn, trial)
    lost = Event()
    renew = queue.renew

    def heartbeat(*args, **kwargs):
        result = renew(*args, **kwargs)
        if not result:
            lost.set()
        return result

    monkeypatch.setattr(queue, "renew", heartbeat)
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(
            run_once,
            connect_to(engine_db),
            "stdio",
            deps=dependencies(),
            stdio=config("call_timeout", 10),
            heartbeat_sec=0.02,
        )
        clients, ready = observed_clients
        assert ready.wait(5) and clients[0].request_sent.wait(3)
        before = time.monotonic()
        conn.execute(
            sql.SQL("UPDATE {} SET {}=clock_timestamp()-interval '1 second' WHERE {}=%s").format(
                sql.Identifier(table("jobs")),
                sql.Identifier(col("jobs", "lease_until")),
                sql.Identifier(col("jobs", "id")),
            ),
            (job,),
        )
        with pytest.raises(RunCancelled):
            pending.result(timeout=3)
        assert lost.is_set() and time.monotonic() - before < 3
    assert clients[0].state == "closed" and clients[0].process.poll() is not None
    assert queue.reclaim(conn) == 1
    assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", 2)]
    assert rows(conn, "jobs", ["status"], "id", job) == [("queued",)]
    assert rows(conn, "spans", ["seq"], "trial_id", trial) == []
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 1


def test_worker_stdio_handoff_rollback(experiment, engine_db, observed_clients, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    enqueue(conn, trial)

    def fail(*args):
        raise RuntimeError("인계 실패")

    monkeypatch.setattr(advance, "on_trial_finished", fail)
    with pytest.raises(RuntimeError, match="인계 실패"):
        run_once(connect_to(engine_db), "stdio", deps=dependencies(), stdio=config())
    clients, _ = observed_clients
    assert clients[0].state == "closed"
    assert rows(conn, "trials", ["status", "attempt"], "id", trial) == [("pending", 2)]
    assert rows(conn, "spans", ["seq"], "trial_id", trial) == []
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 2


def test_worker_iserror_is_not_environment_failure(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    enqueue(conn, trial)
    deps = dependencies()
    deps.model = FakeModel(
        [
            Reply(tool_calls=(ToolCall("one", "list_issues", json.dumps(ARGS)),), in_tokens=10, out_tokens=1),
            Reply(tool_calls=(ToolCall("two", "list_issues", json.dumps(ARGS)),), in_tokens=10, out_tokens=1),
            Reply(text="완료", in_tokens=10, out_tokens=1),
        ]
    )
    assert run_once(connect_to(engine_db), "stdio", deps=deps, stdio=config("tool_error_once"))
    assert rows(conn, "trials", ["status", "run_outcome"], "id", trial) == [("finished", "completed")]
    errors = rows(conn, "spans", ["error"], "trial_id", trial)
    assert [e for (e,) in errors if e is not None] == ["tool_error"]
    assert len(rows(conn, "cost_ledger", ["id"], "ref_id", trial)) == 3
