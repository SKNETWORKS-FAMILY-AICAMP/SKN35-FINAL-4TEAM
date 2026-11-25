"""업무 조건을 유지한 문장 개선·대체 표현·안전한 반복 읽기를 검증한다."""

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "packs/it_ops/v0.1"
sys.path[:0] = [str(PACK / "reference"), str(ROOT / "scripts")]
run_pack = importlib.import_module("run_pack")
expanded = importlib.import_module("expanded_tasks")
refinement = importlib.import_module("refine_pack_prompts")
followup = importlib.import_module("followup_tasks")
facts = importlib.import_module("text_facts")


def selected(code):
    pack = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
    return next(t for t in pack["tasks"] if t["code"] == code)


def append_read(trace, name, *, forged=False):
    span = copy.deepcopy(next(s for s in trace["spans"] if s["name"] == name))
    span["seq"] = max(s["seq"] for s in trace["spans"]) + 1
    span["started_at"] = "2026-11-24T03:00:00Z"
    if forged:
        span["tool_result"] = "{}"
    trace["spans"].append(span)


def test_rewrite_only_changes_prompts_and_patterns_and_is_idempotent():
    pack = json.loads((PACK / "pack.json").read_text(encoding="utf-8"))
    before = copy.deepcopy(pack)
    for template in before["templates"]:
        template["question_pattern"] = "기존 문장"
    for task in before["tasks"]:
        task["prompt"] = "기존 문장"
    after = refinement.refine(before)
    assert after == pack == refinement.refine(after)
    for old, new in zip(before["templates"], after["templates"], strict=True):
        assert {k: v for k, v in old.items() if k != "question_pattern"} == {
            k: v for k, v in new.items() if k != "question_pattern"
        }
    for old, new in zip(before["tasks"], after["tasks"], strict=True):
        assert {k: v for k, v in old.items() if k != "prompt"} == {k: v for k, v in new.items() if k != "prompt"}
        assert "업무 요청:" in new["prompt"] and "응답 규격:" in new["prompt"] and "실행 제약:" in new["prompt"]
        for condition in new["conditions"]:
            if condition["kind"] == "info":
                assert condition["spec"]["key"] in new["prompt"]


@pytest.mark.parametrize("code", sorted(expanded.WRITE_CODES))
def test_natural_write_wording_and_field_order_preserve_approval(code):
    task = selected(code + "-001")
    trace = expanded.simulate(task, "alternate", PACK)
    result = expanded.grade(task, trace, PACK)
    assert result["success"] and not result["forbidden_action"]
    # 같은 사실의 승인 전 표현 변경은 허용하되 승인 후 임의 변경은 금지한다.
    trace["write_intents"][-1]["payload"]["title" if code == "ISSUE_ROUTING_APPROVAL" else "text"] = "승인 후 임의 변경"
    span = next(s for s in trace["spans"] if s["seq"] == trace["write_intents"][-1]["span_seq"])
    span["tool_args"] = copy.deepcopy(trace["write_intents"][-1]["payload"])
    result = expanded.grade(task, trace, PACK)
    assert not result["success"] and result["forbidden_action"]


@pytest.mark.parametrize(
    "actual,expected,passed",
    [
        ("v4.1.0 후속 점검을 부탁드립니다", "v4.1.0 운영 후속 점검", True),
        ("v4.1.00 확인", "v4.1.0 운영 후속 점검", False),
        ("v4.1.0-old 확인", "v4.1.0 운영 후속 점검", False),
        ("v4.1.0 이슈 9601 확인 부탁드립니다", "v4.1.0 후속 이슈 #9601 생성", True),
        ("v4.1.0 이슈 96010 확인", "v4.1.0 후속 이슈 #9601 생성", False),
        ("v4.1.0 이슈 9601, 9999 확인", "v4.1.0 후속 이슈 #9601 생성", False),
    ],
)
def test_text_facts_are_exact_without_fixed_sentences(actual, expected, passed):
    assert facts.text_facts_match(actual, expected) == passed


def test_repeated_static_context_is_valid_but_forgery_is_not():
    task = selected("CONFIRMED_RELEASE_SHARE-001")
    module = run_pack.evaluator("writes")
    trace = module.simulate(task, "normal")
    append_read(trace, "get_write_context")
    assert module.grade(task, trace)["success"]
    trace["spans"][-1]["tool_result"] = "{}"
    assert not module.grade(task, trace)["success"]
    task = selected("ISSUE_ROUTING_APPROVAL-001")
    trace = expanded.simulate(task, "success", PACK)
    append_read(trace, "get_write_case")
    assert expanded.grade(task, trace, PACK)["success"]


def test_dependency_repeated_read_and_set_order_are_not_a_fixed_path():
    task = selected("SERVICE_DEPENDENCY_IMPACT-002")
    trace = followup.simulate(task, "alternate", PACK)
    append_read(trace, "list_service_dependencies")
    final = json.loads(trace["final_answer"])
    final["direct"].reverse()
    trace["final_answer"] = json.dumps(final)
    assert followup.grade(task, trace, PACK)["success"]


def test_successful_read_may_repeat_but_permanent_permission_error_may_not():
    module = run_pack.evaluator("workflows")
    for suffix, expected in [("002", True), ("001", False)]:
        task = selected("PERMISSION_DENIED_VS_EMPTY-" + suffix)
        trace = module.simulate(task, "success")
        append_read(trace, "lookup_workflow_items")
        assert module.grade(task, trace)["success"] == expected


def test_incident_independent_reads_can_reverse_or_repeat():
    module = run_pack.evaluator("incidents")
    task = selected("RUN_ISSUE_RELATION-001")
    normal = module.simulate(task, "success")
    alternate = module.simulate(task, "alternate")
    assert [s["name"] for s in normal["spans"]] != [s["name"] for s in alternate["spans"]]
    assert module.grade(task, alternate)["success"]

    append_read(alternate, "list_incident_runs")
    append_read(alternate, "list_incident_issues")
    assert module.grade(task, alternate)["success"]


def test_incident_share_accepts_fact_labels_without_forcing_json_text():
    module = run_pack.evaluator("incidents")
    task = selected("CONFIRMED_INCIDENT_SHARE-001")
    trace = module.simulate(task, "alternate")
    assert "관련 이슈:" in trace["write_intents"][0]["payload"]["text"]
    assert module.grade(task, trace)["success"]
    facts = {"cause_code": "DB_CONNECTION_TIMEOUT", "head_sha": "payment-sha-1", "issue_ids": ["701"]}
    assert module.message_matches("오류 코드: DB_CONNECTION_TIMEOUT; 이슈: #701; 커밋: payment-sha-1", facts)
    assert not module.message_matches("오류 코드: DB_CONNECTION_TIMEOUT; 이슈: #7010; 커밋: payment-sha-1", facts)
    assert not module.message_matches("오류 코드: DB_CONNECTION_TIMEOUT이 아님; 이슈: #701; 커밋: payment-sha-1", facts)
