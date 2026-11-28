"""정보 충돌·근거 부족의 고정 판정과 시간 경계·출처를 검증한다."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from slotagent.packs.groups import load_group, read_group

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
spec = importlib.util.spec_from_file_location("conflict_eval", PACK / "reference/evaluators/conflicts.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def task(code):
    return next(t for t in load_group(PACK, "conflicts")["tasks"] if t["code"] == code)


def test_nine_tasks_sixty_nine_runs_and_goldens(tmp_path):
    pack, snapshots, golden = read_group(PACK, "conflicts")
    assert len(pack["templates"]) == 3 and len(pack["tasks"]) == 9 and len(golden) == 12
    assert len(snapshots) == 1
    result = module.run(tmp_path)
    assert result["runs"] == 69 and result["all_matched"]
    by_code = {t["code"]: t for t in pack["tasks"]}
    for entry, trace in golden:
        assert module.grade(by_code[entry["task_code"]], trace) == entry["expected"]


def test_oracle_independent_expectations():
    selected = task("CONFLICT_EQUAL_AUTHORITY-001")
    case = module.load_case("case-49af03a2")
    assert module.oracle(selected["slot_values"], case["facts"], case["evidence"]) == {
        "status": "conflict", "selected_version": "UNRESOLVED", "known_status": "success",
        "primary_versions": ["v1.1.0", "v1.2.0"], "evidence_ids": ["payment-primary", "payment-replica"],
        "missing_fields": ["version"], "next_action": "reconcile_primary_sources"}
    selected = task("CONFLICT_FRESH_PRIMARY-001")
    case = module.load_case("case-44ec3989")
    assert module.oracle(selected["slot_values"], case["facts"], list(reversed(case["evidence"]))) == {
        "status": "resolved", "selected_version": "v1.3.0", "known_status": "success",
        "primary_versions": ["v1.3.0"], "evidence_ids": ["payment-live"],
        "missing_fields": [], "next_action": "none"}
    selected = task("CONFLICT_INSUFFICIENT_VERSION-001")
    case = module.load_case("case-152e9771")
    answer = module.oracle(selected["slot_values"], case["facts"], case["evidence"])
    assert answer["known_status"] == "success" and answer["status"] == "insufficient"
    assert answer["selected_version"] == "UNRESOLVED" and answer["evidence_ids"] == []


def test_freshness_inclusive_boundaries_and_future_exclusion():
    selected = task("CONFLICT_FRESH_PRIMARY-001")
    case = module.load_case("case-44ec3989")
    evidence = [case["evidence"][0]]
    boundary = copy.deepcopy(evidence[0])
    boundary.update(evidence_id="boundary", value="v0.0.0", observed_at="2026-11-23T12:00:00+09:00")
    assert module.oracle(selected["slot_values"], case["facts"], evidence+[boundary])["status"] == "conflict"
    boundary["observed_at"] = "2026-11-23T11:59:59+09:00"
    assert module.oracle(selected["slot_values"], case["facts"], evidence+[boundary])["status"] == "resolved"
    boundary["observed_at"] = "2026-11-24T12:00:00+09:00"
    assert module.oracle(selected["slot_values"], case["facts"], evidence+[boundary])["status"] == "conflict"
    boundary["observed_at"] = "2026-11-24T12:00:01+09:00"
    assert module.oracle(selected["slot_values"], case["facts"], evidence+[boundary])["status"] == "resolved"


@pytest.mark.parametrize("field,value", [("repo", "acme/other"), ("environment", "staging"), ("run_id", "other")])
def test_other_execution_does_not_resolve_conflict(field, value):
    selected = task("CONFLICT_EQUAL_AUTHORITY-001")
    case = module.load_case("case-49af03a2")
    case["evidence"][1][field] = value
    assert module.oracle(selected["slot_values"], case["facts"], case["evidence"])["selected_version"] == "v1.1.0"


@pytest.mark.parametrize("change", ["source", "timestamp", "remove_facts", "invalid_answer"])
def test_source_or_answer_tampering_fails(change):
    selected = task("CONFLICT_FRESH_PRIMARY-001")
    trace = module.simulate(selected, "success")
    if change in {"source", "timestamp"}:
        span = next(s for s in trace["spans"] if s["name"] == "list_version_evidence")
        rows = json.loads(span["tool_result"])
        rows[1]["source" if change == "source" else "observed_at"] = (
            "deployment_api" if change == "source" else "2026-11-24T11:00:00+09:00")
        span["tool_result"] = json.dumps(rows)
    elif change == "remove_facts":
        trace["spans"] = [s for s in trace["spans"] if s["name"] != "get_run_facts"]
    else:
        trace["final_answer"] = "not JSON"
    assert not module.grade(selected, trace)["success"]
