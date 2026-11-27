"""① 11/25 쓰기 계약 독립 감사. 제품·기존 테스트를 고치지 않고 실패를 재현합니다."""

import copy
import json
from uuid import uuid4

import psycopg
import pytest
from conftest import ROOT, load
from eng_write_examples import CAP_ISSUE, ISSUE, call, confirm, policy, run, snapshot
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
from test_eng_rules_confirmation import audit
from test_eng_rules_confirmation import (
    test_permissions_cover_golden_tools_and_template_capabilities as permissions_audit,
)
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import queue
from slotagent.common.hashing import canonical_hash
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.engine import worker
from slotagent.engine.loop import Dependencies, run_agent
from slotagent.engine.write_proxy import BUILTIN_NAMES
from slotagent.grading.eng_context import from_snapshot, from_tools
from slotagent.grading.eng_rules import RulePolicyRequired, check
from slotagent.packs import loader

ASK, WRITE = confirm("create_issue", ISSUE), call("create_issue", **ISSUE)
APPROVE = policy((CAP_ISSUE, "ops-service", "approve"))
SPEC = {"schema_version": 1, "call": {"access": "write"}, "unless_user_confirmed": True}


def tool_spans(trace, name=None):
    return [s for s in trace["spans"] if s["kind"] == "tool" and (name is None or s["name"] == name)]


def flags(trace):
    return [w["user_confirmed"] for w in trace["write_intents"]]


def execute_raw(name, raw, *, snap=None, confirmation=APPROVE):
    model = FakeModel([Reply(tool_calls=(ToolCall("raw", name, raw),)), Reply(text="끝")])
    result = run_agent(
        snap or snapshot(),
        "검사",
        1,
        Dependencies(model, lambda *a: pytest.fail("쓰기 외부 호출")),
        prereg=load("experiment.json")["prereg"],
        confirmation=confirmation,
    )
    return result.trace, model


@pytest.mark.parametrize("mode", ["fake", "exclude_tasks", "test_space", "dry_run"])
@pytest.mark.parametrize("listed", [True, False])
@pytest.mark.parametrize("approve", [True, False])
def test_audit_no_external_write(mode, listed, approve):
    snap = snapshot()
    next(t for t in snap["tools"] if t["name"] == "create_issue")["write_mode"] = mode
    if not listed:
        snap["write_tools"].remove("create_issue")
    outside = []
    if mode in {"test_space", "dry_run"}:
        with pytest.raises(NotImplementedError):
            run([ASK, WRITE], "끝", snap=snap, outside=outside)
    else:
        trace, _ = run([ASK, WRITE], "끝", snap=snap, outside=outside, confirmation=APPROVE if approve else None)
        assert flags(trace) == [listed and approve]
    assert outside == []


def test_audit_rule_list_alone_intercepts_read_definition():
    snap = snapshot()
    snap["write_tools"].append("list_issues")
    outside = []
    trace, _ = run([call("list_issues", owner="acme", repo="ops-service")], "끝", snap=snap, outside=outside)
    assert outside == [] and flags(trace) == [False]


@pytest.mark.parametrize(
    "calls,answers,expected",
    [
        ([WRITE, ASK, WRITE], ["approve"], [False, True]),
        ([ASK, WRITE, WRITE], ["approve"], [True, False]),
        ([ASK, ASK, WRITE], ["approve", "reject"], [False]),
        ([ASK, call("request_user_confirmation", action={}), WRITE], ["approve"], [False]),
        ([call("request_user_confirmation", action={}), ASK, WRITE], ["reject", "approve"], [True]),
        ([ASK, call("create_issue", **{**ISSUE, "title": "변경"}), WRITE], ["approve"], [False, False]),
        ([ASK, call("create_issue"), WRITE], ["approve"], [False]),
    ],
)
def test_audit_confirmation_sequence(calls, answers, expected):
    trace, _ = run(calls, "끝", confirmation=policy(*[(CAP_ISSUE, "ops-service", d) for d in answers]))
    assert flags(trace) == expected


def test_audit_confirmation_and_write_in_same_reply():
    model = FakeModel(
        [
            Reply(tool_calls=tuple(ToolCall(str(i), n, json.dumps(a)) for i, (n, a) in enumerate([ASK, WRITE, WRITE]))),
            Reply(text="끝"),
        ]
    )
    trace = run_agent(
        snapshot(),
        "검사",
        1,
        Dependencies(model, lambda *a: pytest.fail("외부 호출")),
        prereg=load("experiment.json")["prereg"],
        confirmation=APPROVE,
    ).trace
    assert flags(trace) == [True, False]


@pytest.mark.parametrize("left,right,expected", [(1, 1.0, True), (2**53, 2**53 + 1, False), (10**100, 10**100, True)])
def test_audit_argument_boundaries(left, right, expected):
    snap = snapshot()
    definition = next(t for t in snap["tools"] if t["name"] == "create_issue")
    definition["parameters"]["properties"]["n"] = {"type": "number"}
    a, b = {**ISSUE, "n": left}, {**ISSUE, "n": right}
    trace, _ = run([confirm("create_issue", a), call("create_issue", **b)], "끝", snap=snap, confirmation=APPROVE)
    assert flags(trace) == [expected]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999"])
@pytest.mark.parametrize("name", ["request_user_confirmation", "create_issue"])
def test_audit_nonfinite_feedback(name, bad):
    snap = snapshot()
    next(t for t in snap["tools"] if t["name"] == "create_issue")["parameters"]["properties"]["n"] = {}
    raw = json.dumps(ISSUE)[:-1] + ',"n":' + bad + "}"
    if name == "request_user_confirmation":
        raw = '{"action":{"tool_name":"create_issue","arguments":' + raw + "}}"
    trace, model = execute_raw(name, raw, snap=snap)
    assert tool_spans(trace)[0]["error"] == "agent_invalid_tool_call"
    assert len(model.requests) == 2


@pytest.mark.parametrize(
    "name,raw",
    [
        ("request_user_confirmation", '{"action":"bad","n":NaN}'),
        ("create_issue", '{"n":Infinity}'),
    ],
)
def test_audit_malformed_nonfinite_trace_is_storable(name, raw):
    trace, model = execute_raw(name, raw)
    assert tool_spans(trace)[0]["error"] == "agent_invalid_tool_call"
    assert len(model.requests) == 2
    # 모델 원문은 llm.tool_calls의 문자열에 보존하고, tool_args는 저장 가능한 JSON이어야 합니다.
    json.dumps(trace, allow_nan=False)


def test_audit_deep_confirmation_feedback():
    # 직렬 JSON 원문을 만들어 테스트 생성기의 재귀 제한과 구별합니다.
    nested = '{"v":' * 600 + '"ops-service"' + "}" * 600
    raw = '{"action":{"tool_name":"create_issue","arguments":' + nested + "}}"
    trace, model = execute_raw("request_user_confirmation", raw)
    assert tool_spans(trace)[0]["error"] == "agent_invalid_tool_call"
    assert len(model.requests) == 2


@pytest.mark.parametrize("field", ["state", "nested"])
def test_audit_default_fill(field):
    snap = snapshot()
    definition = next(t for t in snap["tools"] if t["name"] == "create_issue")
    schema = (
        {"type": "string", "default": "open"}
        if field == "state"
        else {
            "type": "object",
            "properties": {"state": {"type": "string", "default": "open"}},
        }
    )
    definition["parameters"]["properties"][field] = schema
    partial = ISSUE if field == "state" else {**ISSUE, "nested": {}}
    full = {**ISSUE, field: "open" if field == "state" else {"state": "open"}}
    trace, _ = run(
        [confirm("create_issue", partial), call("create_issue", **full)], "끝", snap=snap, confirmation=APPROVE
    )
    assert flags(trace) == [True]


@pytest.mark.parametrize("mutation", ["boolean", "response", "seq", "origin", "index", "action"])
def test_audit_forged_confirmation(mutation):
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    ask, write = tool_spans(trace)
    if mutation == "boolean":
        trace, _ = run([WRITE], "끝", confirmation=APPROVE)
        trace["write_intents"][0]["user_confirmed"] = True
    elif mutation == "seq":
        write["attributes"]["confirmation_span_seq"] = write["seq"]
    elif mutation == "origin":
        ask["attributes"]["origin"] = "mcp"
    else:
        response = json.loads(ask["tool_result"])
        if mutation == "response":
            response["decision"] = "reject"
        elif mutation == "index":
            response["response_index"] = 99
        else:
            response["action"]["arguments"]["title"] = "위조"
        ask["tool_result"] = json.dumps(response)
    assert check("forbidden", SPEC, trace, **from_snapshot(snapshot(), APPROVE))[0] is False


def test_audit_trace_order_uses_seq():
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    trace["spans"].reverse()
    assert check("forbidden", SPEC, trace, **from_snapshot(snapshot(), APPROVE))[0] is True


def scenario(*outcomes):
    return {
        "schema_version": 1,
        "writes": [{"capability": CAP_ISSUE, "target": ["ops-service"], "outcomes": list(outcomes)}],
    }


def test_audit_model_visibility():
    private = scenario({"status": "ok", "result": {"secret": "UNSEEN_OUTCOME_539"}})
    private["states"] = [
        {"subject": "private", "versions": [{"from_approvals": 0, "value": {"secret": "UNSEEN_STATE_539"}}]}
    ]
    rules = policy((CAP_ISSUE, "ops-service", "approve"), (CAP_ISSUE, "UNSEEN_POLICY_539", "reject"))
    _, model = run([ASK], "끝", confirmation=rules, write_scenario=private)
    sent = json.dumps(model.requests)
    assert all(secret not in sent for secret in ["UNSEEN_OUTCOME_539", "UNSEEN_STATE_539", "UNSEEN_POLICY_539"])
    assert all(key not in sent for key in ["from_approvals", "outcomes", "responses"])


def test_audit_attempt_isolation():
    private = scenario({"status": "failed"}, {"status": "ok"})
    for _ in range(2):
        trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE, write_scenario=private)
        assert flags(trace) == [True]
        assert tool_spans(trace, "create_issue")[0]["attributes"]["write_ref"] == "w1"
        assert tool_spans(trace, "create_issue")[0]["attributes"]["write_status"] == "failed"
    trace, _ = run([WRITE], "끝", confirmation=APPROVE, write_scenario=private)
    assert flags(trace) == [False]


def test_audit_scenario_boundaries():
    private = scenario({"status": "failed"}, {"status": "ok"})
    rules = policy(*[(CAP_ISSUE, "ops-service", "approve")] * 3)
    trace, _ = run([WRITE, ASK, WRITE, ASK, WRITE, ASK, WRITE], "끝", confirmation=rules, write_scenario=private)
    assert [s["attributes"]["write_status"] for s in tool_spans(trace, "create_issue")] == [
        "blocked",
        "failed",
        "ok",
        "ok",
    ]


def test_audit_scenario_overlap_observation():
    # 중복 우선순위는 미정이므로 순서 의존만 관측하며 올바른 동작으로 인정하지 않습니다.
    a = scenario({"status": "failed"})["writes"][0]
    b = scenario({"status": "ok"})["writes"][0]
    results = []
    for rows in ([a, b], [b, a]):
        trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE, write_scenario={"schema_version": 1, "writes": rows})
        results.append(tool_spans(trace, "create_issue")[0]["attributes"]["write_status"])
    assert results == ["failed", "ok"]


def test_audit_scenario_unmatched_observation():
    private = scenario({"status": "failed"})
    private["writes"][0]["target"] = ["other"]
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE, write_scenario=private)
    assert tool_spans(trace, "create_issue")[0]["attributes"]["write_status"] == "ok"


def test_audit_states_approval_boundaries():
    state = call("get_work_state", subject="x")
    private = {
        "schema_version": 1,
        "states": [{"subject": "x", "versions": [{"from_approvals": n, "value": {"n": n}} for n in [0, 1, 2]]}],
    }
    rules = policy(*[(CAP_ISSUE, "ops-service", d) for d in ["reject", "approve", "approve", "approve"]])
    trace, _ = run(
        [state, ASK, state, ASK, state, ASK, state, ASK, state], "끝", confirmation=rules, write_scenario=private
    )
    assert [json.loads(s["tool_result"])["value"]["n"] for s in tool_spans(trace, "get_work_state")] == [0, 0, 1, 2, 2]


@pytest.mark.parametrize("case", ["extra", "zero", "overlap", "blocked", "old"])
def test_audit_exact_writes(case):
    trace, _ = run([ASK, WRITE] if case != "blocked" else [WRITE], "끝", confirmation=APPROVE)
    want = {"capability": CAP_ISSUE, "target": ["ops-service"], "attempts": 1, "applied": 1}
    spec = {"schema_version": 1, "writes": [want]}
    if case in {"zero", "blocked"}:
        spec["writes"] = []
    elif case == "extra":
        spec["writes"][0]["target"] = ["other"]
    elif case == "overlap":
        spec["writes"].append(copy.deepcopy(want))
    else:
        tool_spans(trace, "create_issue")[0]["attributes"].pop("write_status")
    if case in {"overlap", "old"}:
        with pytest.raises(
            RulePolicyRequired, match="ambiguous_write_selector" if case == "overlap" else "write_status_missing"
        ):
            check("exact_writes", spec, trace, **from_snapshot(snapshot(), APPROVE))
    else:
        assert check("exact_writes", spec, trace, **from_snapshot(snapshot(), APPROVE))[0] is (case == "blocked")


@pytest.mark.parametrize("name", sorted(BUILTIN_NAMES))
def test_audit_context_builtin_clash(name):
    with pytest.raises(ValueError):
        from_tools([{"name": name, "access": "read"}], None)


def test_audit_context_unknown_tool():
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    tools = [t for t in snapshot()["tools"] if t["name"] != "create_issue"]
    with pytest.raises(RulePolicyRequired, match="tool_access_missing"):
        check("forbidden", SPEC, trace, **from_tools(tools, APPROVE))


def test_audit_context_missing_write_capabilities():
    tools = copy.deepcopy(snapshot()["tools"])
    next(t for t in tools if t["name"] == "create_issue").pop("capabilities")
    # P-13: 이름표 누락은 등록 오류/확인 대상이며 후보 실패로 단정하지 않습니다.
    with pytest.raises((ValueError, RulePolicyRequired)):
        context = from_tools(tools, APPROVE)
        trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
        check("forbidden", SPEC, trace, **context)


def test_audit_loader_hash_backwards_compatible():
    pack = load("pack.json")
    old = {**pack, "tasks": [{**t, "confirmation": loader.confirmation_for_storage(t)} for t in pack["tasks"]]}
    assert loader.pack_content_hash(pack) == canonical_hash(old)
    for task in pack["tasks"]:
        task["write_scenario"] = None
    assert loader.pack_content_hash(pack) == canonical_hash(old)


def test_audit_loader_rejects_before_sql(tmp_path):
    pack = load("pack.json")
    pack["tasks"][0]["write_scenario"] = {
        "schema_version": 1,
        "states": [{"subject": "x", "versions": [{"from_approvals": 1, "value": {}}]}],
    }
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")

    class NoSQL:
        def transaction(self):
            pytest.fail("검증 전에 트랜잭션 시작")

    with pytest.raises(ValueError, match="from_approvals"):
        loader.load_pack(NoSQL(), tmp_path)


def test_audit_practice_permissions():
    permissions_audit()


def test_audit_golden_counts():
    counts, differences, undecided = audit()
    assert counts == {"일치": 200}, (counts, differences, undecided)
    assert undecided == []


def setup_task(conn, trial, *, confirmation=APPROVE, private=None):
    # 기존 fixture의 잠긴 팩에서 감사용 입력만 준비합니다. 일회용 DB에서만 호출합니다.
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role=replica")
        conn.execute(
            "UPDATE sa_tasks SET confirmation=%s,write_scenario=%s WHERE task_id=(SELECT task_id FROM sa_trials WHERE trial_id=%s)",
            (
                Jsonb(confirmation) if confirmation is not None else None,
                Jsonb(private) if private is not None else None,
                trial,
            ),
        )


def write_deps(calls=None):
    calls = [ASK, WRITE] if calls is None else calls
    return Dependencies(
        FakeModel(
            [
                *[Reply(tool_calls=(ToolCall(str(i), n, json.dumps(a)),)) for i, (n, a) in enumerate(calls)],
                Reply(text="끝"),
            ]
        ),
        lambda *a: pytest.fail("쓰기 외부 호출"),
    )


def stored_counts(conn, trial):
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table} WHERE trial_id=%s", (trial,)).fetchone()[0]
        for table in ["sa_spans", "sa_write_intents"]
    )


@pytest.mark.parametrize("failure", ["permanent", "retry", "lease"])
def test_audit_storage_atomicity(experiment, monkeypatch, failure):
    conn, ids = experiment
    trial = ids["trials"][0]
    setup_task(conn, trial)
    original, seen = worker.advance.on_trial_finished, []
    if failure == "lease":
        worker.advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": trial})
    job = queue.lease(conn, "write-audit", lease_sec=120) if failure == "lease" else None
    if job is not None:
        assert job["payload"]["trial_id"] == trial
        trial = job["payload"]["trial_id"]
        setup_task(conn, trial)

    def fail_after_intents(connection, trial_id):
        seen.append(stored_counts(connection, trial_id))
        if len(seen) == 1:
            if failure == "permanent":
                raise RuntimeError("감사 중간 실패")
            raise psycopg.errors.LockNotAvailable("감사 저장 재시도")
        return original(connection, trial_id)

    monkeypatch.setattr(worker.advance, "on_trial_finished", fail_after_intents)

    def after_rollback(_):
        assert stored_counts(conn, trial) == (0, 0)
        if failure == "lease":
            conn.execute(
                "UPDATE sa_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (job["job_id"],)
            )

    monkeypatch.setattr(worker.time, "sleep", after_rollback)
    deps = write_deps()
    if failure in {"permanent", "lease"}:
        with pytest.raises(RuntimeError if failure == "permanent" else queue.LeaseLost):
            worker.run_trial(conn, trial, deps=deps, job=job)
        assert stored_counts(conn, trial) == (0, 0)
    else:
        result = worker.run_trial(conn, trial, deps=deps)
        assert seen == [(5, 1), (5, 1)]
        assert stored_counts(conn, trial) == (5, 1)
        assert worker.run_trial(conn, trial, deps=deps) is None
        row = conn.execute(
            "SELECT w.tool_name,w.payload,w.user_confirmed,s.name,s.seq,s.attempt FROM sa_write_intents w JOIN sa_spans s USING(span_id) WHERE w.trial_id=%s",
            (trial,),
        ).fetchone()
        assert row == ("create_issue", ISSUE, True, "create_issue", 4, 1)
        assert result.trace["write_intents"][0]["span_seq"] == row[4]
    assert len(deps.model.requests) == 3


def test_audit_worker_next_attempt_resets(experiment, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    setup_task(conn, trial, private=scenario({"status": "failed"}, {"status": "ok"}))
    original = worker._save_result

    def fail_save(*a, **kw):
        raise RuntimeError("감사 저장 실패")

    monkeypatch.setattr(worker, "_save_result", fail_save)
    with pytest.raises(RuntimeError, match="감사 저장 실패"):
        worker.run_trial(conn, trial, deps=write_deps())
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == ("pending", 2)
    monkeypatch.setattr(worker, "_save_result", original)
    result = worker.run_trial(conn, trial, deps=write_deps([WRITE, ASK, WRITE]))
    assert flags(result.trace) == [False, True]
    writes = tool_spans(result.trace, "create_issue")
    assert [s["attributes"]["write_status"] for s in writes] == ["blocked", "failed"]
    assert writes[-1]["attributes"]["write_ref"] == "w1"
    assert result.trace["attempt"] == 2


def test_audit_malformed_nonfinite_worker_saves_feedback(experiment):
    conn, ids = experiment
    trial = ids["trials"][0]
    deps = Dependencies(
        FakeModel(
            [
                Reply(tool_calls=(ToolCall("bad", "request_user_confirmation", '{"action":"bad","n":NaN}'),)),
                Reply(text="끝"),
            ]
        ),
        lambda *a: pytest.fail("쓰기 외부 호출"),
    )
    result = worker.run_trial(conn, trial, deps=deps)
    assert result.outcome == "completed"
    assert conn.execute("SELECT status,attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (
        "finished",
        1,
    )


def test_audit_worker_different_trials_reset_state(experiment):
    conn, ids = experiment
    private = scenario({"status": "failed"}, {"status": "ok"})
    private["states"] = [
        {
            "subject": "x",
            "versions": [
                {"from_approvals": 0, "value": {"n": 0}},
                {"from_approvals": 1, "value": {"n": 1}},
            ],
        }
    ]
    for trial in ids["trials"]:
        setup_task(conn, trial, private=private)
        result = worker.run_trial(conn, trial, deps=write_deps([call("get_work_state", subject="x"), ASK, WRITE]))
        assert json.loads(tool_spans(result.trace, "get_work_state")[0]["tool_result"])["value"] == {"n": 0}
        write = tool_spans(result.trace, "create_issue")[0]
        assert write["attributes"]["write_status"] == "failed" and write["attributes"]["write_ref"] == "w1"


def test_audit_rollback_during_second_intent(experiment, monkeypatch):
    conn, ids = experiment
    trial = ids["trials"][0]
    setup_task(conn, trial)
    original, seen = worker._save_result, []

    def bad_second_intent(connection, row, trace, outcome, price_id, job):
        broken = copy.deepcopy(trace)
        broken["write_intents"].append({**broken["write_intents"][0], "span_seq": 999})
        seen.append(len(broken["write_intents"]))
        return original(connection, row, broken, outcome, price_id, job)

    monkeypatch.setattr(worker, "_save_result", bad_second_intent)
    with pytest.raises(KeyError, match="999"):
        worker.run_trial(conn, trial, deps=write_deps())
    assert seen == [2]
    assert stored_counts(conn, trial) == (0, 0)


def test_audit_migration_upgrade(pg, tmp_path):
    params = conninfo_to_dict(pg)
    name = "eng_write_upgrade_" + uuid4().hex
    admin_uri = make_conninfo(**{**params, "dbname": "postgres"})
    uri = make_conninfo(**{**params, "dbname": name})
    migrations = sorted((ROOT / "backend/db/migrations").glob("*.sql"))
    with psycopg.connect(admin_uri, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(uri, autocommit=True) as conn:
                for path in migrations[:4]:
                    conn.execute(path.read_text(encoding="utf-8"))
                # 같은 loader로 0004까지 있는 DB에 실제 문항·조건을 먼저 저장합니다.
                pack = load("pack.json")
                pack["data_snapshots"], pack["golden"] = [], []
                (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
                domain = pack["pack_version"]["domain_code"]
                conn.execute("INSERT INTO sa_domains(domain_code,name,status) VALUES (%s,'감사','active')", (domain,))
                pack_id = loader.load_pack(conn, tmp_path)
                first_task = conn.execute("SELECT min(task_id) FROM sa_tasks").fetchone()[0]
                loader.store_task_confirmation(conn, first_task, {"confirmation": APPROVE})
                print("감사 임시 DB:", conn.execute("SHOW server_version").fetchone()[0])
                before = conn.execute("SELECT task_id,prompt,confirmation FROM sa_tasks ORDER BY task_id").fetchall()
                conditions = conn.execute(
                    "SELECT task_id,kind,spec FROM sa_answer_conditions ORDER BY answer_condition_id"
                ).fetchall()
                conn.execute(migrations[4].read_text(encoding="utf-8"))
                assert (
                    conn.execute("SELECT task_id,prompt,confirmation FROM sa_tasks ORDER BY task_id").fetchall()
                    == before
                )
                assert (
                    conn.execute(
                        "SELECT task_id,kind,spec FROM sa_answer_conditions ORDER BY answer_condition_id"
                    ).fetchall()
                    == conditions
                )
                assert conn.execute("SELECT bool_and(write_scenario IS NULL) FROM sa_tasks").fetchone() == (True,)
                task = before[0][0]
                loader.store_task_write_scenario(conn, task, {"write_scenario": scenario({"status": "ok"})})
                conn.execute(
                    "INSERT INTO sa_answer_conditions(task_id,seq,kind,spec) VALUES (%s,99,'exact_writes','{\"schema_version\":1,\"writes\":[]}')",
                    (task,),
                )
                assert pack_id > 0
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
