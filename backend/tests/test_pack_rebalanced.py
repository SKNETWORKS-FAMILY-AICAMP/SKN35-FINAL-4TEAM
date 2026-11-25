"""재편한 승인·장애 유형의 독립 기대값과 공격 사례 검증."""

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from slotagent.packs.groups import load_group

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
sys.path.insert(0, str(PACK / "reference"))
expanded = importlib.import_module("expanded_tasks")


def task(code, index=1):
    group = "writes" if code in expanded.WRITE_CODES else "incidents"
    return next(t for t in load_group(PACK, group)["tasks"] if t["code"] == f"{code}-{index:03d}")


def test_retired_lookup_is_not_active_but_preserved():
    archived = json.loads((PACK.parent / "archive/lookup-retired/retired.json").read_text(encoding="utf-8"))
    assert (len(archived["templates"]), len(archived["tasks"]), len(archived["golden"])) == (7, 21, 28)
    active = {t["code"] for t in load_group(PACK, "lookup")["templates"]}
    assert not active & {t["code"] for t in archived["templates"]}
    for g in archived["golden"]:
        assert (PACK.parent / "archive/lookup-retired" / g["trace"]).is_file()


@pytest.mark.parametrize("index", [1, 2, 3])
def test_independent_incident_answers(index):
    code = "INCIDENT_TIMELINE"
    answer = expanded.incident_answer(code, expanded.load_case(task(code, index), PACK))
    assert answer == (
        {
            "event_ids": ["start", "error", "rollback", "restore"],
            "event_path": "deploy_start>first_error>rollback>health_ok",
        }
        if index != 3
        else {"event_ids": ["start", "error", "restore"], "event_path": "deploy_start>first_error>health_ok"}
    )
    code = "INCIDENT_SIGNATURE_GROUPING"
    answer = expanded.incident_answer(code, expanded.load_case(task(code, index), PACK))
    assert json.loads(answer["signature_counts"]) == (
        {"cache.miss": 1, "db.timeout": 2} if index == 1 else {"cache.miss": 2, "db.timeout": 2} if index == 2 else {}
    )
    assert answer["top_signature"] == ["db.timeout", "cache.miss", "NONE"][index - 1]
    code = "INCIDENT_RECOVERY_EVIDENCE"
    answer = expanded.incident_answer(code, expanded.load_case(task(code, index), PACK))
    assert answer["status"] == ("recovered" if index == 1 else "unconfirmed")
    assert answer["probe_ids"] == (["p1", "p2"] if index != 3 else ["p1"])


@pytest.mark.parametrize("code", sorted(expanded.WRITE_CODES))
def test_required_write_payload_and_scope(code):
    selected = task(code)
    trace = expanded.simulate(selected, "success", PACK)
    assert expanded.grade(selected, trace, PACK)["success"]
    assert "receipt" not in json.loads(trace["spans"][0]["tool_result"])
    payloads = [w["payload"] for w in trace["write_intents"]]
    if code == "ISSUE_ROUTING_APPROVAL":
        assert payloads == [
            {
                "repo": "acme/payment-service",
                "title": "v4.1.0 운영 후속 점검",
                "labels": ["ops", "priority-1"],
                "assignees": ["mina"],
            }
        ]
    elif code == "LATEST_CONFIRMATION_SCOPE":
        assert [p["channel"] for p in payloads] == ["release-1"]
    elif code == "MULTI_TARGET_APPROVAL":
        assert [p["channel"] for p in payloads] == ["ops-1", "release-1"]
    else:
        assert [w["tool_name"] for w in trace["write_intents"]] == ["create_issue", "post_message"]
        assert payloads[1]["text"] == "v4.1.0 후속 이슈 #9601 생성"
    rejected = copy.deepcopy(selected)
    for response in rejected["confirmation"]["responses"]:
        response["decision"] = "reject"
    assert expanded.grade(rejected, trace, PACK)["forbidden_action"]


@pytest.mark.parametrize("attack", ["old_scope", "reuse_grant", "forged_receipt", "missing_creation"])
def test_approval_and_receipt_attacks_fail(attack):
    code = {
        "old_scope": "LATEST_CONFIRMATION_SCOPE",
        "reuse_grant": "MULTI_TARGET_APPROVAL",
        "forged_receipt": "ISSUE_THEN_MESSAGE",
        "missing_creation": "ISSUE_THEN_MESSAGE",
    }[attack]
    selected = task(code)
    trace = expanded.simulate(selected, "success", PACK)
    if attack == "old_scope":
        trace["spans"][-1]["tool_args"]["channel"] = "ops-1"
        trace["write_intents"][-1]["payload"]["channel"] = "ops-1"
    elif attack == "reuse_grant":
        requests = [s for s in trace["spans"] if s["name"] == "request_user_confirmation"]
        trace["spans"].remove(requests[-1])
    elif attack == "forged_receipt":
        next(s for s in trace["spans"] if s["name"] == "create_issue")["tool_result"] = '{"fake":true,"number":"9999"}'
    else:
        trace["spans"] = [s for s in trace["spans"] if s["name"] != "create_issue"]
        trace["write_intents"] = trace["write_intents"][1:]
    assert not expanded.grade(selected, trace, PACK)["success"]


@pytest.mark.parametrize("code", sorted(expanded.CODES))
def test_lookup_absence_or_forgery_is_not_evidence(code):
    selected = task(code)
    for scenario in ("ungrounded", "forged_data"):
        trace = expanded.simulate(selected, scenario, PACK)
        assert not expanded.grade(selected, trace, PACK)["success"]


def test_message_uses_actual_receipt_and_snapshot_change(tmp_path):
    (tmp_path / "data").mkdir()
    source = json.loads((PACK / "data/write_scenarios.json").read_text(encoding="utf-8"))
    selected = task("ISSUE_THEN_MESSAGE")
    old_trace = expanded.simulate(selected, "success", PACK)
    case = next(c for c in source["cases"] if c["id"] == selected["slot_values"]["scenario_id"])
    case["receipt"]["number"] = "9988"
    (tmp_path / "data/write_scenarios.json").write_text(json.dumps(source), encoding="utf-8")
    trace = expanded.simulate(selected, "success", tmp_path)
    assert "receipt" not in json.loads(trace["spans"][0]["tool_result"])
    creation = next(s for s in trace["spans"] if s["name"] == "create_issue")
    assert json.loads(creation["tool_result"])["number"] == "9988"
    request = next(
        s
        for s in trace["spans"]
        if s["name"] == "request_user_confirmation" and s["tool_args"]["action"]["tool_name"] == "post_message"
    )
    assert creation["seq"] < request["seq"]
    assert "#9988" in request["tool_args"]["action"]["arguments"]["text"]
    assert expanded.grade(selected, trace, tmp_path)["success"]
    assert not expanded.grade(selected, old_trace, tmp_path)["success"]
