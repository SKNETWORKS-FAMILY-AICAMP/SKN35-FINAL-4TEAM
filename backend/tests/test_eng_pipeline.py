"""① 채점 파이프라인: 실제 임시 DB에서 실행 → 규칙 채점 → 가짜 판정 → 분석 작업까지 확인합니다."""

import json

import psycopg
import pytest
from conftest import load
from psycopg.types.json import Jsonb
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.engine import advance
from slotagent.engine.loop import Dependencies
from slotagent.engine.worker import run_trial
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_pipeline import (
    JudgeNotConnected,
    Verdict,
    check_conditions,
    grade,
    load_trace,
    trial_metrics,
)
from slotagent.workers.eng_main import grade_once

ISSUE_ARGS = {"owner": "acme", "repo": "ops-service"}
NO_WRITE = ("forbidden", {"schema_version": 1, "call": {"access": "write"}})


def info(value):
    return ("info", {"schema_version": 1, "key": "answer", "expected": value, "match": "exact"})


def set_conditions(conn, trial, *conditions):
    """픽스처 팩은 이미 잠겨 있으므로 검사용으로 트리거만 잠시 끕니다."""
    conn.execute("SET session_replication_role = replica")
    for seq, (kind, spec) in enumerate(conditions, 1):
        conn.execute(
            """INSERT INTO sa_answer_conditions(task_id,seq,kind,spec)
               SELECT task_id,%s,%s,%s FROM sa_trials WHERE trial_id=%s""",
            (seq, kind, Jsonb(spec), trial),
        )
    conn.execute("SET session_replication_role = DEFAULT")


def answer(text, *calls):
    fake = FakeModel([*(Reply(tool_calls=(c,)) for c in calls), Reply(text=text)])
    return Dependencies(fake, lambda *a: '[{"number":145}]')


def prepare(experiment, *conditions, deps=None):
    conn, data = experiment
    set_conditions(conn, data["trials"][0], *(conditions or (NO_WRITE,)))
    for n, trial in enumerate(data["trials"]):
        run_trial(conn, trial, deps=deps[n] if deps else dependencies())
    run_id = conn.execute(
        "SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s", (data["experiment"],)
    ).fetchone()[0]
    return conn, data, run_id


def by_rules(conn, item):
    """가짜 ② 판정: 규칙이 모두 통과면 정답."""
    if item.run_outcome == "completed" and all(c.passed for c in item.conditions):
        return Verdict("correct")
    return Verdict("wrong_assertion", "final_answer")


def grades(conn, run_id):
    return conn.execute(
        "SELECT trial_id,grade_status,success,forbidden_action,out_of_scope FROM sa_trial_grades "
        "WHERE grading_run_id=%s ORDER BY trial_id",
        (run_id,),
    ).fetchall()


def finished(conn, run_id):
    return conn.execute("SELECT finished_at IS NOT NULL FROM sa_grading_runs WHERE grading_run_id=%s", (run_id,)).fetchone()[0]


def analyze_jobs(conn, run_id):
    return conn.execute(
        "SELECT count(*) FROM sa_jobs WHERE kind='analyze' AND payload->>'grading_run_id'=%s", (str(run_id),)
    ).fetchone()[0]


def job_status(conn, run_id):
    return conn.execute(
        "SELECT status FROM sa_jobs WHERE kind='grade' AND payload->>'grading_run_id'=%s", (str(run_id),)
    ).fetchone()[0]


def only_this(conn, run_id):
    """모듈 DB 를 같이 쓰는 다른 시험의 대기 채점 작업을 치웁니다."""
    conn.execute(
        "UPDATE sa_jobs SET status='cancelled' WHERE kind='grade' AND status='queued' AND payload->>'grading_run_id'<>%s",
        (str(run_id),),
    )


def test_run_to_grade_to_analyze_job(experiment, engine_db):
    write = ToolCall("w", "create_issue", json.dumps({**ISSUE_ARGS, "title": "x"}))
    conn, data, run_id = prepare(experiment, NO_WRITE, info("ok"), deps=[answer('{"answer":"ok"}'), answer('{"answer":"ok"}', write)])
    only_this(conn, run_id)
    connect = lambda: psycopg.connect(engine_db, autocommit=True)  # noqa: E731
    assert grade_once(connect, "g", classify=by_rules) is True
    a, b = data["trials"]
    assert grades(conn, run_id) == [(a, "graded", True, False, False), (b, "graded", False, True, False)]
    assert finished(conn, run_id) and analyze_jobs(conn, run_id) == 1 and job_status(conn, run_id) == "done"
    assert grade_once(connect, "g", classify=by_rules) is False


def test_without_judge_saves_rules_only(experiment):
    conn, _, run_id = prepare(experiment)
    for _ in range(2):
        with pytest.raises(JudgeNotConnected):
            grade(conn, run_id)
        assert conn.execute("SELECT count(*) FROM sa_condition_results WHERE grading_run_id=%s", (run_id,)).fetchone() == (2,)
    assert grades(conn, run_id) == [] and not finished(conn, run_id) and analyze_jobs(conn, run_id) == 0
    grade(conn, run_id, classify=by_rules)
    assert finished(conn, run_id) and analyze_jobs(conn, run_id) == 1


def test_worker_needs_judge_and_leaves_job_queued(experiment, engine_db):
    conn, _, run_id = prepare(experiment)
    with pytest.raises(ValueError, match="판정 함수"):
        grade_once(lambda: psycopg.connect(engine_db, autocommit=True), "g", classify=None)
    assert job_status(conn, run_id) == "queued"


def test_repeat_after_finish_changes_nothing(experiment):
    conn, _, run_id = prepare(experiment)
    grade(conn, run_id, classify=by_rules)
    before = grades(conn, run_id)
    grade(conn, run_id, classify=lambda *a: pytest.fail("다시 판정하면 안 됩니다."))
    assert grades(conn, run_id) == before and analyze_jobs(conn, run_id) == 1


def test_crash_resumes_without_rejudging(experiment):
    conn, data, run_id = prepare(experiment)
    seen = []

    def flaky(_, item):
        seen.append(item.trial_id)
        if len(seen) == 2:
            raise RuntimeError("판정기 중단")
        return Verdict("correct")

    with pytest.raises(RuntimeError):
        grade(conn, run_id, classify=flaky)
    assert len(grades(conn, run_id)) == 1 and not finished(conn, run_id)
    grade(conn, run_id, classify=flaky)
    assert seen == [data["trials"][0], data["trials"][1], data["trials"][1]] and finished(conn, run_id)


def test_undecided_condition_is_not_saved_as_failure(experiment):
    conn, _, run_id = prepare(experiment, info("ok"))  # 답이 JSON 이 아니라 규칙으로 못 정함
    items = []

    def keep(_, item):
        items.append(item)
        return Verdict("ask_or_giveup", "final_answer", judge_status="undecidable")

    grade(conn, run_id, classify=keep)
    assert len(items) == 2
    assert all(i.conditions[0].passed is None and i.conditions[0].undecided for i in items)
    assert conn.execute("SELECT count(*) FROM sa_condition_results WHERE grading_run_id=%s", (run_id,)).fetchone() == (0,)


def test_judge_cannot_overturn_rule_failure(experiment):
    conn, _, run_id = prepare(experiment, info("no"), deps=[answer('{"answer":"ok"}'), answer('{"answer":"ok"}')])
    with pytest.raises(ValueError, match="성공으로 바꿀 수 없습니다"):
        grade(conn, run_id, classify=lambda *a: Verdict("correct"))
    assert grades(conn, run_id) == [] and not finished(conn, run_id)


@pytest.mark.parametrize(
    "verdict",
    [
        Verdict("wrong_assertion"),
        Verdict("correct", "intent"),
        Verdict("maybe"),
        Verdict("wrong_assertion", "no_such"),
        Verdict("correct", judge_status="x"),
        Verdict("correct", fail_tags="text"),
        None,
        {"result_class": "correct"},
    ],
)
def test_bad_verdict_is_not_saved(experiment, verdict):
    conn, _, run_id = prepare(experiment)
    with pytest.raises((ValueError, TypeError)):
        grade(conn, run_id, classify=lambda *a: verdict)
    assert grades(conn, run_id) == []


def test_agent_error_cannot_succeed(experiment):
    refused = Dependencies(FakeModel([Reply(text="", finish_reason="refusal")]), lambda *a: "")
    conn, data, run_id = prepare(experiment, deps=[refused, dependencies()])
    with pytest.raises(ValueError, match="끝까지 실행하지 못한"):
        grade(conn, run_id, classify=lambda *a: Verdict("correct"))
    grade(conn, run_id, classify=lambda c, i: Verdict("ask_or_giveup") if i.run_outcome != "completed" else Verdict("correct"))
    assert [g[2] for g in grades(conn, run_id)] == [False, True]


def test_out_of_scope_comes_from_stored_scope(experiment):
    conn, data = experiment
    conn.execute("SET session_replication_role = replica")
    conn.execute(
        """UPDATE sa_experiment_candidates SET template_scope='{"T2":"out_of_scope"}' WHERE experiment_candidate_id=
           (SELECT experiment_candidate_id FROM sa_trials WHERE trial_id=%s)""",
        (data["trials"][1],),
    )
    conn.execute("SET session_replication_role = DEFAULT")
    conn, data, run_id = prepare(experiment)
    grade(conn, run_id, classify=lambda c, i: Verdict("ask_or_giveup") if i.out_of_scope else Verdict("correct"))
    assert [(g[2], g[4]) for g in grades(conn, run_id)] == [(True, False), (False, True)]


@pytest.mark.parametrize("scope", ["{}", '{"T2":"excluded_write"}'])
def test_missing_scope_stops_grading(experiment, scope):
    conn, data, run_id = prepare(experiment)
    conn.execute("SET session_replication_role = replica")
    conn.execute("UPDATE sa_experiment_candidates SET template_scope=%s WHERE experiment_id=%s", (scope, data["experiment"]))
    conn.execute("SET session_replication_role = DEFAULT")
    with pytest.raises(ValueError, match="범위 판정"):
        grade(conn, run_id, classify=by_rules)
    assert grades(conn, run_id) == []


def test_task_without_conditions_is_not_graded(experiment):
    conn, data = experiment
    for trial in data["trials"]:
        run_trial(conn, trial, deps=dependencies())
    run_id = conn.execute("SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s", (data["experiment"],)).fetchone()[0]
    with pytest.raises(ValueError, match="정답 조건이 없는"):
        grade(conn, run_id, classify=by_rules)


def test_broken_condition_stops_grading(experiment):
    conn, _, run_id = prepare(experiment, ("forbidden", {"schema_version": 1}))
    with pytest.raises(ValueError, match="answer_condition"):
        grade(conn, run_id, classify=by_rules)
    assert grades(conn, run_id) == [] and not finished(conn, run_id)


def test_unreadable_trace_becomes_grader_error_not_failure(experiment):
    conn, data, run_id = prepare(experiment)
    conn.execute("SET session_replication_role = replica")
    conn.execute("UPDATE sa_spans SET tool_args='[]' WHERE trial_id=%s AND kind='tool'", (data["trials"][0],))
    conn.execute("SET session_replication_role = DEFAULT")
    grade(conn, run_id, classify=by_rules)
    assert [(g[1], g[2]) for g in grades(conn, run_id)] == [("grader_error", None), ("graded", True)]
    assert finished(conn, run_id)


def test_env_error_trials_are_skipped(experiment):
    from slotagent.engine.loop import ToolEnvironmentError

    def down(*a):
        raise ToolEnvironmentError()

    conn, data, run_id = prepare(experiment, deps=[dependencies(down), dependencies()])
    assert conn.execute("SELECT run_outcome FROM sa_trials WHERE trial_id=%s", (data["trials"][0],)).fetchone() == ("env_error",)
    grade(conn, run_id, classify=by_rules)
    assert [g[0] for g in grades(conn, run_id)] == [data["trials"][1]]


def test_judge_runs_outside_transaction(experiment):
    conn, _, run_id = prepare(experiment)

    def leaves_open(c, item):
        c.execute("BEGIN")
        return Verdict("correct")

    def idle(c, item):
        assert c.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        return Verdict("correct")

    with pytest.raises(ValueError, match="트랜잭션"):
        grade(conn, run_id, classify=leaves_open)
    conn.rollback()
    grade(conn, run_id, classify=idle)


def test_open_transaction_does_not_block_giving_job_back(experiment, engine_db):
    conn, _, run_id = prepare(experiment)
    only_this(conn, run_id)

    def broken(c, item):
        c.execute("BEGIN")
        raise RuntimeError("중단")

    with pytest.raises(RuntimeError):
        grade_once(lambda: psycopg.connect(engine_db, autocommit=True), "g", classify=broken)
    assert job_status(conn, run_id) == "queued"


def test_permanent_failure_can_be_resumed_by_person(experiment, engine_db):
    conn, _, run_id = prepare(experiment)
    only_this(conn, run_id)
    connect = lambda: psycopg.connect(engine_db, autocommit=True)  # noqa: E731
    with pytest.raises(ValueError):
        grade_once(connect, "g", classify=lambda *a: Verdict("maybe"))
    assert job_status(conn, run_id) == "failed"
    assert advance.resume_failed_grading(conn, run_id) is True
    assert advance.resume_failed_grading(conn, run_id) is False
    assert grade_once(connect, "g", classify=by_rules) is True
    assert finished(conn, run_id) and advance.resume_failed_grading(conn, run_id) is False


def test_lost_lease_saves_no_grade(experiment, engine_db):
    conn, _, run_id = prepare(experiment)
    only_this(conn, run_id)

    def expire(c, item):
        c.execute("UPDATE sa_jobs SET lease_until=now()-interval '1 second' WHERE kind='grade' AND payload->>'grading_run_id'=%s", (str(run_id),))
        return Verdict("correct")

    with pytest.raises(queue.LeaseLost):
        grade_once(lambda: psycopg.connect(engine_db, autocommit=True), "g", classify=expire)
    assert grades(conn, run_id) == []
    assert queue.reclaim(conn, kinds=("run_trial",)) == 0
    assert queue.reclaim(conn, kinds=("grade",)) == 1 and job_status(conn, run_id) == "queued"


def test_db_trace_gives_same_rule_results_as_engine_trace(experiment):
    write = ToolCall("w", "create_issue", json.dumps({**ISSUE_ARGS, "title": "x"}))
    read = ToolCall("r", "list_issues", json.dumps(ISSUE_ARGS))
    conn, data = experiment
    set_conditions(conn, data["trials"][0], NO_WRITE, info("ok"))
    trace = run_trial(conn, data["trials"][0], deps=answer('{"answer":"ok"}', read, write, read)).trace
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        trial = cur.execute("SELECT * FROM sa_trials WHERE trial_id=%s", (data["trials"][0],)).fetchone()
    snap = conn.execute(
        "SELECT config_snapshot FROM sa_experiment_candidates WHERE experiment_candidate_id=%s",
        (trial["experiment_candidate_id"],),
    ).fetchone()[0]
    stored = load_trace(conn, trial)
    conditions = [{"answer_condition_id": n, "seq": n, "kind": k, "spec": s} for n, (k, s) in enumerate((NO_WRITE, info("ok")), 1)]
    context = from_snapshot(snap, None)
    assert check_conditions(conditions, stored, context) == check_conditions(conditions, trace, context)
    assert stored["write_intents"] == trace["write_intents"]
    metrics = trial_metrics(stored)
    assert (metrics["tool_calls"], metrics["distinct_tools"], metrics["repeated_calls"], metrics["steps"]) == (3, 2, 1, 7)
    assert metrics == trial_metrics(trace)


def test_metrics_empty_results():
    span = {"seq": 1, "kind": "tool", "name": "a", "started_at": "2026-11-25T00:00:00Z", "duration_sec": 1}
    results = ["[]", "{}", "", "null", "[1]", "없음", "[" * 5000]
    trace = {"spans": [{**span, "seq": n, "tool_result": r} for n, r in enumerate(results, 1)]}
    assert trial_metrics(trace)["empty_results"] == 4


def test_judge_item_hides_candidate(experiment):
    conn, _, run_id = prepare(experiment)
    items = []
    grade(conn, run_id, classify=lambda c, i: items.append(i) or Verdict("correct"))
    assert not {"label", "candidate", "config_snapshot", "role"} & set(vars(items[0]))
    assert items[0].prompt == next(t["prompt"] for t in load("pack.json")["tasks"] if t["code"] == "T2-0")
