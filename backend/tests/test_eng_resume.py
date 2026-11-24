"""① 수동 재개가 기존 작업의 시도 한도·원자성·비용을 보존하는지 확인합니다."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from conftest import load
from psycopg import sql
from test_eng_queue import clean_queue as clean_queue
from test_eng_stdio import connect_to, enqueue, rows
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import checks, queue
from slotagent.common.db_names import col, table
from slotagent.engine import advance
from slotagent.engine.costs import record_trial_cost
from slotagent.engine.loop import ToolEnvironmentError
from slotagent.engine.worker import run_trial
from slotagent.workers.eng_main import run_once


def change(conn, entity, key, value, **fields):
    conn.execute(
        sql.SQL("UPDATE {} SET {} WHERE {}=%s").format(
            sql.Identifier(table(entity)),
            sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(col(entity, k))) for k in fields),
            sql.Identifier(col(entity, key)),
        ),
        (*fields.values(), value),
    )


def failed_job(conn, trial, attempts=1, error="TypeError"):
    job_id = enqueue(conn, trial)
    job = queue.lease(conn, "failed")
    assert job["job_id"] == job_id
    queue.fail(conn, job, retry=False, error=error)
    change(conn, "jobs", "id", job_id, attempts=attempts)
    change(conn, "trials", "id", trial, attempt=attempts + 1)
    return job_id


def trial_jobs(conn, trial):
    return conn.execute(
        sql.SQL("SELECT {id} FROM {jobs} WHERE {kind}='run_trial' AND {payload}->>'trial_id'=%s").format(
            id=sql.Identifier(col("jobs", "id")),
            jobs=sql.Identifier(table("jobs")),
            kind=sql.Identifier(col("jobs", "kind")),
            payload=sql.Identifier(col("jobs", "payload")),
        ),
        (str(trial),),
    ).fetchall()


def test_resume_preserves_attempt_budget(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = failed_job(conn, trial)
    result = advance.resume_failed_trial(conn, trial)
    assert result.resumed and result.job_id == job
    assert rows(conn, "jobs", ["status", "attempts", "last_error"], "id", job) == [("queued", 1, "TypeError")]

    def permanent(*args):
        raise TypeError("수정되지 않은 설정")

    with pytest.raises(TypeError):
        run_once(connect_to(engine_db), "retry", deps=dependencies(permanent))
    assert rows(conn, "jobs", ["status", "attempts"], "id", job) == [("failed", 2)]
    assert advance.resume_failed_trial(conn, trial).resumed
    assert run_once(connect_to(engine_db), "retry", deps=dependencies())
    assert rows(conn, "jobs", ["status", "attempts"], "id", job) == [("done", 3)]
    assert trial_jobs(conn, trial) == [(job,)]
    assert not run_once(connect_to(engine_db), "retry", deps=dependencies())


def test_resume_concurrently_once(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = failed_job(conn, trial)
    gate = Barrier(2)

    def resume():
        with psycopg.connect(engine_db, autocommit=True) as other:
            gate.wait(timeout=3)
            return advance.resume_failed_trial(other, trial)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: resume(), range(2)))
    assert sum(r.resumed for r in results) == 1
    assert all(r.job_id == job for r in results)
    assert rows(conn, "jobs", ["status", "attempts"], "id", job) == [("queued", 1)]
    assert trial_jobs(conn, trial) == [(job,)]


@pytest.mark.parametrize(
    "last_error,reason",
    [
        ("ToolEnvironmentError", "env_mcp_server_down"),
        ("lease_expired", "env_worker_lost"),
        ("timeout_wall_clock", "timeout_wall_clock"),
    ],
)
def test_resume_exhausted_is_terminal(experiment, last_error, reason):
    conn, ids = experiment
    trial = ids["trials"][0]
    run_trial(conn, ids["trials"][1], deps=dependencies())
    job = failed_job(conn, trial, attempts=3, error=last_error)
    record_trial_cost(
        conn,
        trial_id=trial,
        attempt=1,
        experiment_id=ids["experiment"],
        price_setting_id=None,
        span={"seq": 1, "name": "fake", "in_tokens": 10, "out_tokens": 1, "attributes": {"cost_krw": "0.1"}},
    )
    before = rows(conn, "cost_ledger", ["id", "cost_krw"], "ref_id", trial)
    result = advance.resume_failed_trial(conn, trial)
    assert not result.resumed and result.exhausted
    assert rows(conn, "trials", ["status", "outcome_reason", "run_outcome"], "id", trial) == [
        ("error", reason, checks.run_outcome_for(reason, load("experiment.json")["prereg"]))
    ]
    assert rows(conn, "jobs", ["status", "attempts", "last_error"], "id", job) == [("failed", 3, last_error)]
    assert all(
        status != "pending" for (status,) in rows(conn, "trials", ["status"], "experiment_id", ids["experiment"])
    )
    assert rows(conn, "cost_ledger", ["id", "cost_krw"], "ref_id", trial) == before
    assert queue.lease(conn, "retry") is None


@pytest.mark.parametrize("last_error", ["RuntimeError", "ValueError", "CostPersistenceError", "TimeoutError", None])
def test_resume_unknown_failure_is_reported(experiment, last_error):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = failed_job(conn, trial, attempts=3, error=last_error)
    with pytest.raises(advance.UnmappedFailureError):
        advance.resume_failed_trial(conn, trial)
    assert rows(conn, "trials", ["status"], "id", trial) == [("pending",)]
    assert rows(conn, "jobs", ["status", "last_error"], "id", job) == [("failed", last_error)]


def test_resume_transaction_rollback(experiment, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    job = failed_job(conn, trial, attempts=3, error="ToolEnvironmentError")

    def broken(*args):
        raise RuntimeError("최종 인계 장애")

    monkeypatch.setattr(advance, "on_trial_finished", broken)
    with pytest.raises(RuntimeError, match="최종 인계 장애"):
        advance.resume_failed_trial(conn, trial)
    assert rows(conn, "trials", ["status"], "id", trial) == [("pending",)]
    assert rows(conn, "jobs", ["status", "attempts"], "id", job) == [("failed", 3)]


@pytest.mark.parametrize("state", ["stopped", "finished", "missing"])
def test_resume_invalid_state(experiment, state):
    conn, ids = experiment
    trial = ids["trials"][0]
    if state == "missing":
        trial = 999999999
    elif state == "finished":
        run_trial(conn, trial, deps=dependencies())
    else:
        failed_job(conn, trial)
        advance.stop_experiment(conn, ids["experiment"], "user")
    with pytest.raises(ValueError):
        advance.resume_failed_trial(conn, trial)


def test_worker_cannot_raise_global_attempt_limit(engine_db):
    with pytest.raises(ValueError):
        run_once(connect_to(engine_db), "retry", deps=dependencies(), max_attempts=4)


def test_mcp_initialize_timeout_exhaustion_is_environment_error(experiment, engine_db):
    from test_eng_worker_stdio import config

    conn, ids = experiment
    trial = ids["trials"][0]
    run_trial(conn, ids["trials"][1], deps=dependencies())
    job = enqueue(conn, trial)
    stdio = config("init_timeout", timeout_sec=0.4)
    for _ in range(3):
        deps = dependencies()
        with pytest.raises(ToolEnvironmentError) as caught:
            run_once(connect_to(engine_db), "stdio-timeout", deps=deps, stdio=stdio)
        assert caught.value.reason == "env_mcp_server_down"
        assert not deps.model.requests
    assert rows(conn, "jobs", ["status", "attempts", "last_error"], "id", job) == [("failed", 3, "env_mcp_server_down")]
    result = advance.resume_failed_trial(conn, trial)
    assert not result.resumed and result.exhausted
    assert rows(conn, "trials", ["status", "outcome_reason", "run_outcome"], "id", trial) == [
        ("error", "env_mcp_server_down", "env_error")
    ]
    assert load("experiment.json")["prereg"]["outcome_rules"]["env_error"] == "retry_then_exclude"
    grading = rows(conn, "grading_runs", ["id"], "experiment_id", ids["experiment"])[0][0]
    candidate = rows(conn, "trials", ["exp_candidate_id"], "id", ids["trials"][1])[0][0]
    units = conn.execute("SELECT * FROM analysis_units(%s,%s)", (grading, candidate)).fetchall()
    assert len(units) == 1 and units[0][2:] == (False, "env_error")
    assert rows(conn, "cost_ledger", ["id"], "ref_id", trial) == []
