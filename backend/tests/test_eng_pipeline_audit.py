"""① 채점 파이프라인 독립 감사. 제품 파일은 바꾸지 않고 메모리 변이만 주입합니다."""

import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import psycopg
import pytest
from conftest import ROOT
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_eng_pipeline import answer, info, prepare, set_conditions
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import checks, contracts, queue
from slotagent.common.hashing import canonical_hash
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.engine import advance, worker
from slotagent.engine.loop import Dependencies, ToolEnvironmentError, ToolExecutionError
from slotagent.grading import eng_pipeline as pipeline
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_pipeline import Verdict
from slotagent.workers import eng_main


@pytest.fixture(autouse=True)
def cleanup_audit_jobs(engine_db):
    yield
    with psycopg.connect(engine_db, autocommit=True) as conn:
        conn.execute(
            "UPDATE sa_jobs SET status='cancelled',leased_by=NULL,lease_until=NULL WHERE status IN ('queued','leased')"
        )


def rows(conn, table, run_id):
    return conn.execute(f"SELECT * FROM {table} WHERE grading_run_id=%s", (run_id,)).fetchall()


def state(conn, run_id):
    return (
        len(rows(conn, "sa_condition_results", run_id)),
        len(rows(conn, "sa_trial_grades", run_id)),
        conn.execute(
            "SELECT finished_at IS NOT NULL FROM sa_grading_runs WHERE grading_run_id=%s", (run_id,)
        ).fetchone()[0],
        conn.execute(
            "SELECT count(*) FROM sa_jobs WHERE kind='analyze' AND payload->>'grading_run_id'=%s", (str(run_id),)
        ).fetchone()[0],
    )


def rewrite(conn, query, args=()):
    """잠긴 감사 fixture의 입력 변경에만 씁니다. 연결은 pgserver 임시 DB입니다."""
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        conn.execute(query, args)


def isolate_job(conn, run_id):
    conn.execute(
        "UPDATE sa_jobs SET status='cancelled' WHERE kind='grade' AND status='queued' AND payload->>'grading_run_id'<>%s",
        (str(run_id),),
    )


def correct(*_):
    return Verdict("correct")


@pytest.mark.parametrize("kind", ["link_default", "link_explicit", "info", "order", "end_state", "exact_writes"])
def test_gate_false_failure_does_not_block_success(experiment, kind):
    variants = {
        "link_default": (
            "link",
            {"schema_version": 1, "key": "evidence", "seen": {"result_contains": ["MISSING"]}, "supports": ["answer"]},
        ),
        "info": ("info", {**info("wrong")[1], "key": "diagnostic", "gate": False}),
        "order": (
            "order",
            {"schema_version": 1, "gate": False, "before": {"tool": "absent"}, "after": {"tool": "list_issues"}},
        ),
        "end_state": ("end_state", {"schema_version": 1, "gate": False, "write_intents": [{"tool": "create_issue"}]}),
        "exact_writes": (
            "exact_writes",
            {
                "schema_version": 1,
                "gate": False,
                "writes": [
                    {"capability": "github.issues.write", "target": ["ops-service"], "attempts": 1, "applied": 1}
                ],
            },
        ),
    }
    variants["link_explicit"] = ("link", {**variants["link_default"][1], "gate": False})
    diagnostic = variants[kind]
    assert not checks.condition_gate(*diagnostic)
    conn, _, run_id = prepare(
        experiment, info("ok"), diagnostic, deps=[answer('{"answer":"ok","diagnostic":"ok"}') for _ in range(2)]
    )
    pipeline.grade(conn, run_id, classify=correct)
    assert conn.execute(
        "SELECT bool_and(success) FROM sa_trial_grades WHERE grading_run_id=%s", (run_id,)
    ).fetchone() == (True,)
    assert state(conn, run_id) == (4, 2, True, 1)


@pytest.mark.parametrize("kind", ["forbidden", "exact_writes", "info"])
def test_gate_true_failure_cannot_be_overturned(experiment, kind):
    specs = {
        "forbidden": {"schema_version": 1, "call": {"tool": "list_issues"}},
        "exact_writes": {
            "schema_version": 1,
            "writes": [{"capability": "github.issues.write", "target": ["ops-service"], "attempts": 1, "applied": 1}],
        },
        "info": info("wrong")[1],
    }
    deps = [answer('{"answer":"ok"}') for _ in range(2)] if kind == "info" else [dependencies() for _ in range(2)]
    conn, _, run_id = prepare(experiment, (kind, specs[kind]), deps=deps)
    with pytest.raises(ValueError, match="성공으로 바꿀 수 없습니다"):
        pipeline.grade(conn, run_id, classify=correct)
    assert state(conn, run_id) == (1, 0, False, 0)


def test_false_gate_is_visible_to_classifier(experiment):
    conn, _, run_id = prepare(experiment, ("info", {**info("ok")[1], "gate": False}))
    run, trials = pipeline._run(conn, run_id)
    item = pipeline._grade_rules(conn, run, trials[0], None)
    assert getattr(item.conditions[0], "gate", None) is False


@pytest.mark.parametrize("phase", ["rules", "after_judge", "before_finish"])
def test_crash_resume_boundaries(experiment, monkeypatch, phase):
    conn, data, run_id = prepare(experiment)
    called = []

    def judge(c, item):
        called.append(item.trial_id)
        return Verdict("correct")

    original_save, original_finish = pipeline._save_grade, pipeline._finish
    with monkeypatch.context() as patch:
        if phase == "rules":

            def die(*_):
                raise RuntimeError("규칙 커밋 뒤 중단")

            classify = die
        else:
            classify = judge

            def die(*_):
                raise RuntimeError("판정 뒤 중단")

            patch.setattr(pipeline, "_save_grade" if phase == "after_judge" else "_finish", die)
        with pytest.raises(RuntimeError):
            pipeline.grade(conn, run_id, classify=classify)
    assert pipeline._save_grade is original_save and pipeline._finish is original_finish
    before = state(conn, run_id)
    assert (
        before
        == ({"rules": (1, 0, False, 0), "after_judge": (1, 0, False, 0), "before_finish": (2, 2, False, 0)}[phase])
    )
    pipeline.grade(conn, run_id, classify=judge)
    assert state(conn, run_id) == (2, 2, True, 1)
    assert called == (data["trials"] if phase != "after_judge" else [data["trials"][0], *data["trials"]])


@pytest.mark.parametrize("phase", ["rules", "after_judge", "before_finish"])
def test_process_exit_resume_boundaries(experiment, engine_db, phase):
    conn, data, run_id = prepare(experiment)
    program = r"""
import os,sys,psycopg
sys.path[:0] = ["src", "tests"]
from slotagent.grading import eng_pipeline as p
uri,run_id,phase=sys.argv[1],int(sys.argv[2]),sys.argv[3]
original=p._grade_rules
if phase == "rules":
    def after_rules(*a,**k):
        value=original(*a,**k)
        os._exit(91)
    p._grade_rules=after_rules
if phase == "before_finish":
    p._finish=lambda *a,**k: os._exit(91)
def judge(conn,item):
    print(item.trial_id,flush=True)
    if phase == "after_judge":
        os._exit(91)
    return p.Verdict("correct")
with psycopg.connect(uri,autocommit=True) as conn:
    p.grade(conn,run_id,classify=judge)
"""
    child = subprocess.run(
        [sys.executable, "-c", program, engine_db, str(run_id), phase], capture_output=True, text=True, timeout=20
    )
    assert child.returncode == 91, child.stderr
    assert state(conn, run_id) == ((2, 2, False, 0) if phase == "before_finish" else (1, 0, False, 0))
    resumed = []
    pipeline.grade(conn, run_id, classify=lambda c, item: resumed.append(item.trial_id) or Verdict("correct"))
    assert resumed == ([] if phase == "before_finish" else data["trials"])
    assert state(conn, run_id) == (2, 2, True, 1)


def test_rule_conflict_is_detected_instead_of_mixed_results(experiment, monkeypatch):
    conn, _, run_id = prepare(experiment, info("wrong"), deps=[answer('{"answer":"ok"}') for _ in range(2)])
    with pytest.raises(pipeline.JudgeNotConnected):
        pipeline.grade(conn, run_id)
    assert conn.execute(
        "SELECT bool_or(passed) FROM sa_condition_results WHERE grading_run_id=%s", (run_id,)
    ).fetchone() == (False,)
    monkeypatch.setattr(pipeline, "check", lambda *a, **k: (True, {"span_seqs": []}))
    with pytest.raises(ValueError):
        pipeline.grade(conn, run_id, classify=correct)
    assert rows(conn, "sa_trial_grades", run_id) == []


@pytest.mark.parametrize("source", ["rule_bug", "metrics_bug", "semantic_condition"])
def test_non_trace_errors_do_not_become_permanent_grader_error(experiment, monkeypatch, source):
    condition = ("info", {**info("not-a-number")[1], "match": "number"}) if source == "semantic_condition" else None
    conn, _, run_id = prepare(
        experiment, *([condition] if condition else []), deps=[answer('{"answer":1}') for _ in range(2)]
    )

    def bug(*_, **__):
        raise ValueError("코드 결함")

    if source != "semantic_condition":
        monkeypatch.setattr(pipeline, "check" if source == "rule_bug" else "trial_metrics", bug)
    with pytest.raises(ValueError):
        pipeline.grade(conn, run_id, classify=correct)
    assert rows(conn, "sa_trial_grades", run_id) == []


def test_bad_trace_only_marks_its_own_trial(experiment):
    conn, data, run_id = prepare(experiment)
    rewrite(conn, "UPDATE sa_spans SET tool_args='[]' WHERE trial_id=%s AND kind='tool'", (data["trials"][0],))
    pipeline.grade(conn, run_id, classify=correct)
    assert conn.execute(
        "SELECT grade_status,success FROM sa_trial_grades WHERE grading_run_id=%s ORDER BY trial_id", (run_id,)
    ).fetchall() == [("grader_error", None), ("graded", True)]
    assert state(conn, run_id) == (1, 2, True, 1)


@pytest.mark.parametrize("source", ["hash", "scope", "builtin", "condition"])
def test_snapshot_or_pack_error_stops_without_grader_error(experiment, source):
    conn, data, run_id = prepare(experiment)
    if source == "hash":
        rewrite(
            conn,
            "UPDATE sa_experiment_candidates SET config_hash=%s WHERE experiment_id=%s",
            ("sha256:" + "0" * 64, data["experiment"]),
        )
    elif source == "scope":
        rewrite(
            conn,
            "UPDATE sa_experiment_candidates SET template_scope='{}' WHERE experiment_id=%s",
            (data["experiment"],),
        )
    elif source == "condition":
        rewrite(
            conn,
            "UPDATE sa_answer_conditions SET spec='{}' WHERE task_id=(SELECT task_id FROM sa_trials WHERE trial_id=%s)",
            (data["trials"][0],),
        )
    else:
        snap = conn.execute(
            "SELECT config_snapshot FROM sa_experiment_candidates WHERE experiment_id=%s LIMIT 1", (data["experiment"],)
        ).fetchone()[0]
        snap["tools"][0]["name"] = "request_user_confirmation"
        rewrite(
            conn,
            "UPDATE sa_experiment_candidates SET config_snapshot=%s,config_hash=%s WHERE experiment_id=%s",
            (Jsonb(snap), canonical_hash(snap), data["experiment"]),
        )
    with pytest.raises(ValueError):
        pipeline.grade(conn, run_id, classify=correct)
    assert state(conn, run_id) == (0, 0, False, 0)


@pytest.mark.parametrize("phase", ["rules", "grade", "finish", "grader_error"])
def test_lease_fences_every_write(experiment, monkeypatch, phase):
    conn, data, run_id = prepare(experiment)
    isolate_job(conn, run_id)
    job = queue.lease(conn, "old-audit", kinds=("grade",), lease_sec=60)
    run, trials = pipeline._run(conn, run_id)
    item = None
    if phase in {"grade", "finish"}:
        item = pipeline._grade_rules(conn, run, trials[0], job)
    if phase == "grader_error":
        monkeypatch.setattr(pipeline, "load_trace", lambda *_: (_ for _ in ()).throw(ValueError("못 읽음")))
    conn.execute(
        "UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job["job_id"],)
    )
    before = state(conn, run_id)
    with pytest.raises(queue.LeaseLost):
        if phase in {"rules", "grader_error"}:
            pipeline._grade_rules(conn, run, trials[0], job)
        elif phase == "grade":
            pipeline._save_grade(conn, item, Verdict("correct"), job)
        else:
            pipeline._finish(conn, run, job)
    assert state(conn, run_id) == before


def test_heartbeat_renews_during_long_classifier(experiment, engine_db, monkeypatch):
    conn, _, run_id = prepare(experiment)
    isolate_job(conn, run_id)
    original_lease, original_renew = queue.lease, queue.renew
    renewed = Event()

    def short_lease(c, *a, **kw):
        job = original_lease(c, *a, **kw)
        if job:
            c.execute(
                "UPDATE sa_jobs SET lease_until=clock_timestamp()+interval '0.4 second' WHERE job_id=%s",
                (job["job_id"],),
            )
        return job

    def renew(*a, **kw):
        result = original_renew(*a, **kw)
        if result:
            renewed.set()
        return result

    monkeypatch.setattr(queue, "lease", short_lease)
    monkeypatch.setattr(queue, "renew", renew)

    def slow(c, item):
        assert renewed.wait(3)
        # 원래의 0.4초 임대보다 긴 시간은 DB pg_sleep로 확보합니다.
        with psycopg.connect(engine_db, autocommit=True) as timer:
            timer.execute("SELECT pg_sleep(0.5)")
        return Verdict("correct")

    assert eng_main.grade_once(
        lambda: psycopg.connect(engine_db, autocommit=True), "long-audit", classify=slow, heartbeat_sec=0.03
    )
    assert state(conn, run_id) == (2, 2, True, 1)


def test_concurrent_direct_call_after_other_finishes(experiment, engine_db):
    conn, data, run_id = prepare(experiment)
    run, _ = pipeline._run(conn, run_id)
    second = pipeline._grade_rules(conn, run, data["trials"][1], None)
    pipeline._save_grade(conn, second, Verdict("correct"), None)
    both, first_done = Barrier(2), Event()

    def execute(last):
        def judge(c, item):
            both.wait(timeout=5)
            if last:
                assert first_done.wait(5)
            return Verdict("correct")

        try:
            with psycopg.connect(engine_db, autocommit=True) as connection:
                pipeline.grade(connection, run_id, classify=judge)
            return None
        except Exception as exc:
            return type(exc).__name__
        finally:
            if not last:
                first_done.set()

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(execute, last) for last in [False, True]]
        results = [f.result(timeout=15) for f in futures]
    assert state(conn, run_id) == (2, 2, True, 1)
    assert results == [None, None], results


def test_two_workers_do_not_duplicate_grades(experiment, engine_db):
    conn, _, run_id = prepare(experiment)
    isolate_job(conn, run_id)
    start = Barrier(2)

    def execute(n):
        start.wait(timeout=5)
        return eng_main.grade_once(
            lambda: psycopg.connect(engine_db, autocommit=True), f"audit-{n}", classify=correct, heartbeat_sec=0.05
        )

    with ThreadPoolExecutor(2) as pool:
        results = [pool.submit(execute, n) for n in range(2)]
        assert sorted(f.result(timeout=15) for f in results) == [False, True]
    assert state(conn, run_id) == (2, 2, True, 1)


@pytest.mark.parametrize("judge_status", ["ok", "undecidable"])
def test_undecided_success_policy_observation(experiment, judge_status):
    conn, _, run_id = prepare(experiment, info("ok"))
    pipeline.grade(conn, run_id, classify=lambda *_: Verdict("correct", judge_status=judge_status))
    assert (
        conn.execute("SELECT success,judge_status FROM sa_trial_grades WHERE grading_run_id=%s", (run_id,)).fetchall()
        == [(True, judge_status)] * 2
    )
    assert state(conn, run_id) == (0, 2, True, 1)


def test_out_of_scope_success_observation(experiment):
    conn, data, run_id = prepare(experiment)
    rewrite(
        conn,
        "UPDATE sa_experiment_candidates SET template_scope='{" + '"T2":"out_of_scope"' + "}' WHERE experiment_id=%s",
        (data["experiment"],),
    )
    pipeline.grade(conn, run_id, classify=correct)
    assert (
        conn.execute("SELECT success,out_of_scope FROM sa_trial_grades WHERE grading_run_id=%s", (run_id,)).fetchall()
        == [(True, True)] * 2
    )


def test_resume_grading_resets_retry_budget_observation(experiment):
    conn, _, run_id = prepare(experiment)
    job = conn.execute(
        "SELECT job_id FROM sa_jobs WHERE kind='grade' AND payload->>'grading_run_id'=%s", (str(run_id),)
    ).fetchone()[0]
    for _ in range(3):
        conn.execute("UPDATE sa_jobs SET status='failed',attempts=3 WHERE job_id=%s", (job,))
        assert advance.resume_failed_grading(conn, run_id)
        assert conn.execute("SELECT status,attempts FROM sa_jobs WHERE job_id=%s", (job,)).fetchone() == ("queued", 0)


def test_resume_does_not_revive_old_lease_token(experiment):
    conn, _, run_id = prepare(experiment)
    isolate_job(conn, run_id)
    old = queue.lease(conn, "same-worker", kinds=("grade",), lease_sec=60)
    run, trials = pipeline._run(conn, run_id)
    item = pipeline._grade_rules(conn, run, trials[0], old)
    conn.execute(
        "UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (old["job_id"],)
    )
    assert queue.reclaim(conn, kinds=("grade",), max_attempts=1) == 1
    assert advance.resume_failed_grading(conn, run_id)
    new = queue.lease(conn, "same-worker", kinds=("grade",), lease_sec=60)
    assert new["job_id"] == old["job_id"]
    with pytest.raises(queue.LeaseLost):
        pipeline._save_grade(conn, item, Verdict("correct"), old)
    assert rows(conn, "sa_trial_grades", run_id) == []


@pytest.mark.parametrize("phase", ["rules", "grade"])
def test_expiry_during_transaction_does_not_commit_results(experiment, monkeypatch, phase):
    conn, _, run_id = prepare(experiment)
    isolate_job(conn, run_id)
    job = queue.lease(conn, "expiry-audit", kinds=("grade",), lease_sec=60)
    run, trials = pipeline._run(conn, run_id)
    item = pipeline._grade_rules(conn, run, trials[0], job) if phase == "grade" else None
    before = state(conn, run_id)
    original = pipeline.check_conditions if phase == "rules" else pipeline.trial_metrics

    def expire(*a, **kw):
        result = original(*a, **kw)
        conn.execute(
            "UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job["job_id"],)
        )
        return result

    monkeypatch.setattr(pipeline, "check_conditions" if phase == "rules" else "trial_metrics", expire)
    with pytest.raises(queue.LeaseLost):
        if phase == "rules":
            pipeline._grade_rules(conn, run, trials[0], job)
        else:
            pipeline._save_grade(conn, item, Verdict("correct"), job)
    assert state(conn, run_id) == before


def new_run(conn, run_id, *, purpose="regrade", upto=None, pack=None):
    return conn.execute(
        "INSERT INTO sa_grading_runs(experiment_id,pack_version_id,grader_version,purpose,upto_batch_no) SELECT experiment_id,coalesce(%s,pack_version_id),'audit',%s,%s FROM sa_grading_runs WHERE grading_run_id=%s RETURNING grading_run_id",
        (pack, purpose, upto, run_id),
    ).fetchone()[0]


def replacement_pack(conn, run_id, condition, confirmation=None):
    pack = conn.execute(
        "INSERT INTO sa_pack_versions(domain_code,pack_code,version,premises) SELECT p.domain_code,p.pack_code,p.version||'-audit',p.premises FROM sa_pack_versions p JOIN sa_grading_runs g USING(pack_version_id) WHERE g.grading_run_id=%s RETURNING pack_version_id",
        (run_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO sa_data_snapshots(pack_version_id,source_kind,location,design,content_hash,frozen_at) SELECT %s,d.source_kind,d.location,d.design,d.content_hash,d.frozen_at FROM sa_data_snapshots d JOIN sa_grading_runs g USING(pack_version_id) WHERE g.grading_run_id=%s",
        (pack, run_id),
    )
    template = conn.execute(
        "INSERT INTO sa_templates(pack_version_id,code,question_pattern,split,required_capabilities) VALUES (%s,'T2','감사','held','[]') RETURNING template_id",
        (pack,),
    ).fetchone()[0]
    task = conn.execute(
        "INSERT INTO sa_tasks(template_id,code,prompt,seed,confirmation) VALUES (%s,'T2-0','새 팩의 문항',1,%s) RETURNING task_id",
        (template, Jsonb(confirmation) if confirmation else None),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO sa_answer_conditions(task_id,seq,kind,spec) VALUES (%s,1,%s,%s)",
        (task, condition[0], Jsonb(condition[1])),
    )
    conn.execute("UPDATE sa_pack_versions SET status='locked',locked_at=now() WHERE pack_version_id=%s", (pack,))
    return pack


def test_regrade_uses_new_pack_conditions(experiment):
    conn, _, old_run = prepare(experiment, info("ok"), deps=[answer('{"answer":"ok"}') for _ in range(2)])
    pack = replacement_pack(conn, old_run, info("changed"))
    run_id = new_run(conn, old_run, pack=pack)
    observed = []

    def judge(_, item):
        observed.append(item)
        return Verdict("wrong_assertion", "final_answer")

    pipeline.grade(conn, run_id, classify=judge)
    assert all(i.conditions[0].passed is False for i in observed)
    assert state(conn, run_id) == (2, 2, True, 1)
    assert state(conn, old_run) == (0, 0, False, 0)


def test_regrade_confirmation_comes_from_execution_task(experiment):
    conn, data = experiment
    approve = {
        "schema_version": 1,
        "responses": [{"capability": "github.issues.write", "target": ["ops-service"], "decision": "approve"}],
    }
    reject = copy.deepcopy(approve)
    reject["responses"][0]["decision"] = "reject"
    rewrite(
        conn,
        "UPDATE sa_tasks SET confirmation=%s WHERE task_id=(SELECT task_id FROM sa_trials WHERE trial_id=%s)",
        (Jsonb(approve), data["trials"][0]),
    )
    args = {"owner": "acme", "repo": "ops-service", "title": "승인 쓰기"}

    def deps():
        return answer(
            "끝",
            ToolCall(
                "c",
                "request_user_confirmation",
                json.dumps({"action": {"tool_name": "create_issue", "arguments": args}}),
            ),
            ToolCall("w", "create_issue", json.dumps(args)),
        )

    condition = ("forbidden", {"schema_version": 1, "call": {"access": "write"}, "unless_user_confirmed": True})
    conn, _, old_run = prepare(experiment, condition, deps=[deps(), deps()])
    pack = replacement_pack(conn, old_run, condition, reject)
    run_id = new_run(conn, old_run, pack=pack)
    pipeline.grade(conn, run_id, classify=correct)
    assert conn.execute(
        "SELECT bool_and(success) FROM sa_trial_grades WHERE grading_run_id=%s", (run_id,)
    ).fetchone() == (True,)


@pytest.mark.parametrize("purpose", ["calibration", "regrade"])
def test_grading_scope_and_purpose(experiment, purpose):
    conn, data = experiment
    rewrite(conn, "UPDATE sa_trials SET batch_no=2 WHERE trial_id=%s", (data["trials"][1],))
    conn, _, initial = prepare(experiment)
    run_id = new_run(conn, initial, purpose=purpose, upto=1)
    pipeline.grade(conn, run_id, classify=correct)
    assert state(conn, run_id) == (1, 1, True, 0 if purpose == "calibration" else 1)
    if purpose == "regrade":
        payload = conn.execute(
            "SELECT payload FROM sa_jobs WHERE kind='analyze' AND payload->>'grading_run_id'=%s", (str(run_id),)
        ).fetchone()[0]
        assert payload["is_interim"] and payload["batch_no"] == 1


def test_env_error_run_two_is_graded_without_old_run(experiment):
    conn, data = experiment
    set_conditions(conn, data["trials"][0], ("forbidden", {"schema_version": 1, "call": {"access": "write"}}))

    def down(*_):
        raise ToolEnvironmentError()

    first = data["trials"][0]
    worker.run_trial(conn, first, deps=dependencies(down))
    second = conn.execute(
        "INSERT INTO sa_trials(experiment_id,experiment_candidate_id,task_id,rep,run_no,batch_no) SELECT experiment_id,experiment_candidate_id,task_id,rep,2,batch_no FROM sa_trials WHERE trial_id=%s RETURNING trial_id",
        (first,),
    ).fetchone()[0]
    worker.run_trial(conn, data["trials"][1], deps=dependencies())
    worker.run_trial(conn, second, deps=dependencies())
    run_id = conn.execute(
        "SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s", (data["experiment"],)
    ).fetchone()[0]
    pipeline.grade(conn, run_id, classify=correct)
    assert {r[0] for r in conn.execute("SELECT trial_id FROM sa_trial_grades WHERE grading_run_id=%s", (run_id,))} == {
        second,
        data["trials"][1],
    }


def test_stopped_experiment_completed_trials_are_graded(experiment):
    conn, data, run_id = prepare(experiment)
    advance.stop_experiment(conn, data["experiment"], "user")
    pipeline.grade(conn, run_id, classify=correct)
    assert state(conn, run_id) == (2, 2, True, 1)


@pytest.mark.parametrize("variant", ["write_scenario", "search", "tool_error", "retry", "unicode_large"])
def test_trace_roundtrip_all_six_conditions(experiment, variant):
    conn, data = experiment
    trial_id = data["trials"][0]
    snap = conn.execute(
        "SELECT config_snapshot FROM sa_experiment_candidates WHERE experiment_candidate_id=(SELECT experiment_candidate_id FROM sa_trials WHERE trial_id=%s)",
        (trial_id,),
    ).fetchone()[0]
    policy = {
        "schema_version": 1,
        "responses": [{"capability": "github.issues.write", "target": ["ops-service"], "decision": "approve"}],
    }
    scenario = {
        "schema_version": 1,
        "writes": [
            {
                "capability": "github.issues.write",
                "target": ["ops-service"],
                "outcomes": [{"status": "unknown", "applied": True, "result": {"number": 2**80}}],
            }
        ],
    }
    rewrite(
        conn,
        "UPDATE sa_tasks SET confirmation=%s,write_scenario=%s WHERE task_id=(SELECT task_id FROM sa_trials WHERE trial_id=%s)",
        (Jsonb(policy), Jsonb(scenario), trial_id),
    )
    calls = []
    if variant == "search":
        snap["tool_search"] = {"method": "bm25", "top_k": 1, "deferred": ["list_issues"]}
        rewrite(
            conn,
            "UPDATE sa_experiment_candidates SET config_snapshot=%s,config_hash=%s WHERE experiment_candidate_id=(SELECT experiment_candidate_id FROM sa_trials WHERE trial_id=%s)",
            (Jsonb(snap), canonical_hash(snap), trial_id),
        )
        calls.append(ToolCall("search", "search_tools", '{"query":"list issues"}'))
    calls.append(ToolCall("read", "list_issues", '{"owner":"acme","repo":"ops-service"}'))
    if variant == "write_scenario":
        args = {"owner": "acme", "repo": "ops-service", "title": "한글 2**80"}
        calls.extend(
            [
                ToolCall(
                    "c",
                    "request_user_confirmation",
                    json.dumps({"action": {"tool_name": "create_issue", "arguments": args}}),
                ),
                ToolCall("w", "create_issue", json.dumps(args)),
                ToolCall("lookup", "get_write_result", '{"write_ref":"w1"}'),
            ]
        )

    def read(*_):
        if variant == "tool_error":
            raise ToolExecutionError("조회 오류 한글")
        return '[{"number":145}]'

    def deps():
        return Dependencies(
            FakeModel(
                [
                    *[Reply(tool_calls=(call,)) for call in calls],
                    Reply(text=json.dumps({"answer": "한글", "n": 2**80}, ensure_ascii=False)),
                ]
            ),
            read,
        )

    if variant == "retry":
        original = worker._save_result
        try:
            worker._save_result = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("저장 직전 중단"))
            with pytest.raises(RuntimeError):
                worker.run_trial(conn, trial_id, deps=deps())
        finally:
            worker._save_result = original
    engine = worker.run_trial(conn, trial_id, deps=deps()).trace
    if variant == "retry":
        rewrite(
            conn,
            "INSERT INTO sa_spans(trial_id,attempt,seq,kind,name,started_at,duration_sec,output,attributes) VALUES (%s,1,1,'llm','old-attempt',now(),0,'지난 시도','{}')",
            (trial_id,),
        )
    with conn.cursor(row_factory=dict_row) as cur:
        trial = cur.execute("SELECT * FROM sa_trials WHERE trial_id=%s", (trial_id,)).fetchone()
    stored = pipeline.load_trace(conn, trial)
    definitions = [
        info("한글"),
        (
            "link",
            {"schema_version": 1, "key": "evidence", "seen": {"result_contains": ["145"]}, "supports": ["answer"]},
        ),
        ("order", {"schema_version": 1, "before": {"tool": "list_issues"}, "after": {"tool": "create_issue"}}),
        ("forbidden", {"schema_version": 1, "call": {"access": "write"}, "unless_user_confirmed": True}),
        ("end_state", {"schema_version": 1, "write_intents": "none"}),
        ("exact_writes", {"schema_version": 1, "writes": []}),
        ("info", {**info(2**80)[1], "key": "n"}),
    ]
    conditions = [
        {"answer_condition_id": n, "seq": n, "kind": kind, "spec": spec}
        for n, (kind, spec) in enumerate(definitions, 1)
    ]
    context = from_snapshot(snap, policy)
    assert pipeline.check_conditions(conditions, engine, context) == pipeline.check_conditions(
        conditions, stored, context
    )
    original_metrics, stored_metrics = pipeline.trial_metrics(engine), pipeline.trial_metrics(stored)
    assert original_metrics.pop("tool_sec_by_tool") == pytest.approx(stored_metrics.pop("tool_sec_by_tool"))
    assert original_metrics == stored_metrics
    assert engine["write_intents"] == stored["write_intents"]
    if variant == "retry":
        assert stored["attempt"] == 2


def test_blind_input_identifier_observation(experiment):
    conn, _, run_id = prepare(experiment)
    run, trials = pipeline._run(conn, run_id)
    item = pipeline._grade_rules(conn, run, trials[0], None)
    assert item.trace["trial_id"] == item.trial_id
    label = conn.execute(
        "SELECT ec.label FROM sa_trials t JOIN sa_experiment_candidates ec USING(experiment_candidate_id) WHERE t.trial_id=%s",
        (item.trace["trial_id"],),
    ).fetchone()[0]
    assert label in {"A", "B"}
    assert not {"label", "candidate_id", "config_snapshot"} & vars(item).keys()


def test_blind_judge_settings_and_trace_are_not_filtered_observation(experiment):
    conn, _, run_id = prepare(experiment)
    rewrite(
        conn,
        "UPDATE sa_grading_runs SET judge_settings=%s WHERE grading_run_id=%s",
        (
            Jsonb(
                {
                    "schema_version": 1,
                    "temperature": 0,
                    "votes": 1,
                    "questions": ["grounded"],
                    "rubric_version": "candidate_A_only",
                }
            ),
            run_id,
        ),
    )
    run, trials = pipeline._run(conn, run_id)
    rewrite(
        conn,
        'UPDATE sa_spans SET attributes=attributes||\'{"candidate_label":"A"}\'::jsonb WHERE trial_id=%s',
        (trials[0],),
    )
    item = pipeline._grade_rules(conn, run, trials[0], None)
    contracts.validate("grading", item.judge_settings, part="judge_settings")
    assert item.judge_settings["rubric_version"] == "candidate_A_only"
    assert item.trace["spans"][0]["attributes"]["candidate_label"] == "A"


def test_reclaim_kinds_isolation(experiment, engine_db):
    conn, data, run_id = prepare(experiment)
    isolate_job(conn, run_id)
    run_job = advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": data["trials"][0]})
    conn.execute(
        "UPDATE sa_jobs SET status='leased',attempts=3,leased_by='dead',lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s OR (kind='grade' AND payload->>'grading_run_id'=%s)",
        (run_job, str(run_id)),
    )
    assert queue.reclaim(conn, kinds=("grade",), max_attempts=3) == 1
    assert conn.execute("SELECT status FROM sa_jobs WHERE job_id=%s", (run_job,)).fetchone() == ("leased",)
    captured = []

    class Cleanup:
        def reclaim_expired(self, jobs, *, conn):
            captured.extend(j["kind"] for j in jobs)

    assert not eng_main.run_once(
        lambda: psycopg.connect(engine_db, autocommit=True), "run-audit", deps=dependencies(), stdio=Cleanup()
    )
    assert captured == ["run_trial"]


def test_run_worker_does_not_reclaim_grade_with_its_own_limit(experiment, engine_db):
    conn, _, run_id = prepare(experiment)
    isolate_job(conn, run_id)
    conn.execute(
        "UPDATE sa_jobs SET status='leased',attempts=1,leased_by='dead',lease_until=clock_timestamp()-interval '1 second' WHERE kind='grade' AND payload->>'grading_run_id'=%s",
        (str(run_id),),
    )
    assert not eng_main.run_once(
        lambda: psycopg.connect(engine_db, autocommit=True), "run-audit", deps=dependencies(), max_attempts=1
    )
    assert conn.execute(
        "SELECT status FROM sa_jobs WHERE kind='grade' AND payload->>'grading_run_id'=%s", (str(run_id),)
    ).fetchone() == ("leased",)


def test_real_pack_gate_inventory():
    pack = json.loads((ROOT / "packs/it_ops/v0.1/pack.json").read_text(encoding="utf-8"))
    nongates = [
        c for task in pack["tasks"] for c in task["conditions"] if not checks.condition_gate(c["kind"], c["spec"])
    ]
    print("현재 팩의 비관문 조건 수:", len(nongates))
    assert nongates == []


@pytest.mark.parametrize(
    "mutation,test_name",
    [
        ("rules", "test_judge_cannot_overturn_rule_failure"),
        ("judge_required", "test_worker_needs_judge_and_leaves_job_queued"),
        ("heartbeat", "test_lost_lease_saves_no_grade"),
    ],
)
def test_existing_tests_detect_memory_mutations(experiment, engine_db, monkeypatch, mutation, test_name):
    import test_eng_pipeline as existing

    original_verdict, original_grade = pipeline.check_verdict, eng_main.grade
    with monkeypatch.context() as patch:
        if mutation == "rules":
            patch.setattr(pipeline, "check_verdict", lambda item, verdict: verdict.result_class == "correct")
        elif mutation == "judge_required":
            patch.setattr(eng_main, "grade_once", lambda *a, **k: False)
        else:

            def no_fence(conn, run_id, **kw):
                kw["job"] = None
                kw["cancelled"] = lambda: False
                return pipeline.grade(conn, run_id, **kw)

            patch.setattr(eng_main, "grade", no_fence)
        fn = getattr(existing, test_name)
        if mutation == "judge_required":
            patch.setattr(existing, "grade_once", eng_main.grade_once)
        with pytest.raises(BaseException) as caught:
            fn(experiment) if mutation == "rules" else fn(experiment, engine_db)
        assert "DID NOT RAISE" in str(caught.value) or isinstance(caught.value, AssertionError), str(caught.value)
    assert pipeline.check_verdict is original_verdict and eng_main.grade is original_grade
