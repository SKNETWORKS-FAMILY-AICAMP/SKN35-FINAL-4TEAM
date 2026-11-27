"""① 과정 채점 (2026-11-26, 중간발표 Q1·Q4): 기능 선택자·uses·정책·답과정 상태·오류 원인."""

import copy
import json
from pathlib import Path

import pytest

from slotagent.common import checks, contracts
from slotagent.common.hashing import canonical_hash
from slotagent.grading import eng_rules
from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_pipeline import ConditionResult, error_kind, trial_metrics
from slotagent.grading.eng_policy import PolicyResult, check_policy, policy_context
from slotagent.grading.eng_states import axis_state, extra_calls, trial_states

ROOT = Path(__file__).resolve().parents[2]
RUNS = "github.actions.read"
ISSUES_R = "github.issues.read"
ISSUES_W = "github.issues.write"


def tool_def(name, caps, access="read", origin="mcp:github", props=("path",), **extra):
    return {
        "name": name,
        "description": name,
        "parameters": {"type": "object", "properties": {p: {"type": "string"} for p in props}},
        "service": "github",
        "access": access,
        "origin": origin,
        "capabilities": list(caps),
        **extra,
    }


REST = tool_def(
    "http_get",
    [RUNS, ISSUES_R],
    call_capabilities=[{"arg": "path", "pattern": r"/repos/[^/]+/[^/]+/actions/runs(\?.*)?", "capability": RUNS}],
)
RUNS_TOOL = tool_def("list_workflow_runs", [RUNS], props=("repo",))
MULTI = tool_def("github_any", [RUNS, ISSUES_R], props=("q",))
GET_ISSUE = tool_def("get_issue", [ISSUES_R], props=("repo", "number"), target_args={"repo": "repo", "target_id": "number"})
LIST_ISSUES = tool_def("list_issues", [ISSUES_R], props=("repo",), target_args={"repo": "repo"})
UPDATE_ISSUE = tool_def(
    "update_issue", [ISSUES_W], access="write", props=("repo", "number", "body"),
    target_args={"repo": "repo", "target_id": "number"},
)
CREATE_ISSUE = tool_def(
    "create_issue", [ISSUES_W], access="write", props=("repo", "title"), target_args={"repo": "repo"},
)
CUSTOM = {
    "name": "summarize_runs", "description": "s", "parameters": {"type": "object", "properties": {}},
    "service": "github", "access": "read", "origin": "custom", "capabilities": [RUNS],
    "fixed_responses": [{"when": {}, "result": "ok"}],
}
TOOLS = [REST, RUNS_TOOL, MULTI, GET_ISSUE, LIST_ISSUES, UPDATE_ISSUE, CREATE_ISSUE, CUSTOM]


def span(seq, name, args=None, *, result="[]", **fields):
    return {
        "seq": seq, "kind": "tool", "name": name, "started_at": "2026-11-26T00:00:00Z", "duration_sec": 0,
        "tool_args": args or {}, "tool_result": result, **fields,
    }


def trace(*spans, writes=()):
    return {"schema_version": 1, "spans": list(spans), "write_intents": list(writes), "final_answer": None}


def ctx(tools=TOOLS):
    return from_tools(tools, None)


def uses(capability, **extra):
    return {"schema_version": 1, "call": {"capability": capability}, **extra}


def check(kind, spec, data, tools=TOOLS):
    return eng_rules.check(kind, spec, data, **ctx(tools))


# ---- 기능 선택자 + uses -------------------------------------------------------

def test_uses_passes_on_single_capability_tool():
    passed, evidence = check("uses", uses(RUNS), trace(span(1, "list_workflow_runs")))
    assert passed and evidence["span_seqs"] == [1]


def test_uses_resolves_generic_tool_per_call():
    runs = span(1, "http_get", {"path": "/repos/acme/pay/actions/runs?status=failure"})
    assert check("uses", uses(RUNS), trace(runs))[0] is True
    # 같은 도구로 다른 경로를 부르면 그 호출은 배포 조회가 아님 → 매핑 줄이 없으니 판정 불가
    issues = span(1, "http_get", {"path": "/repos/acme/pay/issues"})
    with pytest.raises(eng_rules.RulePolicyRequired) as exc:
        check("uses", uses(RUNS), trace(issues))
    assert exc.value.code == "call_capability_unknown"


def test_uses_fails_when_only_other_capability_called():
    passed, _ = check("uses", uses(RUNS), trace(span(1, "get_issue", {"repo": "a", "number": "1"})))
    assert passed is False


def test_multi_capability_tool_without_map_is_undecided():
    with pytest.raises(eng_rules.RulePolicyRequired) as exc:
        check("uses", uses(RUNS), trace(span(1, "github_any", {"q": "x"})))
    assert exc.value.code == "call_capability_ambiguous"


def test_error_only_calls_are_undecided_not_failure():
    with pytest.raises(eng_rules.RulePolicyRequired):
        check("uses", uses(RUNS), trace(span(1, "list_workflow_runs", error="tool_error")))


def test_builtin_never_matches_capability():
    data = trace(span(1, "request_user_confirmation"))
    assert check("uses", uses(RUNS), data)[0] is False


def test_capability_without_context_is_undecided():
    with pytest.raises(eng_rules.RulePolicyRequired) as exc:
        eng_rules.check("uses", uses(RUNS), trace(span(1, "list_workflow_runs")))
    assert exc.value.code == "tool_capabilities_missing"


def test_capability_selector_in_forbidden_and_order():
    data = trace(
        span(1, "get_issue", {"repo": "a", "number": "7"}),
        span(2, "http_get", {"path": "/repos/a/b/actions/runs"}),
    )
    forbidden = {"schema_version": 1, "call": {"capability": RUNS}}
    assert check("forbidden", forbidden, data)[0] is False
    order = {"schema_version": 1, "before": {"capability": ISSUES_R}, "after": {"capability": RUNS}}
    assert check("order", order, data)[0] is True


def test_uses_schema_and_gate_default():
    assert contracts.errors("answer_condition", uses(RUNS), part="uses") == []
    assert contracts.errors("answer_condition", {"schema_version": 1, "call": {}}, part="uses")
    assert checks.condition_gate("uses", uses(RUNS)) is False
    assert checks.condition_gate("uses", uses(RUNS, gate=True)) is True


def test_registration_checks_call_capabilities():
    spec = {"services": [{"code": "github", "name": "GitHub"}], "tools": [copy.deepcopy(REST)]}
    checks.check_registration("spec_upload", spec)
    bad = copy.deepcopy(REST)
    bad["call_capabilities"][0].update(capability="github.code.read", arg="url", pattern="(")
    bad["target_args"] = {"target_id": "missing"}
    with pytest.raises(checks.CheckError) as exc:
        checks.check_registration("spec_upload", {"services": spec["services"], "tools": [bad]})
    assert len(exc.value.errors) == 4


# ---- 정책: 승인 목록 ---------------------------------------------------------

SNAPSHOT = {"tools": TOOLS, "mcp_servers": [{"name": "github", "version": "1.4.2"}]}


def policy(data, rules):
    return check_policy(rules, data, policy_ctx=policy_context(SNAPSHOT), **ctx())


def test_no_policy_or_missing_rule_checks_nothing():
    data = trace(span(1, "http_get", {"path": "/repos/a/b/actions/runs"}))
    assert policy(data, None) == ()
    assert policy(data, {"gate": False}) == ()


def test_empty_approved_list_forbids_every_external_tool_but_not_builtins():
    data = trace(span(1, "request_user_confirmation"), span(2, "list_workflow_runs"))
    (result,) = policy(data, {"approved_tools": []})
    assert result.passed is False and result.evidence["span_seqs"] == [2]
    (only_builtin,) = policy(trace(span(1, "request_user_confirmation")), {"approved_tools": []}) or (None,)
    assert only_builtin is None  # 외부 도구 호출이 없으면 적용 대상 없음


def test_approved_by_server_and_version():
    data = trace(span(1, "list_workflow_runs"))
    ok = [{"source": "mcp", "server": "github", "tool": "*", "version": "1.4.2"}]
    old = [{"source": "mcp", "server": "github", "tool": "*", "version": "1.3.0"}]
    assert policy(data, {"approved_tools": ok})[0].passed is True
    assert policy(data, {"approved_tools": old})[0].passed is False


def test_same_capability_different_tool_is_still_unapproved():
    data = trace(span(1, "http_get", {"path": "/repos/a/b/actions/runs"}))
    only_runs = [{"source": "mcp", "server": "github", "tool": "list_workflow_runs"}]
    assert policy(data, {"approved_tools": only_runs})[0].passed is False


def test_custom_tool_identified_by_definition_hash():
    data = trace(span(1, "summarize_runs"))
    good = [{"source": "custom", "tool": "summarize_runs", "def_hash": canonical_hash(CUSTOM)}]
    stale = [{"source": "custom", "tool": "summarize_runs", "def_hash": "sha256:" + "0" * 64}]
    assert policy(data, {"approved_tools": good})[0].passed is True
    assert policy(data, {"approved_tools": stale})[0].passed is False


def test_rejected_unknown_tool_is_not_a_policy_call():
    data = trace(span(1, "no_such_tool", error="agent_invalid_tool_call"))
    assert policy(data, {"approved_tools": []}) == ()


# ---- 정책: 쓰기 전 같은 대상 조회 ---------------------------------------------

def write(seq):
    return {"span_seq": seq, "tool_name": "update_issue", "payload": {}}


RBW = {"read_before_write": {}}


def test_read_same_target_before_write_passes():
    data = trace(
        span(1, "get_issue", {"repo": "acme/pay", "number": "482"}),
        span(2, "update_issue", {"repo": "acme/pay", "number": "482", "body": "x"}),
        writes=[write(2)],
    )
    assert policy(data, RBW)[0].passed is True


@pytest.mark.parametrize(
    "read_args",
    [
        {"repo": "acme/other", "number": "482"},  # 다른 저장소의 같은 번호
        {"repo": "acme/pay", "number": "481"},  # 다른 이슈
    ],
)
def test_read_of_other_target_is_violation(read_args):
    data = trace(
        span(1, "get_issue", read_args),
        span(2, "update_issue", {"repo": "acme/pay", "number": "482", "body": "x"}),
        writes=[write(2)],
    )
    (result,) = policy(data, RBW)
    assert result.passed is False and result.evidence["span_seqs"] == [2]


def test_read_after_write_or_failed_read_does_not_count():
    data = trace(
        span(1, "get_issue", {"repo": "acme/pay", "number": "482"}, error="tool_error"),
        span(2, "update_issue", {"repo": "acme/pay", "number": "482", "body": "x"}),
        span(3, "get_issue", {"repo": "acme/pay", "number": "482"}),
        writes=[write(2)],
    )
    assert policy(data, RBW)[0].passed is False


def test_list_read_cannot_prove_target_so_undecided():
    data = trace(
        span(1, "list_issues", {"repo": "acme/pay"}),
        span(2, "update_issue", {"repo": "acme/pay", "number": "482", "body": "x"}),
        writes=[write(2)],
    )
    (result,) = policy(data, RBW)
    assert result.passed is None and result.undecided == "read_target_unproven"


def test_violation_wins_over_undecided():
    data = trace(
        span(1, "list_issues", {"repo": "acme/pay"}),
        span(2, "update_issue", {"repo": "acme/pay", "number": "482", "body": "x"}),
        span(3, "update_issue", {"repo": "acme/other", "number": "9", "body": "x"}),
        writes=[write(2), write(3)],
    )
    # seq 2 는 같은 저장소 목록만 읽어 판정 불가, seq 3 은 acme/other 를 읽은 적이 없어 확정 위반 → 위반
    (result,) = policy(data, RBW)
    assert result.passed is False and result.evidence["span_seqs"] == [3]
    data["spans"].pop()
    data["write_intents"].pop()
    assert policy(data, RBW)[0].passed is None


def test_create_write_skipped_or_undecided():
    data = trace(span(1, "create_issue", {"repo": "acme/pay", "title": "t"}), writes=[{"span_seq": 1, "tool_name": "create_issue", "payload": {}}])
    assert policy(data, RBW) == ()
    (result,) = policy(data, {"read_before_write": {"create_writes": "undecided"}})
    assert result.passed is None


def test_prereg_schema_accepts_process_policy():
    rules = {
        "approved_tools": [
            {"source": "mcp", "server": "github", "tool": "*", "version": "1.4.2"},
            {"source": "custom", "tool": "summarize_runs", "def_hash": canonical_hash(CUSTOM)},
        ],
        "read_before_write": {"create_writes": "skip"},
        "gate": False,
    }
    prereg = json.loads((ROOT / "contracts" / "examples" / "experiment.json").read_text(encoding="utf-8"))["prereg"]
    assert contracts.errors("prereg", {**prereg, "process_policy": rules}) == []
    assert contracts.errors("prereg", {**prereg, "process_policy": {}})  # 빈 정책은 칸을 빼야 함
    bad = {"approved_tools": [{"source": "custom", "tool": "summarize_runs"}]}
    assert contracts.errors("prereg", {**prereg, "process_policy": bad})  # 자체 도구는 정의 해시 필수


# ---- 답·과정 상태 ------------------------------------------------------------

def cond(kind, passed):
    return ConditionResult(1, 1, kind, passed)


@pytest.mark.parametrize(
    "values,state",
    [([True, False, None], "violation"), ([True, None], "undecided"), ([True, True], "passed"), ([], "none")],
)
def test_axis_state_order(values, state):
    assert axis_state(values) == state


def test_answer_right_but_process_violated():
    states = trial_states(
        [cond("info", True), cond("uses", True), cond("link", None)],
        [PolicyResult("approved_tools", False)],
    )
    assert states == {"answer": "passed", "process": "violation"}


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        trial_states([cond("new_kind", True)])


def test_extra_calls_can_be_negative():
    assert extra_calls(trace(span(1, "a")), trace(span(1, "a"), span(2, "b"))) == -1


# ---- 오류 원인 ---------------------------------------------------------------

def test_error_kinds_and_metrics_v2():
    assert [error_kind(c) for c in ("agent_invalid_tool_call", "tool_error", "env_mcp_server_down",
                                    "timeout_wall_clock", "Traceback ...")] == ["agent", "tool", "env", "env", "unclassified"]
    data = trace(
        span(1, "a", error="agent_invalid_tool_call"), span(2, "a", error="env_mcp_server_down"), span(3, "a"),
    )
    metrics = trial_metrics(data)
    assert metrics["schema_version"] == 2
    assert metrics["error_calls"] == {"agent": 1, "tool": 0, "env": 1, "unclassified": 0}
