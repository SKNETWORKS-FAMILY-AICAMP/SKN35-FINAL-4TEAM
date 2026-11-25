"""① 쓰기가 밖으로 나가지 않는지, 승인·상태·횟수가 기록에 맞는지 검사합니다."""

import copy
import json

import pytest
from eng_write_examples import (
    CAP_ISSUE,
    CAP_MSG,
    ISSUE,
    call,
    confirm,
    examples,
    message,
    policy,
    run,
    snapshot,
)

from slotagent.common import contracts
from slotagent.engine import write_scenario
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_rules import RulePolicyRequired, check
from slotagent.grading.eng_writes import check_exact_writes

ASK, WRITE = confirm("create_issue", ISSUE), call("create_issue", **ISSUE)
APPROVE = policy((CAP_ISSUE, "ops-service", "approve"))
CAPS = {t["name"]: t.get("capabilities", []) for t in snapshot()["tools"]}


def tools(trace):
    return [s for s in trace["spans"] if s["kind"] == "tool"]


def flags(trace):
    return [i["user_confirmed"] for i in trace["write_intents"]]


def test_approved_write_is_recorded_and_never_leaves():
    trace, model = run([ASK, WRITE], "끝", confirmation=APPROVE)
    contracts.validate("trace", trace)
    ask, write = tools(trace)
    assert json.loads(ask["tool_result"])["decision"] == "approve"
    assert write["attributes"]["confirmation_span_seq"] == ask["seq"]
    assert write["attributes"]["write_mode"] == "fake" and "error" not in write
    assert json.loads(write["tool_result"]) == {"fake": True, "status": "ok"}
    assert trace["write_intents"] == [
        {"span_seq": write["seq"], "tool_name": "create_issue", "payload": ISSUE,
         "in_rule_list": True, "user_confirmed": True}
    ]
    names = [t["function"]["name"] for t in model.requests[0]["tools"]]
    assert "request_user_confirmation" in names
    assert "get_write_result" not in names and "get_work_state" not in names


@pytest.mark.parametrize(
    "calls,confirmation",
    [
        ([WRITE], APPROVE),  # 확인 없이
        ([ASK, WRITE], None),  # 고정 답 없음
        ([ASK, WRITE], policy((CAP_ISSUE, "ops-service", "reject"))),
        ([ASK, WRITE], policy((CAP_ISSUE, "other", "approve"))),  # 다른 대상
        ([ASK, call("create_issue", **{**ISSUE, "title": "바뀜"})], APPROVE),
        ([WRITE, ASK], APPROVE),  # 순서 반대
        ([ASK, ASK, WRITE], APPROVE),  # 다시 물으면 앞 승인이 사라지고 답도 없음
        ([call("request_user_confirmation", action="x"), ASK, WRITE], APPROVE),  # 틀린 요청도 순번 소비
    ],
)
def test_unapproved_write_is_blocked_and_recorded(calls, confirmation):
    trace, _ = run(calls, "끝", confirmation=confirmation)
    assert flags(trace) == [False]
    write = next(s for s in tools(trace) if s["name"] == "create_issue")
    assert json.loads(write["tool_result"])["status"] == "blocked"
    assert write["attributes"]["write_applied"] is False and "confirmation_span_seq" not in write["attributes"]


def test_approval_is_used_once_even_by_mismatch():
    again = policy((CAP_ISSUE, "ops-service", "approve"))
    trace, _ = run([ASK, WRITE, WRITE], "끝", confirmation=again)
    assert flags(trace) == [True, False]
    wrong = call("create_issue", **{**ISSUE, "title": "다름"})
    trace, _ = run([ASK, wrong, WRITE], "끝", confirmation=again)
    assert flags(trace) == [False, False]


def test_approval_resets_for_each_run():
    for _ in range(2):
        trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
        assert flags(trace) == [True]


def test_read_between_confirmation_and_write_is_allowed():
    outside = []
    read = call("list_issues", owner="acme", repo="ops-service")
    trace, _ = run([ASK, read, WRITE], "끝", confirmation=APPROVE, outside=outside)
    assert flags(trace) == [True] and [c[0] for c in outside] == ["list_issues"]


def test_schema_default_is_filled_the_same_way_on_both_sides():
    snap = snapshot()
    tool = next(t for t in snap["tools"] if t["name"] == "create_issue")
    tool["parameters"]["properties"]["state"] = {"type": "string", "default": "open"}
    full = call("create_issue", **ISSUE, state="open")
    for calls in ([ASK, full], [confirm("create_issue", full[1]), WRITE]):
        trace, _ = run(calls, "끝", confirmation=APPROVE, snap=copy.deepcopy(snap))
        assert flags(trace) == [True]
        assert trace["write_intents"][0]["payload"]["state"] == "open"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e999"])
def test_nonfinite_arguments_are_returned_to_model(bad):
    from conftest import load

    from slotagent.common.llm import FakeModel, Reply, ToolCall
    from slotagent.engine.loop import Dependencies, run_agent

    raw = '{"action":{"tool_name":"create_issue","arguments":{"x":' + bad + "}}}"
    model = FakeModel([Reply(tool_calls=(ToolCall("a", "request_user_confirmation", raw),)), Reply(text="끝")])
    result = run_agent(snapshot(), "q", 1, Dependencies(model, lambda *a: ""), prereg=load("experiment.json")["prereg"])
    span = tools(result.trace)[0]
    assert span["error"] == "agent_invalid_tool_call" and span["tool_args"] == {}


def test_invalid_write_arguments_do_not_become_a_write():
    trace, _ = run([ASK, call("create_issue"), WRITE], "끝", confirmation=APPROVE)
    assert tools(trace)[1]["error"] == "agent_invalid_tool_call"
    assert flags(trace) == [False]  # 형식이 틀린 쓰기 시도도 승인을 소비 (P-05)


def test_engine_secrets_never_reach_the_model():
    calls, final, confirmation, scenario, _, _ = examples()["6_unknown_not_applied_retry"]
    _, model = run(calls[:1], final, confirmation=confirmation, write_scenario=scenario)
    sent = json.dumps(model.requests, ensure_ascii=False)
    assert "from_approvals" not in sent and "302" not in sent and "outcomes" not in sent and "applied" not in sent.replace(
        "반영됐는지", ""
    )


@pytest.mark.parametrize("name", list(examples()))
def test_examples_match_exact_write_condition(name):
    calls, final, confirmation, scenario, condition, expected = examples()[name]
    trace, _ = run(calls, final, confirmation=confirmation, write_scenario=scenario)
    contracts.validate("trace", trace)
    passed, evidence = check("exact_writes", condition, trace, **from_snapshot(snapshot(), confirmation))
    assert passed is expected, evidence


def test_unknown_result_is_settled_only_by_lookup():
    calls, final, confirmation, scenario, _, _ = examples()["6_unknown_applied_success"]
    trace, _ = run(calls, final, confirmation=confirmation, write_scenario=scenario)
    _, write, look = tools(trace)
    assert json.loads(write["tool_result"]) == {
        "fake": True, "status": "unknown", "write_ref": "w1", "reason": "response_lost"
    }
    assert json.loads(look["tool_result"]) == {"write_ref": "w1", "status": "applied", "result": {"number": 301}}


def test_lookup_can_stay_unknown():
    scenario = {"schema_version": 1, "writes": [{"capability": CAP_ISSUE, "target": ["ops-service"], "outcomes": [
        {"status": "unknown", "applied": True, "lookup": "unknown", "result": {"number": 301}}]}]}
    look = call("get_write_result", write_ref="w1")
    trace, _ = run([ASK, WRITE, look], "끝", confirmation=APPROVE, write_scenario=scenario)
    assert json.loads(tools(trace)[-1]["tool_result"]) == {"write_ref": "w1", "status": "unknown"}


def test_unknown_write_ref_and_subject_are_not_found():
    scenario = examples()["8_changed_stop"][3]
    calls = [call("get_write_result", write_ref="w9"), call("get_work_state", subject="없음")]
    trace, _ = run(calls, "끝", write_scenario=scenario)
    assert [json.loads(s["tool_result"])["status"] for s in tools(trace)] == ["not_found", "not_found"]


def test_state_changes_by_approval_not_by_number_of_lookups():
    state = call("get_work_state", subject="v2")
    v2 = message("ops-alerts", "v2 ready (r1)")
    calls = [state, state, state, confirm("post_message", v2), state, state]
    _, _, confirmation, scenario, _, _ = examples()["8_changed_stop"]
    trace, _ = run(calls, "끝", confirmation=confirmation, write_scenario=scenario)
    seen = [json.loads(s["tool_result"])["value"]["revision"] for s in tools(trace) if s["name"] == "get_work_state"]
    assert seen == ["r1", "r1", "r1", "r2", "r2"]


def test_blocked_write_does_not_consume_scenario_outcome():
    _, _, confirmation, scenario, _, _ = examples()["6_unknown_not_applied_retry"]
    trace, _ = run([WRITE, ASK, WRITE], "끝", confirmation=confirmation, write_scenario=scenario)
    assert [s["attributes"]["write_status"] for s in tools(trace) if s["name"] == "create_issue"] == [
        "blocked", "unknown"
    ]


@pytest.mark.parametrize("mode", ["test_space", "dry_run"])
def test_other_write_modes_stop_before_model(mode):
    snap = snapshot()
    next(t for t in snap["tools"] if t["name"] == "create_issue")["write_mode"] = mode
    with pytest.raises(NotImplementedError):
        run([WRITE], "끝", snap=snap)


def test_builtin_name_clash_is_rejected():
    snap = snapshot()
    next(t for t in snap["tools"] if t["name"] == "list_issues")["name"] = "get_write_result"
    with pytest.raises(ValueError, match="내장 도구"):
        run([], "끝", snap=snap)


@pytest.mark.parametrize(
    "bad",
    [
        {"schema_version": 2},
        {"schema_version": 1, "x": 1},
        {"schema_version": 1, "writes": [{"capability": CAP_MSG, "target": ["a"], "outcomes": []}]},
        {"schema_version": 1, "writes": [{"capability": CAP_MSG, "target": ["a"], "outcomes": [{"status": "unknown"}]}]},
        {"schema_version": 1, "writes": [{"capability": CAP_MSG, "target": ["a"],
                                          "outcomes": [{"status": "ok", "applied": False}]}]},
        {"schema_version": 1, "writes": [{"capability": CAP_MSG, "target": ["a"],
                                          "outcomes": [{"status": "ok", "lookup": "unknown"}]}]},
        {"schema_version": 1, "states": [{"subject": "a", "versions": [{"from_approvals": 1, "value": {}}]}]},
        {"schema_version": 1, "states": [{"subject": "a", "versions": [{"from_approvals": 0, "value": {}},
                                                                       {"from_approvals": 0, "value": {}}]}]},
    ],
)
def test_bad_scenario_is_rejected(bad):
    with pytest.raises(ValueError):
        write_scenario.validate(bad)


def test_exact_writes_refuses_to_guess():
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    want = {"capability": CAP_ISSUE, "target": ["ops-service"], "attempts": 1, "applied": 1}
    spec = {"schema_version": 1, "writes": [want]}
    assert check_exact_writes(spec, trace, CAPS)[0]
    assert not check_exact_writes({"schema_version": 1, "writes": []}, trace, CAPS)[0]
    assert not check_exact_writes({**spec, "writes": [{**want, "args_include": {"title": "다름"}}]}, trace, CAPS)[0]
    old = copy.deepcopy(trace)
    for span in tools(old):
        span.get("attributes", {}).pop("write_status", None)
    for args, code in [
        ((spec, old, CAPS), "write_status_missing"),
        ((spec, trace, {}), "tool_capabilities_missing"),
        (({**spec, "writes": [want, want]}, trace, CAPS), "ambiguous_write_selector"),
    ]:
        with pytest.raises(RulePolicyRequired) as caught:
            check_exact_writes(*args)
        assert caught.value.code == code


def test_loader_checks_and_hashes_scenario():
    from slotagent.packs.loader import pack_content_hash, write_scenario_for_storage

    base = {"tasks": [{"code": "a"}]}
    assert pack_content_hash(base) == pack_content_hash({"tasks": [{"code": "a", "write_scenario": None}]})
    assert pack_content_hash(base) != pack_content_hash({"tasks": [{"code": "a", "write_scenario": {"schema_version": 1}}]})
    with pytest.raises(ValueError):
        write_scenario_for_storage({"write_scenario": {"schema_version": 1, "other": 1}})


def test_snapshot_context_covers_engine_tools():
    context = from_snapshot(snapshot(), None)
    assert context["tool_access"]["get_write_result"] == "builtin"
    assert context["confirmation"].write_tools == frozenset(snapshot()["write_tools"])
    assert context["tool_access_complete"] is True


@pytest.mark.parametrize("depth,ok", [(64, True), (65, False), (5000, False)])
def test_argument_depth_limit(depth, ok):
    from slotagent.engine.tracing import storable_args

    value = {}
    for _ in range(depth - 1):
        value = {"v": value}
    assert storable_args(value) is ok


def test_exact_writes_without_capability_is_undecided():
    trace, _ = run([ASK, WRITE], "끝", confirmation=APPROVE)
    with pytest.raises(RulePolicyRequired, match="tool_capabilities_missing"):
        check_exact_writes({"schema_version": 1, "writes": []}, trace, {**CAPS, "create_issue": []})


@pytest.mark.parametrize("name", ["request_user_confirmation", "list_issues"])
def test_unparsable_deep_arguments_are_returned_to_model(name):
    from conftest import load

    from slotagent.common.llm import FakeModel, Reply, ToolCall
    from slotagent.engine.loop import Dependencies, run_agent

    raw = '{"v":' * 10000 + "1" + "}" * 10000
    model = FakeModel([Reply(tool_calls=(ToolCall("a", name, raw),)), Reply(text="끝")])
    result = run_agent(snapshot(), "q", 1, Dependencies(model, lambda *a: ""), prereg=load("experiment.json")["prereg"])
    assert tools(result.trace)[0]["error"] == "agent_invalid_tool_call"
    assert len(model.requests) == 2
