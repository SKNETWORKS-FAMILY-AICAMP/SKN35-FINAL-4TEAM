"""P-05 엔진 전달 계약의 승인 범위·거절·재사용·재시작 검증."""

import copy
import json
from pathlib import Path

import pytest

from slotagent.common import contracts
from slotagent.common.confirmation import approved_write, fixed_response, same_action

ROOT = Path(__file__).resolve().parents[2]


def example():
    return json.loads((ROOT / "contracts/examples/confirmation.json").read_text(encoding="utf-8"))


def test_contract_examples():
    ex = example()
    for key in ("task_confirmation", "reject_confirmation", "read_only_confirmation"):
        contracts.validate("pack", ex[key], part="confirmation")
    contracts.validate("confirmation", ex["request"], part="request")
    contracts.validate("confirmation", ex["response"], part="response")
    contracts.validate("trace", ex["trace"])
    assert approved_write(ex["task_confirmation"], ex["trace"], 2, {"post_message"}, ex["tool_capabilities"])


@pytest.mark.parametrize("change", ["no_confirmation", "rejected", "channel", "text", "extra_arg",
                                    "wrong_tool", "wrong_reference", "forged_boolean", "forged_response",
                                    "error", "wrong_origin", "restart"])
def test_forbidden_writes(change):
    ex = example()
    policy, trace = ex["task_confirmation"], ex["trace"]
    confirmation, write = trace["spans"]
    if change in {"no_confirmation", "forged_boolean", "restart"}:
        trace["spans"] = [write]
        if change == "restart":
            trace["attempt"] = 2
    elif change == "rejected":
        policy["responses"][0]["decision"] = "reject"
        response = json.loads(confirmation["tool_result"])
        response["decision"] = "reject"
        confirmation["tool_result"] = json.dumps(response)
    elif change in {"channel", "text", "extra_arg"}:
        write["tool_args"][change] = "different"
    elif change == "wrong_tool":
        write["name"] = "create_issue"
    elif change == "wrong_reference":
        write["attributes"]["confirmation_span_seq"] = 999
    elif change == "forged_response":
        policy["responses"][0]["decision"] = "reject"
    elif change == "error":
        confirmation["error"] = "confirmation failed"
    elif change == "wrong_origin":
        confirmation["attributes"]["origin"] = "agent"
    assert not approved_write(policy, trace, 2, {"post_message", "create_issue"}, ex["tool_capabilities"])


def test_fixed_response_no_response_mismatch_and_rejection():
    ex = example()
    assert fixed_response(ex["task_confirmation"], ex["request"], 0, ex["tool_capabilities"]) == ex["response"]
    assert fixed_response(ex["reject_confirmation"], ex["request"], 0, ex["tool_capabilities"])["decision"] == "reject"
    assert fixed_response(ex["task_confirmation"], ex["request"], 1, ex["tool_capabilities"])["decision"] == "no_response"
    assert fixed_response(ex["read_only_confirmation"], ex["request"], 0, ex["tool_capabilities"])["decision"] == "no_response"
    ex["request"]["action"]["arguments"]["channel"] = "other"
    assert fixed_response(ex["task_confirmation"], ex["request"], 0, ex["tool_capabilities"])["decision"] == "reject"


def test_exact_action_and_single_use():
    ex = example()
    action = ex["request"]["action"]
    other = {"arguments": dict(reversed(list(action["arguments"].items()))), "tool_name": "post_message"}
    assert same_action(action, other)
    other["arguments"]["text"] += " "
    assert not same_action(action, other)
    trace = ex["trace"]
    repeated = copy.deepcopy(trace["spans"][1])
    repeated["seq"] = 3
    repeated["started_at"] = "2026-11-23T00:00:03Z"
    trace["spans"].append(repeated)
    assert not approved_write(ex["task_confirmation"], trace, 3, {"post_message"}, ex["tool_capabilities"])


def test_new_rejection_invalidates_previous_approval():
    ex = example()
    policy = ex["task_confirmation"]
    policy["responses"].append({"decision": "reject", "capability": "slack.messages.write", "target": ["ops-alerts"]})
    confirmation = copy.deepcopy(ex["trace"]["spans"][0])
    confirmation["seq"] = 2
    confirmation["tool_result"] = json.dumps(fixed_response(policy, ex["request"], 1, ex["tool_capabilities"]))
    ex["trace"]["spans"][1]["seq"] = 3
    ex["trace"]["spans"].insert(1, confirmation)
    assert not approved_write(policy, ex["trace"], 3, {"post_message"}, ex["tool_capabilities"])


def test_missing_required_contract_fields():
    ex = example()
    del ex["task_confirmation"]["responses"][0]["target"]
    assert contracts.errors("pack", ex["task_confirmation"], part="confirmation")


def test_policy_allows_free_text_and_candidate_argument_names():
    ex = example()
    request = {"action": {"tool_name": "slack_send", "arguments": {
        "channel_id": "ops-alerts", "body": "모델이 자유롭게 작성한 배포 요약"}}}
    assert fixed_response(ex["task_confirmation"], request, 0, ex["tool_capabilities"])["decision"] == "approve"
    trace = ex["trace"]
    trace["spans"][0]["tool_args"] = request
    trace["spans"][0]["tool_result"] = json.dumps(fixed_response(
        ex["task_confirmation"], request, 0, ex["tool_capabilities"]))
    trace["spans"][1]["name"] = "slack_send"
    trace["spans"][1]["tool_args"] = copy.deepcopy(request["action"]["arguments"])
    assert approved_write(ex["task_confirmation"], trace, 2, {"slack_send"}, ex["tool_capabilities"])
    trace["spans"][1]["tool_args"]["body"] = "승인 이후 변경"
    assert not approved_write(ex["task_confirmation"], trace, 2, {"slack_send"}, ex["tool_capabilities"])


@pytest.mark.parametrize("tool,args", [
    ("create_issue", {"channel": "ops-alerts"}),
    ("post_message", {"channel": "ops-alerts-other"}),
    ("post_message", {"ops-alerts": "other"}),
    ("unknown", {"channel": "ops-alerts"}),
])
def test_policy_rejects_wrong_capability_substring_or_key(tool, args):
    ex = example()
    request = {"action": {"tool_name": tool, "arguments": args}}
    assert fixed_response(ex["task_confirmation"], request, 0, ex["tool_capabilities"])["decision"] == "reject"


def test_null_nested_targets_and_malformed_consumed_index():
    ex = example()
    request = {"action": {"tool_name": "post_message", "arguments": {"to": ["ops-alerts"]}}}
    assert fixed_response(None, request, 0, ex["tool_capabilities"])["decision"] == "no_response"
    assert fixed_response(ex["task_confirmation"], request, 0, ex["tool_capabilities"])["decision"] == "approve"
    # 잘못된 첫 요청도 엔진이 순번을 소비하고 다음 요청에는 1을 전달한다.
    assert fixed_response(ex["task_confirmation"], request, 1, ex["tool_capabilities"])["decision"] == "no_response"


def test_loader_validation_null_and_policy_hash():
    from slotagent.packs.loader import confirmation_for_storage, pack_content_hash, store_task_confirmation

    ex = example()
    assert confirmation_for_storage({}) is None
    assert confirmation_for_storage({"confirmation": None}) is None
    pack = {"tasks": [{"code": "test"}]}
    assert pack_content_hash(pack) == pack_content_hash({"tasks": [{"code": "test", "confirmation": None}]})
    approved = {"tasks": [{"code": "test", "confirmation": ex["task_confirmation"]}]}
    rejected = {"tasks": [{"code": "test", "confirmation": ex["reject_confirmation"]}]}
    assert pack_content_hash(approved) != pack_content_hash(rejected)

    class Connection:
        rowcount = 1

        def execute(self, sql, args):
            self.sql, self.args = sql, args
            return self

    conn = Connection()
    store_task_confirmation(conn, 7, {})
    assert conn.args == (None, 7)
    store_task_confirmation(conn, 7, approved["tasks"][0])
    assert conn.args[0].obj == ex["task_confirmation"]
    with pytest.raises(contracts.ContractError):
        store_task_confirmation(conn, 7, {"confirmation": {"invalid": True}})
