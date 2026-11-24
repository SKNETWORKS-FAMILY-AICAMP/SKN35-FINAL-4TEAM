"""① 잠금에 막힌 최종 저장은 모델을 다시 부르지 않고 저장만 다시 시도합니다."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

import psycopg
import pytest
from test_eng_costs import case as case
from test_eng_costs import ledger, states
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.engine import worker
from slotagent.engine.loop import RunCancelled
from slotagent.workers.eng_main import run_once


@pytest.fixture
def short_limits(monkeypatch):
    monkeypatch.setattr(queue, "SQL_LOCK_TIMEOUT_MS", 100)
    monkeypatch.setattr(worker, "FINAL_SAVE_DELAYS", (0.05, 0.05), raising=False)


def count(conn, table, trial):
    return conn.execute(f"SELECT count(*) FROM {table} WHERE trial_id=%s", (trial,)).fetchone()[0]


def count_saves(monkeypatch, on_attempt=lambda n: None):
    """저장 함수에 들어간 횟수를 셉니다."""
    original, calls = worker._save_result, []

    def save(*args, **kwargs):
        calls.append(1)
        on_attempt(len(calls))
        return original(*args, **kwargs)

    monkeypatch.setattr(worker, "_save_result", save)
    return calls


class Blocker:
    """다른 연결이 행을 잡고 있게 합니다."""

    def __init__(self, uri, query, value):
        self.conn = psycopg.connect(uri)
        self.conn.execute(query, (value,))

    def release(self):
        self.conn.rollback()
        self.conn.close()


LOCKS = {
    "trial": "SELECT 1 FROM sa_trials WHERE trial_id=%s FOR UPDATE",
    "experiment": "SELECT 1 FROM sa_experiments WHERE experiment_id=%s FOR UPDATE",
    "job": "SELECT 1 FROM sa_jobs WHERE job_id=%s FOR UPDATE",
}


@pytest.mark.parametrize("target", list(LOCKS))
def test_blocked_save_retries_without_model_call(case, engine_db, monkeypatch, short_limits, target):
    conn, ids, trial, job_id = case
    value = {"trial": trial, "experiment": ids["experiment"], "job": job_id}[target]
    blockers = []

    def on_attempt(n):
        if n == 1:
            blockers.append(Blocker(engine_db, LOCKS[target], value))
        elif n == 2:
            blockers[0].release()

    calls = count_saves(monkeypatch, on_attempt)
    deps = dependencies()
    assert run_once(lambda: psycopg.connect(engine_db), "save", deps=deps)
    assert len(calls) == 2
    assert len(deps.model.requests) == 2
    assert ledger(conn, trial) == (2, Decimal("0.264"))
    assert states(conn, trial, job_id) == (("finished", 1), ("done", 1))
    assert count(conn, "sa_spans", trial) == 3


@pytest.mark.parametrize(
    "error", [psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled, psycopg.errors.DeadlockDetected]
)
def test_partial_write_rolls_back_before_retry(case, engine_db, monkeypatch, short_limits, error):
    """span을 다 쓴 뒤 실패해도 다음 시도에서 중복되지 않습니다."""
    conn, ids, trial, job_id = case
    original, seen = worker.advance.on_trial_finished, []

    def fail_once(connection, trial_id):
        seen.append(connection.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial_id,)).fetchone()[0])
        if len(seen) == 1:
            raise error("모의 실패")
        return original(connection, trial_id)

    monkeypatch.setattr(worker.advance, "on_trial_finished", fail_once)
    deps = dependencies()
    assert run_once(lambda: psycopg.connect(engine_db), "save", deps=deps)
    assert seen == [3, 3]
    assert len(deps.model.requests) == 2
    assert ledger(conn, trial) == (2, Decimal("0.264"))
    assert count(conn, "sa_spans", trial) == 3
    assert states(conn, trial, job_id) == (("finished", 1), ("done", 1))


def test_retry_is_bounded(case, engine_db, monkeypatch, short_limits):
    conn, ids, trial, job_id = case
    calls = count_saves(monkeypatch)
    blocker = []
    monkeypatch.setattr(
        worker.contracts,
        "validate",
        _hook(worker.contracts.validate, trial, lambda: blocker.append(Blocker(engine_db, LOCKS["trial"], trial))),
    )
    deps = dependencies()
    try:
        with pytest.raises(psycopg.errors.LockNotAvailable):
            run_once(lambda: psycopg.connect(engine_db), "save", deps=deps)
    finally:
        blocker[0].release()
    assert len(calls) == 3
    assert len(deps.model.requests) == 2
    assert ledger(conn, trial) == (2, Decimal("0.264"))
    assert count(conn, "sa_spans", trial) == 0


def _hook(original, trial, action):
    def validate(name, value, *args, **kwargs):
        if name == "trace" and value.get("trial_id") == trial:
            action()
        return original(name, value, *args, **kwargs)

    return validate


@pytest.mark.parametrize("error", [psycopg.OperationalError("연결 끊김"), RuntimeError("모의"), ValueError("모의")])
def test_other_errors_are_not_retried(case, engine_db, monkeypatch, short_limits, error):
    """커밋됐는지 알 수 없는 연결 오류와 일반 오류는 저장을 다시 시도하지 않습니다."""
    conn, ids, trial, job_id = case
    calls = count_saves(monkeypatch)

    def fail(*args):
        raise error

    monkeypatch.setattr(worker.advance, "on_trial_finished", fail)
    with pytest.raises(type(error)):
        run_once(lambda: psycopg.connect(engine_db), "save", deps=dependencies())
    assert len(calls) == 1
    assert count(conn, "sa_spans", trial) == 0
    assert ledger(conn, trial)[0] == 2


@pytest.mark.parametrize("change", ["attempt", "stopped", "lease"])
def test_ownership_rechecked_on_each_retry(case, engine_db, monkeypatch, short_limits, change):
    """기다리는 사이 소유권을 잃으면 다음 시도에서 저장하지 않습니다."""
    conn, ids, trial, job_id = case
    original, seen = worker.advance.on_trial_finished, []

    def on_attempt(n):
        if n == 2 and change == "attempt":
            conn.execute("UPDATE sa_trials SET attempt=attempt+1 WHERE trial_id=%s", (trial,))
        elif n == 2 and change == "stopped":
            worker.advance.stop_experiment(conn, ids["experiment"], "user")
        elif n == 2:
            conn.execute(
                "UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job_id,)
            )

    def fail_once(connection, trial_id):
        seen.append(1)
        if len(seen) == 1:
            raise psycopg.errors.LockNotAvailable("모의 실패")
        return original(connection, trial_id)

    calls = count_saves(monkeypatch, on_attempt)
    monkeypatch.setattr(worker.advance, "on_trial_finished", fail_once)
    with pytest.raises(queue.LeaseLost if change == "lease" else RunCancelled):
        run_once(lambda: psycopg.connect(engine_db), "save", deps=dependencies())
    assert len(calls) == 2 and len(seen) == 1
    assert count(conn, "sa_spans", trial) == 0
    assert ledger(conn, trial)[0] == 2


def slow_model(deps, seen):
    """임대 연장이 몇 번 돌 때까지 첫 모델 응답을 붙잡습니다."""
    original = deps.model.chat

    def chat(**kwargs):
        assert seen.wait(8)
        return original(**kwargs)

    deps.model.chat = chat


def test_heartbeat_survives_transient_lock(case, engine_db, monkeypatch):
    conn, ids, trial, job_id = case
    original, results, seen = queue.renew, [], Event()

    def renew(*args, **kwargs):
        if len(results) < 2:
            results.append("blocked")
            raise psycopg.errors.LockNotAvailable("모의 잠금")
        results.append(original(*args, **kwargs))
        seen.set()
        return results[-1]

    monkeypatch.setattr(queue, "renew", renew)
    deps = dependencies()
    slow_model(deps, seen)
    assert run_once(lambda: psycopg.connect(engine_db), "save", deps=deps, heartbeat_sec=0.05)
    assert results[:3] == ["blocked", "blocked", True]
    assert states(conn, trial, job_id) == (("finished", 1), ("done", 1))
    assert len(deps.model.requests) == 2


@pytest.mark.parametrize("failure", ["expired", "disconnected"])
def test_heartbeat_real_loss_still_cancels(case, engine_db, monkeypatch, failure):
    conn, ids, trial, job_id = case
    seen = Event()

    def renew(*args, **kwargs):
        seen.set()
        if failure == "expired":
            return False
        raise psycopg.OperationalError("연결 끊김")

    monkeypatch.setattr(queue, "renew", renew)
    deps = dependencies()
    slow_model(deps, seen)
    with pytest.raises(RunCancelled):
        run_once(lambda: psycopg.connect(engine_db), "save", deps=deps, heartbeat_sec=0.05)
    assert count(conn, "sa_spans", trial) == 0


def test_recover_lock_allows_cost(case, engine_db):
    """회수 중인 트랜잭션이 다른 풀이의 비용 저장을 막지 않습니다."""
    from test_eng_costs import receipt

    from slotagent.engine.costs import record_trial_cost

    conn, ids, trial, job_id = case
    job = queue.lease(conn, "recover")
    with psycopg.connect(engine_db, autocommit=True) as reclaiming, psycopg.connect(engine_db, autocommit=True) as cost:
        with reclaiming.transaction(), ThreadPoolExecutor(1) as pool:
            queue._recover_trial(reclaiming, job)
            other = next(t for t in ids["trials"] if t != trial)
            pool.submit(record_trial_cost, cost, **receipt(ids, other)).result(timeout=3)
    assert ledger(conn, other)[0] == 1
