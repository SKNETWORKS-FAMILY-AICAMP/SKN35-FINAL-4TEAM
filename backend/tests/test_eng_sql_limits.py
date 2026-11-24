"""① 트랜잭션 상한·비용 영수증만의 재시도·재과금 계수."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

import psycopg
import pytest
from test_eng_costs import case as case
from test_eng_costs import ledger, receipt, states
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.engine import worker
from slotagent.engine.costs import CostPersistenceError, record_trial_cost
from slotagent.workers.eng_main import run_once


def settings(conn):
    return conn.execute("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')").fetchone()


@pytest.mark.parametrize("outer", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_local_limits_restore(experiment, outer, failure):
    conn, _ = experiment
    conn.execute("SET lock_timeout='9s'")
    conn.execute("SET statement_timeout='11s'")

    def check():
        previous = settings(conn)
        if failure:
            with pytest.raises(psycopg.errors.QueryCanceled):
                with queue.transaction(conn, lock_ms=20, statement_ms=30):
                    assert settings(conn) == ("20ms", "30ms")
                    conn.execute("SELECT pg_sleep(1)")
        else:
            with queue.transaction(conn, lock_ms=20, statement_ms=30):
                assert settings(conn) == ("20ms", "30ms")
        assert settings(conn) == previous

    if outer:
        with conn.transaction():
            check()
    else:
        check()
    assert settings(conn) == ("9s", "11s")


class SlowInsert:
    def __init__(self, conn, failures):
        self.conn, self.failures, self.calls = conn, failures, 0

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, query, *args):
        if query.lstrip().startswith("INSERT INTO sa_cost_ledger"):
            self.calls += 1
            if self.calls <= self.failures:
                return self.conn.execute("SELECT pg_sleep(1)")
        return self.conn.execute(query, *args)


@pytest.mark.parametrize("failures", [2, 3])
def test_cost_receipt_bounded_retry(case, engine_db, monkeypatch, failures):
    conn, ids, trial, job_id = case
    monkeypatch.setattr(queue, "SQL_STATEMENT_TIMEOUT_MS", 30)
    writes = []

    def record(connection, **values):
        proxy = SlowInsert(connection, failures)
        writes.append(proxy)
        return record_trial_cost(proxy, **values)

    monkeypatch.setattr(worker, "record_trial_cost", record)
    deps = dependencies()
    if failures == 2:
        assert run_once(lambda: psycopg.connect(engine_db), "sql", deps=deps)
        assert ledger(conn, trial)[0] == 2
        assert len(deps.model.requests) == 2
    else:
        with pytest.raises(CostPersistenceError):
            run_once(lambda: psycopg.connect(engine_db), "sql", deps=deps)
        assert states(conn, trial, job_id) == (("pending", 2), ("failed", 1))
        assert not run_once(lambda: psycopg.connect(engine_db), "sql", deps=dependencies())
        assert len(deps.model.requests) == 1 and ledger(conn, trial)[0] == 0
    assert writes[0].calls == 3


def test_no_key_lock_allows_cost(experiment, engine_db):
    conn, ids = experiment
    with psycopg.connect(engine_db, autocommit=True) as final, psycopg.connect(engine_db, autocommit=True) as cost:
        with final.transaction(), ThreadPoolExecutor(1) as pool:
            final.execute(
                "SELECT experiment_id FROM sa_experiments WHERE experiment_id=%s FOR NO KEY UPDATE",
                (ids["experiment"],),
            )
            pool.submit(record_trial_cost, cost, **receipt(ids, ids["trials"][0])).result(timeout=2)
    assert ledger(conn, ids["trials"][0])[0] == 1


def test_final_timeout_recharge(case, engine_db, monkeypatch):
    conn, ids, trial, job_id = case
    monkeypatch.setattr(queue, "SQL_LOCK_TIMEOUT_MS", 30)
    locked, release = Event(), Event()

    def hold():
        with psycopg.connect(engine_db, autocommit=True) as blocker:
            with blocker.transaction():
                blocker.execute("SELECT trial_id FROM sa_trials WHERE trial_id=%s FOR UPDATE", (trial,))
                locked.set()
                assert release.wait(8)

    deps = dependencies()

    def received(span):
        if span["seq"] == 3:
            pool.submit(hold)
            assert locked.wait(3)

    deps.on_model_span = received
    with ThreadPoolExecutor(1) as pool:
        try:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                run_once(lambda: psycopg.connect(engine_db), "sql", deps=deps)
        finally:
            release.set()
    # 복구도 같은 잠금에 막힌 경우 임대 만료 회수로 이어집니다.
    conn.execute(
        "UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s AND status='leased'",
        (job_id,),
    )
    newer = dependencies()
    assert run_once(lambda: psycopg.connect(engine_db), "sql", deps=newer)
    assert len(deps.model.requests) == len(newer.model.requests) == 2
    assert ledger(conn, trial) == (4, Decimal("0.528"))
