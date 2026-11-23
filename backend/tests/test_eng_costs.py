"""① 중간 비용·늦은 응답·중복·장애 후의 실제 DB 상태와 호출 수를 검증합니다."""

import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from threading import Barrier

import psycopg
import pytest
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.common.llm import FakeModel, Reply
from slotagent.engine import advance, worker
from slotagent.engine.costs import CostConflictError, CostPersistenceError, record_trial_cost
from slotagent.engine.loop import Dependencies, RunCancelled
from slotagent.workers.eng_main import run_once


@pytest.fixture
def case(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    job_id = advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": trial})
    yield conn, ids, trial, job_id
    with psycopg.connect(engine_db, autocommit=True) as cleanup:
        cleanup.execute(
            "UPDATE sa_jobs SET status='cancelled',leased_by=NULL,lease_until=NULL WHERE status IN ('queued','leased')"
        )


def states(conn, trial, job_id):
    return (
        conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone(),
        conn.execute("SELECT status,attempts FROM sa_jobs WHERE job_id=%s", (job_id,)).fetchone(),
    )


def ledger(conn, trial):
    return conn.execute(
        "SELECT count(*),coalesce(sum(cost_krw),0) FROM sa_cost_ledger WHERE source='trial' AND ref_id=%s", (trial,)
    ).fetchone()


def receipt(ids, trial, *, attempt=1, seq=1):
    return dict(
        trial_id=trial,
        attempt=attempt,
        experiment_id=ids["experiment"],
        price_setting_id=None,
        span={"seq": seq, "name": "fake", "in_tokens": 100, "out_tokens": 10, "attributes": {"cost_krw": "2"}},
    )


def expire(conn, job_id):
    conn.execute("UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job_id,))


@pytest.mark.parametrize("error", [ValueError, NotImplementedError, RuntimeError])
def test_error_before_model_response_records_no_cost(case, engine_db, error):
    conn, ids, trial, job_id = case
    deps = dependencies()
    invoked = []

    def fail(**kwargs):
        invoked.append(kwargs)
        raise error("모의 호출 전 오류")

    deps.model.chat = fail
    with pytest.raises(error):
        run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert states(conn, trial, job_id) == (("pending", 2), ("queued" if error is RuntimeError else "failed", 1))
    assert ledger(conn, trial) == (0, 0)
    assert len(invoked) == 1


@pytest.mark.parametrize("error", [ValueError, NotImplementedError, RuntimeError])
def test_error_after_response_keeps_cost_and_stops_next_call(case, engine_db, error):
    conn, ids, trial, job_id = case
    tools = []

    def fail(*args):
        tools.append(args)
        raise error("모의 도구 오류")

    deps = dependencies(fail)
    with pytest.raises(error):
        run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert states(conn, trial, job_id) == (("pending", 2), ("queued" if error is RuntimeError else "failed", 1))
    assert ledger(conn, trial) == (1, Decimal("0.12"))
    assert len(deps.model.requests) == len(tools) == 1
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)


def test_identical_receipt_concurrently_commits_once(case, engine_db):
    conn, ids, trial, job_id = case
    barrier = Barrier(2)

    def save(_):
        with psycopg.connect(engine_db) as other:
            barrier.wait(timeout=10)
            record_trial_cost(other, **receipt(ids, trial))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(save, range(2)))
    record_trial_cost(conn, **receipt(ids, trial))
    assert ledger(conn, trial) == (1, 2)
    assert states(conn, trial, job_id) == (("pending", 1), ("queued", 0))


@pytest.mark.parametrize("field,value", [("in_tokens", 101), ("out_tokens", 11), ("cost_krw", "3")])
def test_same_key_different_receipt_is_an_error(case, field, value):
    conn, ids, trial, job_id = case
    item = receipt(ids, trial)
    record_trial_cost(conn, **item)
    changed = copy.deepcopy(item)
    if field == "cost_krw":
        changed["span"]["attributes"][field] = value
    else:
        changed["span"][field] = value
    with pytest.raises(CostConflictError):
        record_trial_cost(conn, **changed)
    assert ledger(conn, trial) == (1, 2)
    assert states(conn, trial, job_id) == (("pending", 1), ("queued", 0))


def test_receipt_conflict_fails_job_permanently(case, engine_db):
    conn, ids, trial, job_id = case
    record_trial_cost(conn, **receipt(ids, trial))
    deps = dependencies()
    with pytest.raises(CostConflictError):
        run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert states(conn, trial, job_id) == (("pending", 2), ("failed", 1))
    assert ledger(conn, trial) == (1, 2)
    assert len(deps.model.requests) == 1
    assert not run_once(lambda: psycopg.connect(engine_db), "w", deps=dependencies())


def test_final_save_and_duplicate_completion_do_not_add_cost(case, engine_db):
    conn, ids, trial, job_id = case
    deps = dependencies()
    assert run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert ledger(conn, trial) == (2, Decimal("0.264"))
    assert conn.execute(
        "SELECT attempt,span_seq FROM sa_cost_ledger WHERE source='trial' AND ref_id=%s ORDER BY span_seq", (trial,)
    ).fetchall() == [(1, 1), (1, 3)]
    assert states(conn, trial, job_id) == (("finished", 1), ("done", 1))
    duplicate = dependencies()
    assert worker.run_trial(conn, trial, deps=duplicate) is None
    assert not run_once(lambda: psycopg.connect(engine_db), "w", deps=duplicate)
    assert not duplicate.model.requests
    assert len(deps.model.requests) == 2
    assert ledger(conn, trial) == (2, Decimal("0.264"))


def test_late_old_response_is_charged_after_new_worker_finishes(case, engine_db):
    conn, ids, trial, job_id = case
    job = queue.lease(conn, "old")
    old = Dependencies(FakeModel([Reply(text="옛 답", in_tokens=2000)]), lambda *a: pytest.fail("도구 호출 금지"))
    new = Dependencies(FakeModel([Reply(text="새 답", in_tokens=3000)]), lambda *a: pytest.fail("도구 호출 금지"))
    chat = old.model.chat

    def delayed(**kwargs):
        reply = chat(**kwargs)
        with psycopg.connect(engine_db, autocommit=True) as other:
            expire(other, job_id)
            assert queue.reclaim(other, max_attempts=3) == 1
            replacement = queue.lease(other, "new")
            assert worker.run_trial(other, trial, deps=new, job=replacement).trace["attempt"] == 2
        return reply

    old.model.chat = delayed
    spans = []
    old.on_model_span = lambda span: spans.append(copy.deepcopy(span))
    with pytest.raises(RunCancelled):
        worker.run_trial(conn, trial, deps=old, job=job)
    assert states(conn, trial, job_id) == (("finished", 2), ("done", 2))
    price_id = conn.execute(
        "SELECT price_setting_id FROM sa_cost_ledger WHERE source='trial' AND ref_id=%s LIMIT 1", (trial,)
    ).fetchone()[0]
    record_trial_cost(
        conn, trial_id=trial, attempt=1, span=spans[0], experiment_id=ids["experiment"], price_setting_id=price_id
    )
    assert ledger(conn, trial) == (2, 5)
    assert len(old.model.requests) == len(new.model.requests) == 1
    assert conn.execute("SELECT DISTINCT attempt FROM sa_spans WHERE trial_id=%s", (trial,)).fetchall() == [(2,)]


def test_final_result_failure_does_not_roll_back_cost(case, engine_db, monkeypatch):
    conn, ids, trial, job_id = case

    def fail(*args):
        raise RuntimeError("결과 저장 후 인계 오류")

    deps = dependencies()
    monkeypatch.setattr(advance, "on_trial_finished", fail)
    with pytest.raises(RuntimeError):
        run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert states(conn, trial, job_id) == (("pending", 2), ("queued", 1))
    assert ledger(conn, trial) == (2, Decimal("0.264"))
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)
    assert len(deps.model.requests) == 2


def test_repeating_failure_is_bounded_and_all_attempt_costs_remain(case, engine_db):
    conn, ids, trial, job_id = case
    models = []

    def fail(*args):
        raise RuntimeError("반복 오류")

    for attempt in range(1, 4):
        deps = dependencies(fail)
        models.append(deps.model)
        with pytest.raises(RuntimeError):
            run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
        assert states(conn, trial, job_id) == (
            ("pending", attempt + 1),
            ("failed" if attempt == 3 else "queued", attempt),
        )
        assert ledger(conn, trial) == (attempt, Decimal("0.12") * attempt)
    unused = dependencies()
    assert not run_once(lambda: psycopg.connect(engine_db), "w", deps=unused)
    assert sum(len(model.requests) for model in models) == 3
    assert not unused.model.requests


class BrokenInsert:
    def __init__(self, conn):
        self.conn = conn

    def transaction(self):
        return self.conn.transaction()

    def execute(self, query, values=None):
        if query.lstrip().startswith("INSERT INTO sa_cost_ledger"):
            return self.conn.execute("SELECT 1/0")
        return self.conn.execute(query, values)


def test_cost_db_failure_uses_job_limit_without_own_retry(case, engine_db, monkeypatch):
    conn, ids, trial, job_id = case
    writes, models, tools = [], [], []

    def broken(conn, **values):
        writes.append(values)
        return record_trial_cost(BrokenInsert(conn), **values)

    monkeypatch.setattr(worker, "record_trial_cost", broken)
    for _ in range(3):
        deps = dependencies(lambda *args: tools.append(args) or "[]")
        models.append(deps.model)
        with pytest.raises(CostPersistenceError) as caught:
            run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
        assert "division" not in str(caught.value)
    assert states(conn, trial, job_id) == (("pending", 4), ("failed", 3))
    assert ledger(conn, trial) == (0, 0)
    assert len(writes) == sum(len(model.requests) for model in models) == 3
    assert not tools
    assert not run_once(lambda: psycopg.connect(engine_db), "w", deps=dependencies())


class LostCommitReply:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def transaction(self):
        with self.conn.transaction():
            yield
        raise psycopg.OperationalError("비공개 커밋 응답 유실")

    def execute(self, *args, **kwargs):
        return self.conn.execute(*args, **kwargs)


def test_committed_cost_with_lost_ack_replay_is_idempotent(case, engine_db, monkeypatch):
    conn, ids, trial, job_id = case
    captured = []

    def lost(conn, **values):
        captured.append(values)
        return record_trial_cost(LostCommitReply(conn), **values)

    monkeypatch.setattr(worker, "record_trial_cost", lost)
    deps = dependencies()
    with pytest.raises(CostPersistenceError):
        run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert states(conn, trial, job_id) == (("pending", 2), ("queued", 1))
    assert ledger(conn, trial) == (1, Decimal("0.12"))
    # 별도 자동 재시도 장치가 아니라, 같은 영수증이 재전달돼도 중복되지 않는지 검사합니다.
    record_trial_cost(conn, **captured[0])
    assert ledger(conn, trial) == (1, Decimal("0.12"))
    assert len(captured) == len(deps.model.requests) == 1


def test_stopped_experiment_still_records_inflight_response_cost(case, engine_db):
    conn, ids, trial, job_id = case
    tools = []
    deps = dependencies(lambda *a: tools.append(a) or "[]")
    chat = deps.model.chat

    def stop_then_reply(**kwargs):
        result = chat(**kwargs)
        advance.stop_experiment(conn, ids["experiment"], "user")
        return result

    deps.model.chat = stop_then_reply
    with pytest.raises(RunCancelled):
        run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert states(conn, trial, job_id) == (("cancelled", 2), ("cancelled", 1))
    assert ledger(conn, trial) == (1, Decimal("0.12"))
    assert len(deps.model.requests) == 1
    assert not tools


def test_preserved_cost_is_used_by_next_budget_check(case, engine_db):
    conn, ids, trial, job_id = case

    def fail(span):
        raise RuntimeError("비용 저장 뒤 종료")

    deps = Dependencies(FakeModel([Reply(text="비용 100원", in_tokens=100000)]), lambda *a: "", on_model_span=fail)
    with pytest.raises(RuntimeError):
        run_once(lambda: psycopg.connect(engine_db), "w", deps=deps)
    assert ledger(conn, trial) == (1, 100)
    unused = dependencies()
    assert run_once(lambda: psycopg.connect(engine_db), "w", deps=unused)
    assert not unused.model.requests
    assert len(deps.model.requests) == 1
    assert states(conn, trial, job_id) == (("cancelled", 2), ("done", 2))
    assert conn.execute(
        "SELECT status,stop_reason FROM sa_experiments WHERE experiment_id=%s", (ids["experiment"],)
    ).fetchone() == ("stopped", "budget")


@pytest.mark.parametrize("source", ["judge", "chat", "validation"])
def test_partial_index_does_not_restrict_other_sources(case, source):
    conn, ids, trial, job_id = case
    for _ in range(2):
        conn.execute(
            """INSERT INTO sa_cost_ledger(source,ref_id,attempt,span_seq,experiment_id,model,in_tokens,out_tokens,cost_krw)
               VALUES (%s,%s,1,1,%s,'fake',0,0,0)""",
            (source, trial, ids["experiment"]),
        )
    assert conn.execute(
        "SELECT count(*) FROM sa_cost_ledger WHERE source=%s AND ref_id=%s", (source, trial)
    ).fetchone() == (2,)
    assert states(conn, trial, job_id) == (("pending", 1), ("queued", 0))


def test_legacy_trial_costs_can_leave_new_fields_null(case):
    conn, ids, trial, job_id = case
    for _ in range(2):
        conn.execute(
            """INSERT INTO sa_cost_ledger(source,ref_id,model,in_tokens,out_tokens,cost_krw)
               VALUES ('trial',%s,'legacy',0,0,0)""",
            (trial,),
        )
    assert conn.execute("SELECT attempt,span_seq FROM sa_cost_ledger WHERE ref_id=%s", (trial,)).fetchall() == [
        (None, None),
        (None, None),
    ]
    assert ledger(conn, trial) == (2, 0)


def test_process_exit_after_cost_commit_is_reclaimed_without_losing_cost(case, engine_db):
    conn, ids, trial, job_id = case
    job = queue.lease(conn, "dead")
    identifiers = {k: job[k] for k in ("job_id", "attempts", "leased_by", "kind", "payload")}
    script = """import os,sys,json
from pathlib import Path
sys.path[:0] = [str(Path.cwd()/'src'),str(Path.cwd()/'tests')]
import psycopg
from test_eng_worker import dependencies
from slotagent.engine.worker import run_trial
conn=psycopg.connect(sys.argv[1],autocommit=True)
deps=dependencies()
deps.on_model_span=lambda span: os._exit(17)
run_trial(conn,int(sys.argv[2]),deps=deps,job=json.loads(sys.argv[3]))
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script, engine_db, str(trial), json.dumps(identifiers)], capture_output=True, timeout=20
    )
    assert crashed.returncode == 17
    assert ledger(conn, trial) == (1, Decimal("0.12"))
    expire(conn, job_id)
    assert queue.reclaim(conn, max_attempts=3) == 1
    assert states(conn, trial, job_id) == (("pending", 2), ("queued", 1))
    deps = dependencies()
    assert run_once(lambda: psycopg.connect(engine_db), "new", deps=deps)
    assert states(conn, trial, job_id) == (("finished", 2), ("done", 2))
    assert ledger(conn, trial) == (3, Decimal("0.384"))
    assert len(deps.model.requests) == 2


def test_database_disconnect_before_cost_commit_is_reclaimed(case, engine_db):
    conn, ids, trial, job_id = case
    job = queue.lease(conn, "lost")
    deps = dependencies()
    chat = deps.model.chat

    def disconnect(**kwargs):
        result = chat(**kwargs)
        with psycopg.connect(engine_db, autocommit=True) as other:
            other.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))
        return result

    deps.model.chat = disconnect
    with pytest.raises(CostPersistenceError):
        worker.run_trial(conn, trial, deps=deps, job=job)
    with psycopg.connect(engine_db, autocommit=True) as other:
        expire(other, job_id)
        assert queue.reclaim(other, max_attempts=3) == 1
        assert states(other, trial, job_id) == (("pending", 2), ("queued", 1))
        assert ledger(other, trial) == (0, 0)  # 실제 비용 미보존 위험 구간을 0원 과금으로 해석하지 않습니다.
    assert len(deps.model.requests) == 1
