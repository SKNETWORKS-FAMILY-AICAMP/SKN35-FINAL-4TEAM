"""재시도·페이지 완전성의 데이터·실행·기대 판정을 검증한다."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest
from slotagent.packs.groups import read_group, load_group

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
spec = importlib.util.spec_from_file_location("reliability_eval", PACK / "reference/evaluators/reliability.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def tasks():
    return load_group(PACK, "reliability")["tasks"]


def test_pack_and_sixty_scenarios(tmp_path):
    pack, snapshots, golden = read_group(PACK, "reliability")
    assert len(pack["templates"]) == 3 and len(pack["tasks"]) == 9
    assert len(snapshots) == 1 and len(golden) == 12
    result = module.run(tmp_path)
    assert result["runs"] == 60 and result["all_matched"]
    by_code = {t["code"]: t for t in pack["tasks"]}
    for entry, trace in golden:
        assert module.grade(by_code[entry["task_code"]], trace) == entry["expected"]


def test_independent_fixed_answers_and_empty_middle_page():
    by_code = {t["code"]: t for t in tasks()}
    assert module.oracle(by_code["RETRY_TRANSIENT_READ-001"], module.load_case("transient-1")) == {
        "status": "complete", "items": ["101", "102"], "call_count": 2}
    assert module.oracle(by_code["RETRY_TRANSIENT_READ-003"], module.load_case("transient-3"))["call_count"] == 3
    assert module.oracle(by_code["RETRY_EXHAUSTED_READ-001"], module.load_case("persistent-1")) == {
        "status": "unavailable", "items": [], "call_count": 3}
    assert module.oracle(by_code["PAGINATED_ISSUES_COMPLETE-001"], module.load_case("pages-1")) == {
        "status": "complete", "items": ["101", "102", "103", "104"], "call_count": 3}
    assert module.oracle(by_code["PAGINATED_ISSUES_COMPLETE-002"], module.load_case("pages-2"))["items"] == ["201", "202", "204"]
    empty = by_code["PAGINATED_ISSUES_COMPLETE-003"]
    trace = module.simulate(empty, "success")
    assert json.loads(trace["final_answer"]) == {"status": "complete", "items": [], "call_count": 3}
    assert module.grade(empty, trace)["success"]


def test_per_candidate_attempt_state_isolation():
    case = module.load_case("transient-1")
    first, second = module.ToolEnvironment(case), module.ToolEnvironment(case)
    request = {"repo": case["repo"]}
    assert not first.call(request)["ok"]
    assert first.call(request)["ok"]
    assert not second.call(request)["ok"]
    fresh = module.ToolEnvironment(case)
    assert fresh.calls == 0 and not fresh.call(request)["ok"]


@pytest.mark.parametrize("change", ["reply", "count", "repo", "cursor", "duplicate_seq", "invalid_final"])
def test_forged_or_incomplete_evidence_fails(change):
    task = next(t for t in tasks() if t["code"] == "PAGINATED_ISSUES_COMPLETE-001")
    trace = module.simulate(task, "success")
    if change == "reply":
        reply = json.loads(trace["spans"][0]["tool_result"])
        reply["next_cursor"] = None
        trace["spans"][0]["tool_result"] = json.dumps(reply)
    elif change == "count":
        trace["spans"].pop()
    elif change == "repo":
        trace["spans"][0]["tool_args"]["repo"] = "acme/other"
    elif change == "cursor":
        trace["spans"][1]["tool_args"]["cursor"] = None
    elif change == "duplicate_seq":
        trace["spans"][1]["seq"] = 1
    else:
        trace["final_answer"] = "not JSON"
    assert not module.grade(task, trace)["success"]


def test_wrong_arguments_are_not_valid_exhaustion():
    task = next(t for t in tasks() if t["code"] == "RETRY_EXHAUSTED_READ-001")
    trace = module.simulate(task, "success")
    environment = module.ToolEnvironment(module.load_case("persistent-1"))
    for span in trace["spans"]:
        span["tool_args"]["repo"] = "acme/other"
        span["tool_result"] = json.dumps(environment.call(span["tool_args"]))
    assert not module.grade(task, trace)["success"]


def test_duplicate_page_response_does_not_change_fixture():
    case = module.load_case("pages-1")
    original = copy.deepcopy(case)
    environment = module.ToolEnvironment(case)
    reply = environment.call({"repo": case["repo"], "cursor": None})
    reply["items"].clear()
    assert environment.call({"repo": case["repo"], "cursor": None})["items"]
    assert case == original
