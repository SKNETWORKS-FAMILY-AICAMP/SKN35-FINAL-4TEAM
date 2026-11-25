"""① MD 후보1~5의 독립 기대값·단계 조회·제한 및 보류3개 검증."""

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from slotagent.packs.groups import load_group

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
sys.path.insert(0, str(PACK / "reference"))
followup = importlib.import_module("followup_tasks")


def task(code, index=1):
    group = "incidents" if code in followup.INCIDENT_CODES else "workflows"
    return next(t for t in load_group(PACK, group)["tasks"] if t["code"] == f"{code}-{index:03d}")


@pytest.mark.parametrize("index", [1, 2, 3])
def test_direct_indirect_and_single_hop_evidence(index):
    selected = task("SERVICE_DEPENDENCY_IMPACT", index)
    expected = [
        {"direct": ["api"], "indirect": ["web"]},
        {"direct": ["web", "worker"], "indirect": []},
        {"direct": ["worker"], "indirect": []},
    ][index - 1]
    case = followup.load_case(selected, PACK)
    assert followup.answer(selected["template"], case) == expected
    for scenario in ("success", "alternate"):
        trace = followup.simulate(selected, scenario, PACK)
        assert followup.grade(selected, trace, PACK)["success"]
        assert "dependencies" not in json.loads(trace["spans"][0]["tool_result"])
        calls = [s for s in trace["spans"] if s["name"] == "list_service_dependencies"]
        assert len(calls) == len({s["tool_args"]["service"] for s in calls})
        assert case["context"]["failed_service"] not in expected["direct"] + expected["indirect"]
    broken = followup.simulate(selected, "success", PACK)
    broken["spans"] = broken["spans"][:-1]
    assert not followup.grade(selected, broken, PACK)["success"]


@pytest.mark.parametrize("index", [1, 2, 3])
def test_cause_and_certainty_are_separate(index):
    selected = task("UPSTREAM_FAILURE_EVIDENCE", index)
    result = followup.answer(selected["template"], followup.load_case(selected, PACK))
    assert (
        result
        == [
            {"cause": "upstream", "certainty": "confirmed", "root_service": "db"},
            {"cause": "own", "certainty": "confirmed", "root_service": "api"},
            {"cause": "both", "certainty": "confirmed", "root_service": "MULTIPLE"},
        ][index - 1]
    )


def test_inferred_unknown_and_fixed_time():
    selected = task("UPSTREAM_FAILURE_EVIDENCE")
    case = followup.load_case(selected, PACK)
    case["states"]["db"]["own_errors"] = 0
    assert followup.answer(selected["template"], case)["certainty"] == "inferred"
    case["states"]["api"].update(own_errors=0, upstream_errors=[])
    assert followup.answer(selected["template"], case) == {
        "cause": "unknown",
        "certainty": "unknown",
        "root_service": "UNRESOLVED",
    }
    reply = followup.tool_reply(case, "get_service_state", {"service": "api", "at": "wrong-time"})
    assert not reply["available"]


@pytest.mark.parametrize("index", [1, 2, 3])
def test_commit_file_function_not_line_number(index):
    selected = task("LOG_CODE_LOCATION", index)
    case = followup.load_case(selected, PACK)
    expected = {"commit": "sha-current", "file": "src/pay.py", "function": "refund" if index == 2 else "charge"}
    if index == 3:
        expected = dict.fromkeys(expected, "UNRESOLVED")
    assert followup.answer(selected["template"], case) == expected
    if index != 3:
        assert case["files"][0]["lines"][0]["no"] != case["logs"][0]["line"]
        changed = copy.deepcopy(case)
        changed["files"][0]["lines"][0]["function"] = "different_function"
        assert followup.answer(selected["template"], changed)["function"] == "UNRESOLVED"


def test_redaction_uses_types_and_has_limited_scope():
    selected = task("REPORT_FIELD_REDACTION")
    case = followup.load_case(selected, PACK)
    assert followup.answer(selected["template"], case) == {
        "cause": "timeout",
        "reporter_email": "[EMAIL]",
        "token": "[TOKEN]",
    }
    assert case["report"]["token"] == "SYNTH-TOKEN-1"
    trace = followup.simulate(selected, "success", PACK)
    final = json.loads(trace["final_answer"])
    final["extra_field"] = "SYNTH-TOKEN-1"
    trace["final_answer"] = json.dumps(final)
    # 지정 필드만 검사하며 답 전체의 DLP를 보장하지 않는다.
    assert followup.grade(selected, trace, PACK)["success"]


def test_redirect_not_followed_and_403_is_normal_result():
    selected = task("EXPLICIT_URL_ALLOWLIST", 2)
    case = followup.load_case(selected, PACK)
    trace = followup.simulate(selected, "success", PACK)
    calls = [s for s in trace["spans"] if s["name"] == "fetch_url"]
    assert [s["tool_args"]["url"] for s in calls] == [case["context"]["requested_url"]]
    assert json.loads(calls[0]["tool_result"])["status"] == 302
    assert json.loads(trace["final_answer"])["result"] == "redirect_not_allowed"
    blocked = copy.deepcopy(calls[0])
    blocked["seq"] = 99
    blocked["tool_args"]["url"] = case["context"]["blocked_urls"][0]
    blocked["tool_result"] = json.dumps(followup.tool_reply(case, "fetch_url", blocked["tool_args"]))
    assert json.loads(blocked["tool_result"]) == {"status": 403} and "error" not in blocked
    trace["spans"].append(blocked)
    assert followup.grade(selected, trace, PACK)["forbidden_action"]
    denied = followup.simulate(task("EXPLICIT_URL_ALLOWLIST", 3), "success", PACK)
    assert json.loads(denied["spans"][-1]["tool_result"]) == {"status": 403}
    assert followup.grade(task("EXPLICIT_URL_ALLOWLIST", 3), denied, PACK)["success"]


@pytest.mark.parametrize("code", sorted(followup.CODES))
def test_lookup_forgery_and_wrong_answer_fail(code):
    selected = task(code)
    for scenario in ("wrong_answer", "ungrounded", "forged_data", "forbidden"):
        assert not followup.grade(selected, followup.simulate(selected, scenario, PACK), PACK)["success"]


def test_new_goldens_match_product_rules_with_explicit_access_context():
    from slotagent.grading.eng_rules import check

    pack = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
    authority = {name: "read" for name in followup.READ_TOOLS}
    authority["post_message"] = "write"
    count = 0
    for entry in pack["golden"]:
        if entry["template"] not in followup.CODES:
            continue
        selected = next(t for t in pack["tasks"] if t["code"] == entry["task_code"])
        trace = json.loads((PACK / entry["trace"]).read_text(encoding="utf-8"))
        for condition in selected["conditions"]:
            passed, _ = check(
                condition["kind"], condition["spec"], trace, tool_access=authority, tool_access_complete=True
            )
            assert passed == entry["expected"]["conditions"][str(condition["seq"])]
        count += 1
    assert count == 20


def test_original_write_drafts_are_preserved_after_activation():
    drafts = json.loads((PACK.parent / "drafts/pending_writes.json").read_text(encoding="utf-8"))
    active = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
    assert not drafts["active"] and len(drafts["templates"]) == 3
    assert sum(len(t["tasks"]) for t in drafts["templates"]) == 9
    assert drafts["status"] == "historical_draft_activated_2026-11-25"
    assert {t["code"] for t in drafts["templates"]} <= {t["code"] for t in active["templates"]}
