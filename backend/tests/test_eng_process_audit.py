"""① 과정 채점 검증 요청서 16항의 독립 재현. 제품 코드는 수정하지 않습니다."""

import subprocess
import sys
import types
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
from test_eng_pipeline import grades, prepare, set_policy
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import checks, contracts
from slotagent.engine.worker import run_trial
from slotagent.grading import eng_pipeline, eng_rules
from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_pipeline import JudgeNotConnected, Verdict, grade, trial_metrics
from slotagent.grading.eng_policy import PolicyResult, check_policy, policy_context
from slotagent.grading.eng_states import axis_state

ROOT = Path(__file__).resolve().parents[2]
READ = "github.issues.read"
WRITE = "github.issues.write"
OTHER = "github.actions.read"
THIRD = "github.code.read"


def tool(name="read_issue", caps=(READ,), access="read", **extra):
    return {
        "name": name, "description": name, "service": "github", "origin": "mcp:github",
        "access": access, "capabilities": list(caps),
        "parameters": {"type": "object", "properties": {
            key: {"type": "string"} for key in ("repo", "id", "path")
        }},
        **extra,
    }


def span(seq=1, name="read_issue", args=None, **extra):
    return {
        "seq": seq, "kind": "tool", "name": name, "tool_args": args or {},
        "tool_result": "482", "duration_sec": 0, "started_at": "2026-11-26T00:00:00Z", **extra,
    }


def trace(*spans, writes=()):
    return {"schema_version": 1, "spans": list(spans), "write_intents": list(writes), "final_answer": '{"a":"482"}'}


def use(data, tools, cap=READ, **context):
    return eng_rules.check(
        "uses", {"schema_version": 1, "call": {"capability": cap}}, data,
        **(context or from_tools(tools, None)),
    )[0]


def policy(data, tools, config, servers=None):
    snapshot = {"tools": tools, "mcp_servers": servers or []}
    return check_policy(config, data, policy_ctx=policy_context(snapshot), **from_tools(tools, None))


def write(seq=2):
    return {"span_seq": seq, "tool_name": "update_issue", "payload": {"repo": "acme/a", "id": "482"},
            "in_rule_list": True, "user_confirmed": True}


def rw_tools():
    target = {"repo": "repo", "target_id": "id"}
    return [tool(target_args=target), tool("update_issue", (WRITE,), "write", target_args=target)]


@pytest.fixture(scope="module")
def previous_rules():
    """커밋 전 기준 모듈을 메모리에서만 읽어 같은 입력으로 대조합니다."""
    source = subprocess.run(
        ["git", "show", "HEAD:backend/src/slotagent/grading/eng_rules.py"],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout
    module = types.ModuleType("_eng_rules_audit_previous")
    sys.modules[module.__name__] = module
    exec(compile(source, "HEAD:eng_rules.py", "exec"), module.__dict__)
    yield module
    del sys.modules[module.__name__]


def outcome(module, kind, spec, data, context):
    try:
        return module.check(kind, {"schema_version": 1, **spec}, data, **context)
    except module.RulePolicyRequired as exc:
        return "undecided", exc.code


@pytest.mark.parametrize("kind,spec", [
    ("info", {"key": "a", "expected": "482", "match": "exact"}),
    ("link", {"key": "proof", "seen": {"result_contains": ["482"], "tool_access": "read"}, "supports": ["a"]}),
    ("order", {"before": {"tool": "read_issue"}, "after": {"access": "read", "args_include": {"id": "2"}}}),
    ("forbidden", {"call": {"access": "write"}}),
    ("forbidden", {"call": {"tool": "read_issue"}}),
    ("end_state", {"write_intents": "none"}),
    ("end_state", {"write_intents": [{"tool": "update_issue"}]}),
    ("exact_writes", {"writes": []}),
])
@pytest.mark.parametrize("variant", ["normal", "error", "empty", "repeated"])
def test_01_previous_conditions(previous_rules, kind, spec, variant):
    spans = [span(), span(2, "second", {"id": "2"})]
    if variant == "error":
        spans[0]["error"] = "tool_error"
    if variant == "empty":
        spans = []
    if variant == "repeated":
        spans.append(span(3))
    data = trace(*spans)
    ctx = from_tools([tool(), tool("second"), tool("update_issue", (WRITE,), "write")], None)
    assert outcome(eng_rules, kind, spec, data, ctx) == outcome(previous_rules, kind, spec, data, ctx)


def test_02_no_confirmation_is_undecided():
    with pytest.raises(eng_rules.RulePolicyRequired):
        use(trace(span()), [], tool_access={"read_issue": "read"}, tool_access_complete=True)


@pytest.mark.parametrize("mode,cap", [("unmatched", READ), ("ambiguous", READ), ("ambiguous", THIRD)])
def test_03_mapping_unknown_or_ambiguous(mode, cap):
    rules = [{"arg": "path", "pattern": "/issues", "capability": READ}]
    if mode == "ambiguous":
        rules.append({"arg": "path", "pattern": "/issues", "capability": OTHER})
    tools = [tool(caps=(READ, OTHER, THIRD), call_capabilities=rules)]
    data = trace(span(args={"path": "/issues" if mode == "ambiguous" else "/unknown"}))
    with pytest.raises(eng_rules.RulePolicyRequired):
        use(data, tools, cap)


@pytest.mark.parametrize("cap,unknown", [(THIRD, False), (READ, True)])
def test_04_multiple_capabilities_without_mapping(cap, unknown):
    tools = [tool(caps=(READ, OTHER))]
    if unknown:
        with pytest.raises(eng_rules.RulePolicyRequired):
            use(trace(span()), tools, cap)
    else:
        assert use(trace(span()), tools, cap) is False


@pytest.mark.parametrize("name", ["request_user_confirmation", "get_work_state", "get_write_result", "unknown_tool"])
def test_05_builtin_and_rejected_not_counted(name):
    data = trace(span(name=name, error="agent_invalid_tool_call") if name == "unknown_tool" else span(name=name))
    assert use(data, [tool()]) is False
    assert policy(data, [tool()], {"approved_tools": []}) == ()


def test_05_search_builtin_not_counted():
    from slotagent.grading.eng_context import from_snapshot

    ctx = from_snapshot({"tools": [tool()], "tool_search": {"method": "bm25"}}, None)
    data = trace(span(name="search_tools"))
    assert use(data, [], **ctx) is False
    assert check_policy({"approved_tools": []}, data, policy_ctx=policy_context({"tools": [tool()]}), **ctx) == ()


@pytest.mark.parametrize("part", ["capability", "approved_tools"])
def test_05_known_tool_rejected_before_execution_not_counted(part):
    tools = [tool()]
    tools[0]["parameters"]["required"] = ["id"]
    data = trace(span(args={"id": 482}, error="agent_invalid_tool_call"))
    if part == "capability":
        assert use(data, tools) is False
    else:
        assert policy(data, tools, {"approved_tools": []}) == ()


def test_06_error_only_use_is_undecided():
    with pytest.raises(eng_rules.RulePolicyRequired):
        use(trace(span(error="tool_error")), [tool()])


def test_07_approval_absent_empty_missing_version():
    data, tools = trace(span()), [tool()]
    assert policy(data, tools, {"gate": True}) == ()
    assert policy(data, tools, {"approved_tools": []})[0].passed is False
    entries = [{"source": "mcp", "server": "github", "tool": "read_issue", "version": "1.0"}]
    result = policy(data, tools, {"approved_tools": entries})[0]
    assert result.passed is None and result.undecided == "tool_version_missing"


def test_08_same_capability_other_tool_not_approved():
    entries = [{"source": "mcp", "server": "github", "tool": "other_tool"}]
    assert policy(trace(span()), [tool(), tool("other_tool")], {"approved_tools": entries})[0].passed is False


@pytest.mark.parametrize("mode,expected", [("other_repo", False), ("after", False), ("failed", False), ("list", None)])
def test_09_read_before_write(mode, expected):
    tools = rw_tools()
    read = span(args={"repo": "acme/b" if mode == "other_repo" else "acme/a", "id": "482"})
    if mode == "after":
        read["seq"] = 3
    if mode == "failed":
        read["error"] = "tool_error"
    if mode == "list":
        tools[0]["target_args"] = {"repo": "repo"}
        read["tool_args"].pop("id")
    data = trace(read, span(2, "update_issue", {"repo": "acme/a", "id": "482"}), writes=[write()])
    assert policy(data, tools, {"read_before_write": {}})[0].passed is expected


def test_10_violation_dominates_unknown():
    data = trace(span(), span(2, "unreported"))
    result = policy(data, [tool()], {"approved_tools": []})[0]
    assert result.passed is False
    assert axis_state([None, False]) == "violation"


def test_11_unknown_policy_not_persisted(experiment, monkeypatch):
    conn, data, run_id = prepare(experiment)
    set_policy(conn, data, {"approved_tools": []})
    monkeypatch.setattr(eng_pipeline, "check_policy", lambda *a, **kw: (PolicyResult("approved_tools", None),))
    observed = []

    def judge(conn, item):
        observed.append(item.policy[0].passed)
        return Verdict("correct")

    grade(conn, run_id, classify=judge)
    assert observed == [None] * len(data["trials"])
    assert conn.execute("SELECT count(*) FROM sa_policy_results WHERE grading_run_id=%s", (run_id,)).fetchone()[0] == 0
    assert all(row[2] for row in grades(conn, run_id))


@pytest.mark.parametrize("recomputed", [True, None, "absent"])
def test_12_resume_rejects_policy_result_change(experiment, monkeypatch, recomputed):
    conn, data, run_id = prepare(experiment)
    set_policy(conn, data, {"approved_tools": []})
    with pytest.raises(JudgeNotConnected):
        grade(conn, run_id)
    assert conn.execute("SELECT passed FROM sa_policy_results WHERE grading_run_id=%s", (run_id,)).fetchone()[0] is False
    changed = () if recomputed == "absent" else (PolicyResult("approved_tools", recomputed),)
    monkeypatch.setattr(eng_pipeline, "check_policy", lambda *a, **kw: changed)
    with pytest.raises(ValueError, match="정책 결과"):
        grade(conn, run_id, classify=lambda conn, item: Verdict("correct"))


@pytest.mark.parametrize("gate", [True, False])
def test_13_gate_and_correct_verdict(experiment, gate):
    conn, data, run_id = prepare(experiment)
    set_policy(conn, data, {"approved_tools": [], "gate": gate})
    if gate:
        with pytest.raises(ValueError, match="과정 정책"):
            grade(conn, run_id, classify=lambda conn, item: Verdict("correct"))
        assert grades(conn, run_id) == []
    else:
        grade(conn, run_id, classify=lambda conn, item: Verdict("correct"))
        assert all(row[2] for row in grades(conn, run_id))


def test_14_trace_attributes_cannot_replace_snapshot():
    tools = [tool(caps=(OTHER,))]
    data = trace(span(attributes={"access": "builtin", "capability": READ, "capabilities": [READ],
                                 "origin": "builtin", "server": "approved", "version": "1.0"}))
    with pytest.raises(eng_rules.TraceError, match="access"):
        use(data, tools)
    assert policy(data, tools, {"approved_tools": []})[0].passed is False
    data["spans"][0]["attributes"]["access"] = "read"
    assert use(data, tools) is False


def test_15_upgrade_existing_database_and_old_metrics(pg):
    """별도 임시 DB에 0001~0005와 v1 자료를 넣은 뒤 0006을 적용합니다."""
    params = conninfo_to_dict(pg)
    name = "eng_upgrade_" + uuid4().hex
    with psycopg.connect(make_conninfo(**{**params, "dbname": "postgres"}), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(make_conninfo(**{**params, "dbname": name}), autocommit=True) as conn:
                migrations = sorted((ROOT / "backend/db/migrations").glob("*.sql"))
                for path in migrations:
                    if path.name < "0006":
                        conn.execute(path.read_text(encoding="utf-8"))
                old = trial_metrics(trace(span()))
                old["schema_version"] = 1
                old.pop("error_calls")
                fixture = experiment.__wrapped__(make_conninfo(**{**params, "dbname": name}))
                old_conn, data = next(fixture)
                try:
                    for trial in data["trials"]:
                        run_trial(old_conn, trial, deps=dependencies())
                    run_id = old_conn.execute(
                        "SELECT grading_run_id FROM sa_grading_runs WHERE experiment_id=%s", (data["experiment"],)
                    ).fetchone()[0]
                    old_conn.execute(
                        "INSERT INTO sa_trial_grades(grading_run_id,trial_id,success,result_class,metrics) "
                        "VALUES (%s,%s,true,'correct',%s)", (run_id, data["trials"][0], Jsonb(old)),
                    )
                    conn.execute((ROOT / "backend/db/migrations/0006_process_grading.sql").read_text(encoding="utf-8"))
                    stored = conn.execute("SELECT metrics FROM sa_trial_grades").fetchone()[0]
                finally:
                    fixture.close()
                assert stored == old
                contracts.validate("grading", stored, part="trial_metrics")
                assert conn.execute("SELECT to_regclass('sa_policy_results')").fetchone()[0] == "sa_policy_results"
                constraint = conn.execute(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='sa_answer_conditions_kind_check'"
                ).fetchone()[0]
                assert "uses" in constraint
        finally:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.mark.parametrize("pattern", ["(", "a{999999999999999999999999}"])
def test_16_invalid_regex_rejected_at_registration(pattern):
    bad = tool(call_capabilities=[{"arg": "path", "pattern": pattern, "capability": READ}])
    contracts.validate("common", bad, part="tool_def")
    with pytest.raises(checks.CheckError):
        checks.check_registration("spec_upload", {"services": [{"code": "github", "name": "GitHub"}], "tools": [bad]})


def test_16_grading_invalid_regex_does_not_crash():
    bad = tool(call_capabilities=[{"arg": "path", "pattern": "(", "capability": READ}])
    with pytest.raises(eng_rules.RulePolicyRequired):
        use(trace(span(args={"path": "/issues"})), [bad])


def test_extra_missing_update_id_is_not_proven_creation():
    tools = rw_tools()
    data = trace(span(2, "update_issue", {"repo": "acme/a"}), writes=[write()])
    result = policy(data, tools, {"read_before_write": {}})
    assert result and result[0].passed is None


def test_extra_missing_repo_cannot_prove_same_target():
    tools = rw_tools()
    data = trace(span(args={"id": "482"}), span(2, "update_issue", {"id": "482"}), writes=[write()])
    assert policy(data, tools, {"read_before_write": {}})[0].passed is None


def test_extra_valid_approval_not_hidden_by_unknown_version():
    entries = [
        {"source": "mcp", "server": "github", "tool": "read_issue", "version": "1.0"},
        {"source": "mcp", "server": "github", "tool": "read_issue"},
    ]
    result = policy(trace(span()), [tool()], {"approved_tools": entries})[0]
    assert policy(trace(span()), [tool()], {"approved_tools": entries[::-1]})[0].passed is True
    assert result.passed is True
