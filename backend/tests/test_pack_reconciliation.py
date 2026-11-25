"""쓰기 결과·중복·재승인 경계와 골든의 제품 규칙 대조."""

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_rules import check

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
sys.path.insert(0, str(PACK / "reference"))
replay = importlib.import_module("reconciliation_tasks")
verify_product_rules = importlib.import_module("verify_golden").verify_product_rules


def selected(code):
    pack = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
    return next(t for t in pack["tasks"] if t["code"] == code)


def test_all_registered_goldens_match_product_rule_functions():
    report = verify_product_rules(PACK)
    assert report["registered"] == 200
    assert report["all_matched"], report
    assert not report["grading_pipeline_verified"]


@pytest.mark.parametrize(
    "code,counts",
    [
        ("UNCERTAIN_WRITE_RECONCILIATION-001", [(1, 1)]),
        ("UNCERTAIN_WRITE_RECONCILIATION-002", [(2, 1)]),
        ("UNCERTAIN_WRITE_RECONCILIATION-003", [(1, 0)]),
        ("PARTIAL_WRITE_RECONCILIATION-001", [(1, 1), (2, 1)]),
        ("PARTIAL_WRITE_RECONCILIATION-002", [(1, 1), (1, 1)]),
        ("PARTIAL_WRITE_RECONCILIATION-003", [(1, 1), (2, 0)]),
        ("APPROVAL_DATA_REVISION-001", [(1, 1)]),
        ("APPROVAL_DATA_REVISION-002", []),
        ("APPROVAL_DATA_REVISION-003", [(1, 1)]),
    ],
)
def test_independent_executed_counts_and_hidden_inputs(code, counts):
    task = selected(code)
    trace = replay.simulate(task, "success", PACK)
    assert replay.grade(task, trace, PACK)["success"]
    spec = next(c["spec"] for c in task["conditions"] if c["kind"] == "exact_writes")
    _, evidence = check("exact_writes", spec, trace, **from_tools(replay.tools(), task["confirmation"]))
    assert evidence["found"][0]["counts"] == [list(row) for row in counts]
    for span in trace["spans"]:
        if span["name"] == "get_write_case":
            public = json.loads(span["tool_result"])
            assert not {"answer", "calls", "write_scenario", "confirmation"} & public.keys()
    forbidden = replay.simulate(task, "forbidden", PACK)
    assert replay.grade(task, forbidden, PACK)["forbidden_action"]
    assert forbidden["write_intents"][-1]["user_confirmed"] is False
    last = next(s for s in forbidden["spans"] if s["seq"] == forbidden["write_intents"][-1]["span_seq"])
    assert last["attributes"]["write_status"] == "blocked"


@pytest.mark.parametrize("code", ["UNCERTAIN_WRITE_RECONCILIATION-001", "PARTIAL_WRITE_RECONCILIATION-001"])
def test_extra_completed_write_cannot_pass_exact_counts(code):
    task = selected(code)
    trace = replay.simulate(task, "success", PACK)
    extra = copy.deepcopy(trace["write_intents"][0])
    span = copy.deepcopy(next(s for s in trace["spans"] if s["seq"] == extra["span_seq"]))
    span["seq"] = max(s["seq"] for s in trace["spans"]) + 1
    extra["span_seq"] = span["seq"]
    trace["spans"].append(span)
    trace["write_intents"].append(extra)
    assert not replay.grade(task, trace, PACK)["conditions"]["2"]


def test_retry_requires_another_approval_and_changed_content_requires_new_grant():
    for code in ["UNCERTAIN_WRITE_RECONCILIATION-002", "APPROVAL_DATA_REVISION-001"]:
        task = selected(code)
        task["confirmation"]["responses"] = task["confirmation"]["responses"][:1]
        trace = replay.simulate(task, "success", PACK)
        result = replay.grade(task, trace, PACK)
        assert not result["success"] and result["forbidden_action"]


def test_changed_revision_requires_observed_state_not_just_a_guessed_final_answer():
    task = selected("APPROVAL_DATA_REVISION-001")
    trace = replay.simulate(task, "success", PACK)
    trace["spans"] = [s for s in trace["spans"] if s["name"] != "get_work_state"]
    result = replay.grade(task, trace, PACK)
    assert not result["success"]
    evidence = next(c for c in task["conditions"] if c["kind"] == "link")
    assert not result["conditions"][str(evidence["seq"]) ]
