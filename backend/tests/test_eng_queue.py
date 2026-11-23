"""① 실제 임시 DB에서 중복 임대·만료 회수·오래된 워커의 결과 차단을 확인합니다."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import psycopg
import pytest
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.engine import advance
from slotagent.engine.lock import lock_and_enqueue
from slotagent.engine.loop import RunCancelled
from slotagent.engine.worker import run_trial
from slotagent.workers.eng_main import run_once


@pytest.fixture(autouse=True)
def clean_queue(engine_db):
    """실험별 남은 작업이 다음 검사의 임대 순서에 섞이지 않도록 분리합니다."""
    yield
    with psycopg.connect(engine_db, autocommit=True) as conn:
        conn.execute(
            """UPDATE sa_jobs SET status='cancelled',lease_until=NULL,leased_by=NULL
               WHERE status IN ('queued','leased')"""
        )


def add_job(conn, trial, priority=0):
    return advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": trial}, priority)


def expire(conn, job):
    conn.execute(
        "UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job["job_id"],)
    )


def test_priority_skip_locked_and_tokens(experiment, engine_db):
    conn, ids = experiment
    low = add_job(conn, ids["trials"][0])
    high = add_job(conn, ids["trials"][1], 10)
    with psycopg.connect(engine_db) as blocker, psycopg.connect(engine_db) as other:
        blocker.execute("SELECT job_id FROM sa_jobs WHERE job_id=%s FOR UPDATE", (high,))
        job = queue.lease(other, "worker")
        assert job["job_id"] == low
        assert job["attempts"] == 1
        assert queue.renew(other, job)
        expire(conn, job)
        assert not queue.renew(other, job)
        with pytest.raises(queue.LeaseLost):
            queue.fail(other, job, retry=True)
        assert queue.reclaim(other) == 1
        replacement = queue.lease(other, "worker")
        assert replacement["job_id"] == low
        assert replacement["attempts"] == 2
        with other.transaction(), pytest.raises(queue.LeaseLost):
            queue.finish(other, job)
        with other.transaction():
            queue.finish(other, replacement)
    # 남은 높은 우선순위 작업도 정리하여 다음 실험과 분리합니다.
    job = queue.lease(conn, "worker")
    assert job["job_id"] == high
    queue.fail(conn, job, retry=False)


def test_reclaim_dead_worker_restores_trial_and_reexecutes(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    add_job(conn, trial)
    job = queue.lease(conn, "dead")
    # 별도 프로세스를 정상 정리 없이 종료하여 Python 예외 복구가 불가능한 상황을 만듭니다.
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os,sys,psycopg; c=psycopg.connect(sys.argv[1],autocommit=True); "
            "c.execute(\"UPDATE sa_trials SET status='running',started_at=now() WHERE trial_id=%s\",(int(sys.argv[2]),)); "
            "os._exit(17)",
            engine_db,
            str(trial),
        ],
        capture_output=True,
        timeout=15,
    )
    assert crashed.returncode == 17
    expire(conn, job)
    assert queue.reclaim(conn) == 1
    assert queue.reclaim(conn) == 0
    assert conn.execute("SELECT status,attempt,started_at FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
        "pending",
        2,
        None,
    )
    replacement = queue.lease(conn, "new")
    result = run_trial(conn, trial, deps=dependencies(), job=replacement)
    assert result.trace["attempt"] == 2
    assert conn.execute("SELECT status FROM sa_jobs WHERE job_id=%s", (job["job_id"],)).fetchone() == ("done",)


def test_old_worker_cannot_save_after_reclaim(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    add_job(conn, trial)
    job = queue.lease(conn, "old")

    def tool(*args):
        with psycopg.connect(engine_db, autocommit=True) as replacement:
            expire(replacement, job)
            assert queue.reclaim(replacement) == 1
            new_job = queue.lease(replacement, "new")
            run_trial(replacement, trial, deps=dependencies(), job=new_job)
        return "[]"

    with pytest.raises(RunCancelled):
        run_trial(conn, trial, deps=dependencies(tool), job=job)
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
        "finished",
        2,
    )
    assert conn.execute("SELECT DISTINCT attempt FROM sa_spans WHERE trial_id=%s", (trial,)).fetchall() == [(2,)]
    assert conn.execute(
        "SELECT count(*) FROM sa_cost_ledger WHERE source='trial' AND ref_id=%s", (trial,)
    ).fetchone() == (2,)


def test_expiry_blocks_save_even_before_reclaim(experiment):
    conn, ids = experiment
    trial = ids["trials"][0]
    add_job(conn, trial)
    job = queue.lease(conn, "old")

    def tool(*args):
        expire(conn, job)
        return "[]"

    with pytest.raises(RunCancelled):
        run_trial(conn, trial, deps=dependencies(tool), job=job)
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)
    assert queue.reclaim(conn) == 1


def test_reclaim_stopped_trial_cancels_without_retry(experiment):
    conn, ids = experiment
    trial = ids["trials"][0]
    add_job(conn, trial)
    job = queue.lease(conn, "dead")
    conn.execute("UPDATE sa_trials SET status='running' WHERE trial_id=%s", (trial,))
    advance.stop_experiment(conn, ids["experiment"], "user")
    expire(conn, job)
    assert queue.reclaim(conn) == 1
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
        "cancelled",
        2,
    )
    assert conn.execute("SELECT status FROM sa_jobs WHERE job_id=%s", (job["job_id"],)).fetchone() == ("cancelled",)


def test_disconnected_worker_is_recovered_by_another_connection(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    add_job(conn, trial)
    job = queue.lease(conn, "disconnected")

    def tool(*args):
        with psycopg.connect(engine_db, autocommit=True) as recovery:
            recovery.execute("SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,))
        return "[]"

    with pytest.raises(psycopg.OperationalError):
        run_trial(conn, trial, deps=dependencies(tool), job=job)
    with psycopg.connect(engine_db, autocommit=True) as recovery:
        expire(recovery, job)
        assert queue.reclaim(recovery) == 1
        assert recovery.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
            "pending",
            2,
        )
        replacement = queue.lease(recovery, "new")
        assert run_trial(recovery, trial, deps=dependencies(), job=replacement).trace["attempt"] == 2


def test_queue_completion_failure_rolls_back_all_results(experiment, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    add_job(conn, trial)
    job = queue.lease(conn, "worker")

    def broken(*args):
        raise RuntimeError("큐 완료 저장 장애")

    with monkeypatch.context() as context:
        context.setattr(queue, "finish", broken)
        with pytest.raises(RuntimeError, match="큐 완료 저장 장애"):
            run_trial(conn, trial, deps=dependencies(), job=job)
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)
    assert conn.execute(
        "SELECT count(*) FROM sa_cost_ledger WHERE ref_id=%s AND source='trial'", (trial,)
    ).fetchone() == (0,)
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("pending", 2)
    queue.fail(conn, job, retry=True)
    assert conn.execute("SELECT attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (2,)
    replacement = queue.lease(conn, "new")
    assert run_trial(conn, trial, deps=dependencies(), job=replacement).trace["attempt"] == 2


def test_worker_heartbeat_and_failure_return(experiment, engine_db, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    job_id = add_job(conn, trial)
    renewed = Event()
    original = queue.renew

    def renew(*args, **kwargs):
        result = original(*args, **kwargs)
        renewed.set()
        return result

    monkeypatch.setattr(queue, "renew", renew)

    def tool(*args):
        assert renewed.wait(5)
        raise RuntimeError("임시 오류")

    def connect():
        return psycopg.connect(engine_db)

    with pytest.raises(RuntimeError, match="임시 오류"):
        run_once(connect, "worker", deps=dependencies(tool), heartbeat_sec=0.01)
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("pending", 2)
    assert conn.execute("SELECT status FROM sa_jobs WHERE job_id=%s", (job_id,)).fetchone() == ("queued",)
    assert run_once(connect, "worker", deps=dependencies())
    assert conn.execute("SELECT status FROM sa_jobs WHERE job_id=%s", (job_id,)).fetchone() == ("done",)
    assert not run_once(connect, "worker", deps=dependencies())


def test_parallel_completions_create_one_grading_job(experiment, engine_db):
    conn, ids = experiment
    for trial in ids["trials"]:
        add_job(conn, trial)

    def execute(number):
        return run_once(lambda: psycopg.connect(engine_db), f"worker-{number}", deps=dependencies())

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert all(executor.map(execute, range(2)))
    assert conn.execute(
        "SELECT count(*) FROM sa_grading_runs WHERE experiment_id=%s", (ids["experiment"],)
    ).fetchone() == (1,)


def draft_copy(conn, exp):
    new = conn.execute(
        """INSERT INTO sa_experiments(kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by)
           SELECT kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by
           FROM sa_experiments WHERE experiment_id=%s RETURNING experiment_id""",
        (exp,),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash,template_scope)
           SELECT %s,candidate_id,label,role,config_snapshot,config_hash,template_scope
           FROM sa_experiment_candidates WHERE experiment_id=%s""",
        (new, exp),
    )
    return new


def test_lock_enqueue_idempotent_and_rollback(experiment, monkeypatch):
    conn, ids = experiment
    exp = draft_copy(conn, ids["experiment"])
    original = advance.enqueue

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("작업 등록 장애")

    with monkeypatch.context() as context:
        context.setattr(advance, "enqueue", broken)
        with pytest.raises(RuntimeError):
            lock_and_enqueue(conn, exp)
    assert conn.execute("SELECT status,locked_at FROM sa_experiments WHERE experiment_id=%s", (exp,)).fetchone() == (
        "draft",
        None,
    )
    assert conn.execute("SELECT count(*) FROM sa_trials WHERE experiment_id=%s", (exp,)).fetchone() == (0,)
    first = lock_and_enqueue(conn, exp)
    assert first == {"experiment_id": exp, "status": "running", "trials_total": 2}
    assert lock_and_enqueue(conn, exp) == first
    assert conn.execute(
        """SELECT count(*) FROM sa_jobs WHERE kind='run_trial' AND (payload->>'trial_id')::bigint
           IN (SELECT trial_id FROM sa_trials WHERE experiment_id=%s)""",
        (exp,),
    ).fetchone() == (2,)
    advance.stop_experiment(conn, exp, "user")


def connector(engine_db):
    return lambda: psycopg.connect(engine_db)


def test_permanent_error_fails_job_without_retry(experiment, engine_db):
    """설정·미지원 오류는 다시 돌려도 같으므로 작업을 바로 failed 로 두고 다시 빌려 주지 않습니다."""
    conn, ids = experiment
    trial = ids["trials"][0]
    job_id = add_job(conn, trial)
    with pytest.raises(TypeError):
        run_once(connector(engine_db), "worker", deps=dependencies(lambda *args: 145))
    assert conn.execute("SELECT status,attempts,last_error FROM sa_jobs WHERE job_id=%s", (job_id,)).fetchone() == (
        "failed",
        1,
        "TypeError",
    )
    # 풀이는 후보 실패로 기록하지 않고 pending 으로 남겨, 원인을 고친 뒤 다시 등록할 수 있게 합니다.
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("pending", 2)
    assert not run_once(connector(engine_db), "worker", deps=dependencies())


def test_transient_error_stops_at_max_attempts(experiment, engine_db):
    conn, ids = experiment
    trial = ids["trials"][0]
    job_id = add_job(conn, trial)

    def flaky(*args):
        raise RuntimeError("임시 오류")

    for expected in ("queued", "failed"):
        with pytest.raises(RuntimeError):
            run_once(connector(engine_db), "worker", deps=dependencies(flaky), max_attempts=2)
        assert conn.execute("SELECT status FROM sa_jobs WHERE job_id=%s", (job_id,)).fetchone() == (expected,)
    assert not run_once(connector(engine_db), "worker", deps=dependencies(), max_attempts=2)
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("pending", 3)


def test_reclaim_stops_requeueing_at_max_attempts(experiment, engine_db):
    """매번 프로세스를 죽이는 작업도 상한에서 멈춥니다."""
    conn, ids = experiment
    job_id = add_job(conn, ids["trials"][0])
    job = queue.lease(conn, "dead")
    expire(conn, job)
    assert queue.reclaim(conn, max_attempts=2) == 1
    assert conn.execute("SELECT status FROM sa_jobs WHERE job_id=%s", (job_id,)).fetchone() == ("queued",)
    job = queue.lease(conn, "dead")
    expire(conn, job)
    assert queue.reclaim(conn, max_attempts=2) == 1
    assert conn.execute("SELECT status,last_error FROM sa_jobs WHERE job_id=%s", (job_id,)).fetchone() == (
        "failed",
        "lease_expired",
    )
    with pytest.raises(ValueError):
        queue.reclaim(conn, max_attempts=0)
