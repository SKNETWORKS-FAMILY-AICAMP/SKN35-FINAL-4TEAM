"""① 완료 재전달은 부모 행 잠금·같은 트랜잭션에서 한 번만 작업을 만듭니다."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.engine import advance
from slotagent.engine.loop import ToolEnvironmentError
from slotagent.engine.worker import run_trial


def finished_grading(conn, ids, *, extra=False):
    if not extra:

        def fail(*args):
            raise ToolEnvironmentError()

        for trial in ids["trials"]:
            run_trial(conn, trial, deps=dependencies(fail))
        gr = conn.execute(
            "SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s", (ids["experiment"],)
        ).fetchone()[0]
    else:
        gr = conn.execute(
            """INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose)
               SELECT experiment_id,pack_version_id,'test','regrade' FROM sa_experiments
               WHERE experiment_id=%s RETURNING grading_run_id""",
            (ids["experiment"],),
        ).fetchone()[0]
    conn.execute("UPDATE sa_grading_runs SET finished_at=now() WHERE grading_run_id=%s", (gr,))
    return gr


def analysis(conn, ids, gr, *, interim=False, stop=False):
    return conn.execute(
        """INSERT INTO sa_analyses(experiment_id,grading_run_id,method,code_version,input_hash,is_interim,batch_no)
           VALUES (%s,%s,%s,'test',%s,%s,%s) RETURNING analysis_id""",
        (
            ids["experiment"],
            gr,
            Jsonb({"ci": {}, "correction": {}, "seed": 1124, "sequential": {"stop": stop}}),
            "a" * 64,
            interim,
            1 if interim else None,
        ),
    ).fetchone()[0]


def jobs(conn, kind, field, event):
    return conn.execute(
        "SELECT job_id FROM sa_jobs WHERE kind=%s AND payload->>%s=%s ORDER BY job_id", (kind, field, str(event))
    ).fetchall()


def concurrent(uri, callback, event):
    barrier = Barrier(20)

    def call(_):
        with psycopg.connect(uri, autocommit=True) as conn:
            conn.execute("SET statement_timeout='15s'")
            barrier.wait(timeout=20)
            return callback(conn, event)

    with ThreadPoolExecutor(20) as pool:
        return list(pool.map(call, range(20)))


def test_concurrent_grading(experiment, engine_db):
    conn, ids = experiment
    gr = finished_grading(conn, ids)
    results = concurrent(engine_db, advance.on_grading_finished, gr)
    assert len(set(results)) == 1
    assert jobs(conn, "analyze", "grading_run_id", gr) == [(results[0],)]


@pytest.mark.parametrize("interim,stop", [(False, False), (True, True), (True, False)])
def test_concurrent_analysis(experiment, engine_db, interim, stop):
    conn, ids = experiment
    gr = finished_grading(conn, ids)
    an = analysis(conn, ids, gr, interim=interim, stop=stop)
    concurrent(engine_db, advance.on_analysis_done, an)
    assert len(jobs(conn, "report", "analysis_id", an)) == (0 if interim and not stop else 1)
    status = conn.execute(
        "SELECT status,stop_reason FROM sa_experiments WHERE experiment_id=%s", (ids["experiment"],)
    ).fetchone()
    assert status == (("stopped", "interim") if interim and stop else ("running", None))


@pytest.mark.parametrize("event_type", ["grading", "final", "interim_stop"])
def test_rollback(experiment, event_type):
    conn, ids = experiment
    gr = finished_grading(conn, ids)
    if event_type == "grading":
        callback, event, kind, field = advance.on_grading_finished, gr, "analyze", "grading_run_id"
    else:
        an = analysis(conn, ids, gr, interim=event_type == "interim_stop", stop=True)
        callback, event, kind, field = advance.on_analysis_done, an, "report", "analysis_id"
    with pytest.raises(RuntimeError, match="rollback"):
        with conn.transaction():
            callback(conn, event)
            assert len(jobs(conn, kind, field, event)) == 1
            raise RuntimeError("rollback")
    assert jobs(conn, kind, field, event) == []
    assert conn.execute(
        "SELECT status FROM sa_experiments WHERE experiment_id=%s", (ids["experiment"],)
    ).fetchone() == ("running",)
    callback(conn, event)
    callback(conn, event)
    assert len(jobs(conn, kind, field, event)) == 1


def test_independent_events(experiment):
    conn, ids = experiment
    for gr in [finished_grading(conn, ids), finished_grading(conn, ids, extra=True)]:
        advance.on_grading_finished(conn, gr)
        advance.on_grading_finished(conn, gr)
        assert len(jobs(conn, "analyze", "grading_run_id", gr)) == 1
        an = analysis(conn, ids, gr)
        advance.on_analysis_done(conn, an)
        advance.on_analysis_done(conn, an)
        assert len(jobs(conn, "report", "analysis_id", an)) == 1


@pytest.mark.parametrize("status", ["queued", "leased", "done", "failed", "cancelled"])
def test_existing_job(experiment, status):
    conn, ids = experiment
    gr = finished_grading(conn, ids)
    an = analysis(conn, ids, gr)
    job = advance.on_grading_finished(conn, gr)
    advance.on_analysis_done(conn, an)
    report = jobs(conn, "report", "analysis_id", an)
    conn.execute(
        """UPDATE sa_jobs SET status=%s,leased_by=CASE WHEN %s='leased' THEN 'test' END,
           lease_until=CASE WHEN %s='leased' THEN now()+interval '1 minute' END
           WHERE job_id=ANY(%s)""",
        (status, status, status, [job, report[0][0]]),
    )
    assert advance.on_grading_finished(conn, gr) == job
    advance.on_analysis_done(conn, an)
    assert jobs(conn, "analyze", "grading_run_id", gr) == [(job,)]
    assert jobs(conn, "report", "analysis_id", an) == report
