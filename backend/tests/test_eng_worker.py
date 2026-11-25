"""① 실제 임시 DB에서 가짜 모델 풀이·원자적 저장·오래된 시도 차단을 확인합니다."""

import copy
import json
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from conftest import ROOT, load
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from slotagent.common import contracts
from slotagent.common.hashing import agent_spec_hash, canonical_hash
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.common.snapshot import build_config_snapshot, trial_seed
from slotagent.engine import advance
from slotagent.engine.loop import Dependencies, RunCancelled
from slotagent.engine.worker import run_trial


@pytest.fixture(scope="module")
def engine_db(pg):
    """기존 통합 검사의 전역 집계와 섞이지 않는 별도 임시 DB를 사용합니다."""
    params = conninfo_to_dict(pg)
    name = "eng_core_" + uuid4().hex
    admin_uri = make_conninfo(**{**params, "dbname": "postgres"})
    uri = make_conninfo(**{**params, "dbname": name})
    with psycopg.connect(admin_uri, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(uri, autocommit=True) as conn:
                for path in sorted((ROOT / "backend" / "db" / "migrations").glob("*.sql")):
                    conn.execute(path.read_text(encoding="utf-8"))
            yield uri
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture
def experiment(engine_db):
    """① 전용 작은 실험을 만들어 다른 역할의 테스트 데이터와 분리합니다."""
    with psycopg.connect(engine_db, autocommit=True) as conn:
        suffix = uuid4().hex[:12]

        def one(query, *values):
            return conn.execute(query, values).fetchone()[0]

        user = one(
            "INSERT INTO sa_users(email,name) VALUES (%s,'엔진 검사') RETURNING user_id", suffix + "@example.test"
        )
        domain = "eng_" + suffix
        conn.execute("INSERT INTO sa_domains(domain_code,name,status) VALUES (%s,'엔진 검사','active')", (domain,))
        av = load("agent_version.json")
        agent = one("INSERT INTO sa_agents(owner_id,name) VALUES (%s,'엔진 검사') RETURNING agent_id", user)
        av_id = one(
            """INSERT INTO sa_agent_versions(agent_id,version_no,connection_type,model_provider,control_level,
                    model,temperature,instructions,spec,spec_hash) VALUES (%s,1,'spec_upload',%s,'C2',%s,%s,%s,%s,%s)
                    RETURNING agent_version_id""",
            agent,
            av["model_provider"],
            av["model"],
            av["temperature"],
            av["instructions"],
            Jsonb(av["spec"]),
            agent_spec_hash(av["model"], av["temperature"], av["instructions"], av["spec"]),
        )
        slot = one(
            """INSERT INTO sa_slots(agent_version_id,name,service,access,comparable)
                      VALUES (%s,'GitHub 조회','github','read',true) RETURNING slot_id""",
            av_id,
        )
        base = load("slot_and_candidates.json")["candidates"][0]["component_spec"]
        candidates = []
        for label in ["A", "B"]:
            candidates.append(
                one(
                    """INSERT INTO sa_candidates(slot_id,label,name,component_kind,component_spec,spec_hash,is_baseline)
                                    VALUES (%s,%s,%s,'tool_bundle',%s,%s,%s) RETURNING candidate_id""",
                    slot,
                    label,
                    label,
                    Jsonb(base),
                    canonical_hash(base),
                    label == "A",
                )
            )
        pack = one(
            """INSERT INTO sa_pack_versions(domain_code,pack_code,version,premises)
                      VALUES (%s,%s,'v1',%s) RETURNING pack_version_id""",
            domain,
            "eng_" + suffix,
            Jsonb(load("pack.json")["pack_version"]["premises"]),
        )
        conn.execute(
            """INSERT INTO sa_data_snapshots(pack_version_id,source_kind,location,content_hash,frozen_at)
                        VALUES (%s,'repo','fake://engine',%s,now())""",
            (pack, canonical_hash({"engine": suffix})),
        )
        template = one(
            """INSERT INTO sa_templates(pack_version_id,code,question_pattern,is_representative,split,required_capabilities)
                         VALUES (%s,'T2','열린 이슈 조회',false,'held','["github.issues.read"]') RETURNING template_id""",
            pack,
        )
        task_data = next(t for t in load("pack.json")["tasks"] if t["code"] == "T2-0")
        task = one(
            """INSERT INTO sa_tasks(template_id,code,prompt,slot_values,seed)
                     VALUES (%s,'T2-0',%s,%s,%s) RETURNING task_id""",
            template,
            task_data["prompt"],
            Jsonb(task_data["slot_values"]),
            task_data["seed"],
        )
        conn.execute("UPDATE sa_pack_versions SET status='locked',locked_at=now() WHERE pack_version_id=%s", (pack,))
        source = load("experiment.json")
        plan = copy.deepcopy(source["plan"])
        plan["tasks"] = [{"task_id": task, "batch_no": 1}]
        exp = one(
            """INSERT INTO sa_experiments(kind,agent_version_id,slot_id,pack_version_id,reps,prereg,plan,budget_krw,created_by)
                    VALUES ('compare',%s,%s,%s,1,%s,%s,100,%s) RETURNING experiment_id""",
            av_id,
            slot,
            pack,
            Jsonb(source["prereg"]),
            Jsonb(plan),
            user,
        )
        for label, candidate in zip(["A", "B"], candidates, strict=True):
            snap, digest = build_config_snapshot(conn, candidate)
            conn.execute(
                """INSERT INTO sa_experiment_candidates(experiment_id,candidate_id,label,role,config_snapshot,config_hash,template_scope)
                            VALUES (%s,%s,%s,%s,%s,%s,'{"T2":"in_scope"}')""",
                (exp, candidate, label, "baseline" if label == "A" else "candidate", Jsonb(snap), digest),
            )
        conn.execute(
            """INSERT INTO sa_settings(scope,scope_ref,key,value) VALUES ('global','',%s,%s)""",
            ("price." + av["model"], Jsonb({"in_per_1k_krw": 1, "out_per_1k_krw": 2})),
        )
        assert one("SELECT lock_experiment(%s)", exp) == 2
        trials = [
            r[0]
            for r in conn.execute("SELECT trial_id FROM sa_trials WHERE experiment_id=%s ORDER BY trial_id", (exp,))
        ]
        yield conn, {"experiment": exp, "trials": trials, "seed": task_data["seed"]}


def dependencies(tool=None):
    model = FakeModel(
        [
            Reply(
                tool_calls=(ToolCall("issues", "list_issues", '{"owner":"acme","repo":"ops-service","state":"open"}'),),
                in_tokens=100,
                out_tokens=10,
            ),
            Reply(text="열린 이슈는 145, 148입니다.", in_tokens=120, out_tokens=12),
        ]
    )
    return Dependencies(model, tool or (lambda *args: '[{"number":145},{"number":148}]'))


def test_trial_read_and_atomic_storage_and_single_grading_handoff(experiment):
    conn, ids = experiment
    for trial in ids["trials"]:
        result = run_trial(conn, trial, deps=dependencies())
        contracts.validate("trace", result.trace)
        assert result.outcome == "completed"
        assert result.trace["trial_id"] == trial
        assert result.trace["attempt"] == 1
        assert result.trace["spans"][0]["attributes"]["model.seed"] == trial_seed(ids["seed"], 0)
        row = conn.execute(
            "SELECT status,in_tokens,out_tokens,cost_krw,tool_desc_tokens FROM sa_trials WHERE trial_id=%s", (trial,)
        ).fetchone()
        assert row == ("finished", 220, 22, Decimal("0.264"), None)
        assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (3,)
        assert conn.execute(
            "SELECT count(*),sum(cost_krw) FROM sa_cost_ledger WHERE source='trial' AND ref_id=%s", (trial,)
        ).fetchone() == (2, Decimal("0.264"))
    assert conn.execute(
        "SELECT count(*) FROM sa_grading_runs WHERE experiment_id=%s", (ids["experiment"],)
    ).fetchone() == (1,)
    assert conn.execute(
        "SELECT count(*) FROM sa_jobs WHERE kind='grade' AND (payload->>'grading_run_id')::bigint IN "
        "(SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s)",
        (ids["experiment"],),
    ).fetchone() == (1,)
    fake = dependencies()
    assert run_trial(conn, ids["trials"][0], deps=fake) is None
    assert not fake.model.requests


def test_budget_exhaustion_does_not_call_model(experiment):
    conn, ids = experiment
    conn.execute(
        """INSERT INTO sa_cost_ledger(source,experiment_id,model,in_tokens,out_tokens,cost_krw)
                    VALUES ('trial',%s,'fake',0,0,100)""",
        (ids["experiment"],),
    )
    deps = dependencies()
    assert run_trial(conn, ids["trials"][0], deps=deps) is None
    assert not deps.model.requests
    assert conn.execute(
        "SELECT status,stop_reason FROM sa_experiments WHERE experiment_id=%s", (ids["experiment"],)
    ).fetchone() == ("stopped", "budget")
    assert conn.execute(
        "SELECT count(*) FROM sa_trials WHERE experiment_id=%s AND status='cancelled'", (ids["experiment"],)
    ).fetchone() == (2,)


def test_failed_handoff_rolls_back_results_and_keeps_received_costs(experiment, monkeypatch):
    conn, ids = experiment

    def fail(*args):
        raise RuntimeError("인계 실패")

    monkeypatch.setattr(advance, "on_trial_finished", fail)
    trial = ids["trials"][0]
    with pytest.raises(RuntimeError, match="인계 실패"):
        run_trial(conn, trial, deps=dependencies())
    assert conn.execute("SELECT status,attempt,started_at FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
        "pending",
        2,
        None,
    )
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)
    assert conn.execute(
        "SELECT count(*),sum(cost_krw) FROM sa_cost_ledger WHERE ref_id=%s AND source='trial'", (trial,)
    ).fetchone() == (2, Decimal("0.264"))
    monkeypatch.undo()
    result = run_trial(conn, trial, deps=dependencies())
    assert result.outcome == "completed"
    assert result.trace["attempt"] == 2
    assert conn.execute(
        "SELECT count(*),sum(cost_krw) FROM sa_cost_ledger WHERE ref_id=%s AND source='trial'", (trial,)
    ).fetchone() == (4, Decimal("0.528"))


def test_old_attempt_cannot_persist_after_reassignment(experiment):
    conn, ids = experiment
    trial = ids["trials"][0]

    def tool(*args):
        conn.execute("UPDATE sa_trials SET attempt=attempt+1 WHERE trial_id=%s", (trial,))
        return "[]"

    with pytest.raises(RunCancelled):
        run_trial(conn, trial, deps=dependencies(tool))
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("running", 2)
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)


def test_no_default_can_accidentally_call_paid_model(experiment):
    conn, ids = experiment
    with pytest.raises(NotImplementedError):
        run_trial(conn, ids["trials"][0])
    assert conn.execute("SELECT status FROM sa_trials WHERE trial_id=%s", (ids["trials"][0],)).fetchone() == (
        "pending",
    )


@pytest.mark.parametrize(
    "failure", [ValueError("인증 오류"), NotImplementedError("미지원 회사"), RuntimeError("응답 부족")]
)
def test_model_exceptions_release_attempt_and_allow_retry(experiment, failure):
    conn, ids = experiment
    deps = dependencies()

    def fail(**kwargs):
        raise failure

    deps.model.chat = fail
    trial = ids["trials"][0]
    with pytest.raises(type(failure)) as caught:
        run_trial(conn, trial, deps=deps)
    assert caught.value is failure
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("pending", 2)
    assert run_trial(conn, trial, deps=dependencies()).outcome == "completed"


@pytest.mark.parametrize("approve", [True, False])
def test_write_is_stored_with_task_confirmation_and_never_executed(experiment, approve):
    conn, ids = experiment
    trial = ids["trials"][0]
    args = {"owner": "acme", "repo": "ops-service", "title": "x"}
    if approve:
        policy = {
            "schema_version": 1,
            "responses": [{"capability": "github.issues.write", "target": ["ops-service"], "decision": "approve"}],
        }
        conn.execute("SET session_replication_role = replica")  # 잠긴 팩의 시험용 정책만 직접 넣음
        conn.execute(
            "UPDATE sa_tasks SET confirmation=%s WHERE task_id=(SELECT task_id FROM sa_trials WHERE trial_id=%s)",
            (Jsonb(policy), trial),
        )
        conn.execute("SET session_replication_role = DEFAULT")
    ask = json.dumps({"action": {"tool_name": "create_issue", "arguments": args}})
    called = []
    deps = Dependencies(
        FakeModel(
            [
                Reply(tool_calls=(ToolCall("c", "request_user_confirmation", ask),)),
                Reply(tool_calls=(ToolCall("w", "create_issue", json.dumps(args)),)),
                Reply(text="끝"),
            ]
        ),
        lambda *a: called.append(a),
    )
    assert run_trial(conn, trial, deps=deps).outcome == "completed"
    assert not called
    assert conn.execute(
        """SELECT w.tool_name,w.payload,w.in_rule_list,w.user_confirmed,s.name,s.attempt
           FROM sa_write_intents w JOIN sa_spans s USING (span_id) WHERE w.trial_id=%s""",
        (trial,),
    ).fetchall() == [("create_issue", args, True, approve, "create_issue", 1)]


def test_tool_error_is_saved_in_error_column(experiment):
    conn, ids = experiment
    deps = Dependencies(
        FakeModel([Reply(tool_calls=(ToolCall("bad", "absent", "{}"),)), Reply(text="끝")]), lambda *a: "[]"
    )
    trial = ids["trials"][0]
    run_trial(conn, trial, deps=deps)
    assert conn.execute("SELECT error FROM sa_spans WHERE trial_id=%s AND kind='tool'", (trial,)).fetchone() == (
        "agent_invalid_tool_call",
    )


def test_cancelled_signal_releases_current_attempt(experiment):
    conn, ids = experiment
    deps = dependencies()
    deps.cancelled = lambda: True
    trial = ids["trials"][0]
    with pytest.raises(RunCancelled):
        run_trial(conn, trial, deps=deps)
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("pending", 2)


def test_stopped_experiment_does_not_leave_released_trial_pending(experiment):
    conn, ids = experiment
    trial = ids["trials"][0]

    def stop_then_fail(*args):
        advance.stop_experiment(conn, ids["experiment"], "user")
        raise RuntimeError("중단 중 도구 실패")

    with pytest.raises(RuntimeError, match="중단 중 도구 실패"):
        run_trial(conn, trial, deps=dependencies(stop_then_fail))
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
        "cancelled",
        2,
    )


def test_recovery_failure_keeps_original_exception(experiment, monkeypatch):
    from slotagent.engine import worker

    conn, ids = experiment
    original = ValueError("원래 모델 오류")
    deps = dependencies()

    def fail_model(**kwargs):
        raise original

    def fail_recovery(*args):
        raise RuntimeError("비공개 DB 오류 원문")

    deps.model.chat = fail_model
    monkeypatch.setattr(worker, "_release_attempt", fail_recovery)
    with pytest.raises(ValueError) as caught:
        run_trial(conn, ids["trials"][0], deps=deps)
    assert caught.value is original
    assert "상태 복구 실패" in original.__notes__[0]
    assert "비공개" not in original.__notes__[0]
