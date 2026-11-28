"""① 실험 종료 게이트: 덜 끝난 실험이 done 이 되지 않고, 막힌 실험은 이어서 끝내거나 사람이 포기할 수 있는지 봅니다."""

import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_eng_advance_idempotency import analysis
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.engine import advance
from slotagent.engine.worker import run_trial
from slotagent.grading.eng_pipeline import Verdict, grade


def run(conn, *trials):
    for trial in trials:
        run_trial(conn, trial, deps=dependencies())


def grading(conn, ids, *, regrade=False, upto=None):
    if regrade:
        gr = conn.execute(
            """INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose,upto_batch_no)
               SELECT experiment_id,pack_version_id,'test','regrade',%s::int FROM sa_experiments WHERE experiment_id=%s
               RETURNING grading_run_id""",
            (upto, ids["experiment"]),
        ).fetchone()[0]
    else:
        gr = conn.execute("SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s AND purpose='initial'",
                          (ids["experiment"],)).fetchone()[0]
    conditions(conn, ids)
    grade(conn, gr, classify=lambda *_: Verdict("correct"))
    return gr


def conditions(conn, ids):
    """픽스처 팩은 잠겨 있고 조건이 없어 검사용으로 한 번만 넣습니다."""
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        conn.execute(
            """INSERT INTO sa_answer_conditions(task_id,seq,kind,spec)
               SELECT task_id,1,'forbidden','{"schema_version":1,"call":{"access":"write"}}' FROM sa_trials t
               WHERE trial_id=%s AND NOT EXISTS (SELECT 1 FROM sa_answer_conditions c WHERE c.task_id=t.task_id)""",
            (ids["trials"][0],),
        )


def report(conn, ids, an, *kinds):
    for kind in kinds or advance.REPORT_KINDS:
        conn.execute("INSERT INTO sa_reports(experiment_id,analysis_id,kind,content) VALUES (%s,%s,%s,%s)",
                     (ids["experiment"], an, kind, Jsonb({})))


def status(conn, ids):
    return conn.execute("SELECT status,stop_reason FROM sa_experiments WHERE experiment_id=%s",
                        (ids["experiment"],)).fetchone()


def ready(experiment):
    conn, ids = experiment
    run(conn, *ids["trials"])
    an = analysis(conn, ids, grading(conn, ids))
    return conn, ids, an


def test_complete_experiment_is_done_once(experiment):
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    assert advance.on_reports_done(conn, ids["experiment"]) == []
    assert advance.on_reports_done(conn, ids["experiment"]) == []
    assert status(conn, ids) == ("done", None)


@pytest.mark.parametrize("kinds", [(), ("one_pager",), ("detail",)])
def test_missing_report_blocks(experiment, kinds):
    conn, ids, an = ready(experiment)
    if kinds:
        report(conn, ids, an, *kinds)
    assert advance.on_reports_done(conn, ids["experiment"]) == ["reports_missing"]
    assert status(conn, ids) == ("running", None)


def test_reports_of_two_analyses_are_not_mixed(experiment):
    conn, ids, an = ready(experiment)
    other = analysis(conn, ids, grading(conn, ids, regrade=True))
    report(conn, ids, an, "one_pager")
    report(conn, ids, other, "detail")
    assert advance.on_reports_done(conn, ids["experiment"]) == ["reports_missing"]


def test_reports_of_other_experiment_do_not_count(experiment):
    conn, ids, an = ready(experiment)
    other = conn.execute(
        """INSERT INTO sa_experiments(kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by)
           SELECT kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by
           FROM sa_experiments WHERE experiment_id=%s RETURNING experiment_id""", (ids["experiment"],)).fetchone()[0]
    report(conn, {**ids, "experiment": other}, an)
    assert advance.on_reports_done(conn, ids["experiment"]) == ["reports_missing"]
    assert status(conn, ids) == ("running", None)


def test_missing_grade_blocks(experiment):
    """DB 가 막는 상태지만, 채점이 빠진 분석은 게이트도 최종으로 보지 않습니다."""
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        conn.execute("DELETE FROM sa_trial_grades WHERE trial_id=%s", (ids["trials"][0],))
    assert advance.on_reports_done(conn, ids["experiment"]) == ["analysis_missing"]


def test_parallel_reports_then_gate_in_same_transaction(experiment, engine_db):
    """두 워커가 리포트 저장과 통지를 한 트랜잭션에 넣어도 둘 다 저장되고 마지막 쪽이 끝냅니다."""
    conn, ids, an = ready(experiment)
    barrier = threading.Barrier(2)

    def write(kind):
        with psycopg.connect(engine_db, autocommit=True) as c, c.transaction():
            report(c, ids, an, kind)
            barrier.wait(timeout=10)
            return advance.on_reports_done(c, ids["experiment"])

    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(write, advance.REPORT_KINDS))
    assert sorted(result) == [[], ["reports_missing"]]
    assert status(conn, ids) == ("done", None)


def test_interim_analysis_is_not_final(experiment):
    conn, ids = experiment
    run(conn, *ids["trials"])
    an = analysis(conn, ids, grading(conn, ids), interim=True)
    report(conn, ids, an)
    assert advance.on_reports_done(conn, ids["experiment"]) == ["analysis_missing"]


def test_partial_grading_cannot_finish_experiment(experiment):
    """앞 묶음만 채점한 분석·리포트가 먼저 나와도 끝나지 않고, 전체를 채점해야 끝납니다."""
    conn, ids = experiment
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        conn.execute("UPDATE sa_trials SET batch_no=2 WHERE trial_id=%s", (ids["trials"][1],))
    run(conn, ids["trials"][0])
    early = analysis(conn, ids, grading(conn, ids, regrade=True, upto=1))
    report(conn, ids, early)
    assert advance.on_reports_done(conn, ids["experiment"]) == ["trials_unfinished", "analysis_missing"]
    run(conn, ids["trials"][1])
    assert advance.on_reports_done(conn, ids["experiment"]) == ["analysis_missing"]
    final = analysis(conn, ids, grading(conn, ids, regrade=True))
    report(conn, ids, final)
    assert advance.on_reports_done(conn, ids["experiment"]) == []
    assert status(conn, ids) == ("done", None)


def test_env_errors_in_later_batch_do_not_hide_partial_scope(experiment):
    """뒤 묶음이 모두 환경 오류라 채점할 풀이가 없어도, 앞 묶음까지만 본 분석은 최종이 아닙니다."""
    from slotagent.engine.loop import ToolEnvironmentError

    conn, ids = experiment
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        conn.execute("UPDATE sa_trials SET batch_no=2 WHERE trial_id=%s", (ids["trials"][1],))

    def down(*_):
        raise ToolEnvironmentError()

    run(conn, ids["trials"][0])
    run_trial(conn, ids["trials"][1], deps=dependencies(down))
    report(conn, ids, analysis(conn, ids, grading(conn, ids, regrade=True, upto=1)))
    assert advance.on_reports_done(conn, ids["experiment"]) == ["analysis_missing"]
    report(conn, ids, analysis(conn, ids, grading(conn, ids, regrade=True, upto=2)))
    assert advance.on_reports_done(conn, ids["experiment"]) == []


@pytest.mark.parametrize("state,blocker", [("pending", "trials_unfinished"), ("running", "trials_unfinished"),
                                           ("cancelled", "trials_cancelled")])
def test_leftover_trial_blocks(experiment, state, blocker):
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        conn.execute("UPDATE sa_trials SET status=%s,run_outcome=NULL,outcome_reason=NULL,finished_at=NULL WHERE trial_id=%s",
                     (state, ids["trials"][0]))
    assert blocker in advance.on_reports_done(conn, ids["experiment"])
    assert status(conn, ids) == ("running", None)


def test_env_error_trial_does_not_block(experiment):
    from slotagent.engine.loop import ToolEnvironmentError

    conn, ids = experiment

    def down(*_):
        raise ToolEnvironmentError()

    run_trial(conn, ids["trials"][0], deps=dependencies(down))
    run(conn, ids["trials"][1])
    an = analysis(conn, ids, grading(conn, ids))
    report(conn, ids, an)
    assert advance.on_reports_done(conn, ids["experiment"]) == []


@pytest.mark.parametrize("reason,final", [("user", "stopped"), ("job_failed", "failed")])
def test_stopped_experiment_is_not_revived(experiment, reason, final):
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    advance.stop_experiment(conn, ids["experiment"], reason)
    assert advance.on_reports_done(conn, ids["experiment"]) == []
    assert status(conn, ids) == (final, reason)


def test_unknown_experiment(experiment):
    conn, _ = experiment
    for callback in (advance.on_reports_done, advance.abandon_failed_experiment):
        with pytest.raises(ValueError):
            callback(conn, 2**62)


def test_gate_waits_for_concurrent_stop(experiment, engine_db):
    """멈춤이 먼저 잠그면 게이트는 기다렸다가 done 으로 덮지 않습니다."""
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    result = []
    with psycopg.connect(engine_db, autocommit=True) as other:
        with other.transaction():
            advance.stop_experiment(other, ids["experiment"], "user")
            thread = threading.Thread(target=lambda: result.append(advance.on_reports_done(conn, ids["experiment"])))
            thread.start()
            thread.join(0.2)
            assert thread.is_alive()
        thread.join(5)
    assert result == [[]] and status(conn, ids) == ("stopped", "user")


# ---- 사람이 포기 ----------------------------------------------------------
def fail_job(conn, kind, field, value):
    return conn.execute(
        "INSERT INTO sa_jobs(kind,payload,status,attempts,last_error) VALUES (%s,%s,'failed',3,'ValueError') RETURNING job_id",
        (kind, Jsonb({"schema_version": 1, "kind": kind, field: value})),
    ).fetchone()[0]


def test_abandon_failed_trial(experiment):
    conn, ids = experiment
    run(conn, ids["trials"][0])
    job = fail_job(conn, "run_trial", "trial_id", ids["trials"][1])
    assert advance.abandon_failed_experiment(conn, ids["experiment"]) == 1
    assert status(conn, ids) == ("failed", "job_failed")
    assert conn.execute("SELECT status FROM sa_trials WHERE experiment_id=%s ORDER BY trial_id",
                        (ids["experiment"],)).fetchall() == [("finished",), ("cancelled",)]
    assert conn.execute("SELECT status,last_error FROM sa_jobs WHERE job_id=%s", (job,)).fetchone() == ("failed", "ValueError")
    assert advance.abandon_failed_experiment(conn, ids["experiment"]) == 0
    with pytest.raises(ValueError):
        advance.resume_failed_trial(conn, ids["trials"][1])


def test_abandon_needs_a_failed_job(experiment):
    conn, ids = experiment
    with pytest.raises(ValueError, match="끝내 실패한 작업"):
        advance.abandon_failed_experiment(conn, ids["experiment"])
    fail_job(conn, "run_trial", "trial_id", ids["trials"][0])
    # 실패 뒤 새 작업이 다시 들어갔거나 풀이가 끝났으면 실패로 보지 않습니다.
    advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": ids["trials"][0]})
    with pytest.raises(ValueError, match="끝내 실패한 작업"):
        advance.abandon_failed_experiment(conn, ids["experiment"])
    assert status(conn, ids)[0] in {"locked", "running"}


def test_abandon_ignores_other_experiments_jobs(experiment):
    conn, ids = experiment
    fail_job(conn, "run_trial", "trial_id", 2**40)
    fail_job(conn, "grade", "grading_run_id", 2**40)
    with pytest.raises(ValueError, match="끝내 실패한 작업"):
        advance.abandon_failed_experiment(conn, ids["experiment"])


def fail_stage(conn, ids, kind):
    """그 단계가 아직 안 끝난 채 작업만 실패한 상태. 돌려주는 값: payload 칸 이름과 번호."""
    if kind == "grade":
        field, event = "grading_run_id", conn.execute(
            "SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s", (ids["experiment"],)).fetchone()[0]
    elif kind == "analyze":
        field, event = "grading_run_id", grading(conn, ids)
    else:
        field, event = "analysis_id", analysis(conn, ids, grading(conn, ids))
    conn.execute("DELETE FROM sa_jobs WHERE kind=%s AND payload->>%s=%s", (kind, field, str(event)))
    fail_job(conn, kind, field, event)
    return field, event


@pytest.mark.parametrize("kind", ["grade", "analyze", "report"])
def test_abandon_after_later_stage_failed(experiment, kind):
    conn, ids = experiment
    run(conn, *ids["trials"])
    fail_stage(conn, ids, kind)
    assert advance.abandon_failed_experiment(conn, ids["experiment"]) == 0
    assert status(conn, ids) == ("failed", "job_failed")


@pytest.mark.parametrize("kind", ["grade", "analyze", "report"])
@pytest.mark.parametrize("state", ["queued", "done"])
def test_abandon_ignores_failure_taken_over_by_new_job(experiment, kind, state):
    conn, ids = experiment
    run(conn, *ids["trials"])
    field, event = fail_stage(conn, ids, kind)
    job = fail_job(conn, kind, field, event)
    conn.execute("UPDATE sa_jobs SET status=%s WHERE job_id=%s", (state, job))
    with pytest.raises(ValueError, match="끝내 실패한 작업"):
        advance.abandon_failed_experiment(conn, ids["experiment"])
    # 이어받은 작업까지 실패하면 다시 포기할 수 있습니다.
    conn.execute("UPDATE sa_jobs SET status='failed' WHERE job_id=%s", (job,))
    assert advance.abandon_failed_experiment(conn, ids["experiment"]) == 0


@pytest.mark.parametrize("kind", ["grade", "analyze", "report"])
def test_abandon_ignores_failure_of_finished_stage(experiment, kind):
    """작업 행은 failed 로 남았어도 결과가 이미 저장됐으면 실패로 보지 않습니다."""
    conn, ids = experiment
    run(conn, *ids["trials"])
    field, event = fail_stage(conn, ids, kind)
    if kind == "grade":
        grading(conn, ids)
    elif kind == "analyze":
        analysis(conn, ids, event)
    else:
        report(conn, ids, event)
    with pytest.raises(ValueError, match="끝내 실패한 작업"):
        advance.abandon_failed_experiment(conn, ids["experiment"])


@pytest.mark.parametrize("state", ["failed", "queued"])
def test_malformed_job_does_not_break_abandon(experiment, state):
    """다른 작업의 payload 가 잘못돼도 판단과 취소가 그대로 됩니다."""
    conn, ids = experiment
    for kind, field in (("run_trial", "trial_id"), ("grade", "grading_run_id"), ("report", "analysis_id")):
        for value in ("not-an-id", None, {"a": 1}, 1.5):
            job = fail_job(conn, kind, field, value)
            conn.execute("UPDATE sa_jobs SET status=%s WHERE job_id=%s", (state, job))
    with pytest.raises(ValueError, match="끝내 실패한 작업"):
        advance.abandon_failed_experiment(conn, ids["experiment"])
    fail_job(conn, "run_trial", "trial_id", ids["trials"][0])
    assert advance.abandon_failed_experiment(conn, ids["experiment"]) == len(ids["trials"])
    assert status(conn, ids) == ("failed", "job_failed")


def test_abandon_rejects_finished_or_stopped(experiment):
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    fail_job(conn, "report", "analysis_id", an)
    advance.on_reports_done(conn, ids["experiment"])
    with pytest.raises(ValueError, match="진행 중인"):
        advance.abandon_failed_experiment(conn, ids["experiment"])
    assert status(conn, ids) == ("done", None)


def test_gate_rolls_back_with_caller(experiment):
    conn, ids, an = ready(experiment)
    report(conn, ids, an)
    with pytest.raises(RuntimeError), conn.transaction():
        assert advance.on_reports_done(conn, ids["experiment"]) == []
        raise RuntimeError("호출자 롤백")
    assert status(conn, ids) == ("running", None)
    with queue.transaction(conn):
        assert advance.completion_blockers(conn, ids["experiment"]) == []


def test_final_analysis_is_newest_with_both_reports(experiment):
    """리포트 있는 A, 더 최신이지만 리포트 없는 B, 더 최신 중간 분석 C → 근거는 A (status 의 latest 는 C)."""
    conn, ids, a = ready(experiment)
    assert advance.final_analysis_id(conn, ids["experiment"]) is None
    report(conn, ids, a)
    b = analysis(conn, ids, grading(conn, ids, regrade=True))
    c = analysis(conn, ids, grading(conn, ids, regrade=True), interim=True)
    assert advance.complete_analysis_ids(conn, ids["experiment"]) == [a, b]
    assert advance.final_analysis_id(conn, ids["experiment"]) == a < b < c
    report(conn, ids, b)
    assert advance.final_analysis_id(conn, ids["experiment"]) == b
    assert advance.on_reports_done(conn, ids["experiment"]) == []
