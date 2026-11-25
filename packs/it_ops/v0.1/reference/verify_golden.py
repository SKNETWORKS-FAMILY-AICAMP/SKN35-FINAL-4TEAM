"""등록한 골든의 스키마·문항 연결·조건별 기대값을 임시 검사기로 재생한다."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend/src"))

from deployment_answer import PACK_DIR
from run_pack import grade_task
from slotagent.common import checks, contracts
from slotagent.grading.eng_context import from_tools
from slotagent.grading.eng_rules import RulePolicyRequired, check
from slotagent.packs.loader import read_pack

KINDS = {"success", "alt_success", "near_miss", "forbidden"}


def verify_product_rules(pack_dir: Path = PACK_DIR):
    """공식 연습 권한표와 문항 정책으로 규칙 함수만 대조. 전체 채점 흐름 검증은 아님."""
    pack, _, goldens = read_pack(pack_dir)
    tasks = {t["code"]: t for t in pack["tasks"]}
    tools = json.loads((pack_dir / "practice/tool_permissions.json").read_text(encoding="utf-8"))["tools"]
    mismatches, undecidable = [], []
    for entry, trace in goldens:
        task = tasks[entry["task_code"]]
        context = from_tools(tools, task.get("confirmation"))
        actual = {}
        for condition in task["conditions"]:
            try:
                actual[str(condition["seq"])] = check(condition["kind"], condition["spec"], trace, **context)[0]
            except RulePolicyRequired as exc:
                undecidable.append({"trace": entry["trace"], "seq": condition["seq"], "reason": str(exc)})
        success = trace.get("run_outcome") == "completed" and all(
            actual.get(str(c["seq"]), False) for c in task["conditions"]
            if checks.condition_gate(c["kind"], c["spec"]))
        forbidden = any(not actual.get(str(c["seq"]), True) for c in task["conditions"] if c["kind"] == "forbidden")
        result = {"success": success, "conditions": actual, "forbidden_action": forbidden}
        if result != {key: entry["expected"][key] for key in result}:
            mismatches.append({"trace": entry["trace"], "expected": entry["expected"], "actual": result})
    return {"registered": len(goldens), "mismatches": mismatches, "undecidable": undecidable,
            "all_matched": not mismatches and not undecidable, "grading_pipeline_verified": False}


def verify_golden(pack_dir: Path = PACK_DIR, template_code: str | None = "DEPLOY_LATEST_SUCCESS") -> dict:
    pack_dir = pack_dir.resolve()
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    tasks = {t["code"]: t for t in pack["tasks"]}
    templates = [t for t in pack["templates"] if template_code is None or t["code"] == template_code]
    entries = [g for g in pack["golden"] if any(t["code"] == g["template"] for t in templates)]
    if not templates:
        raise ValueError("Unknown golden template")
    for template in templates:
        suite = [g for g in entries if g["template"] == template["code"]]
        if len(suite) != 4 or {g["kind"] for g in suite} != KINDS:
            raise ValueError("Representative template requires exactly four golden kinds")
    results = []
    for entry in entries:
        expected = contracts.validate("pack", entry["expected"], part="golden_expected")
        task = tasks[entry["task_code"]]
        if task["template"] != entry["template"]:
            raise ValueError("Golden task/template mismatch")
        for condition in task["conditions"]:
            contracts.validate("answer_condition", condition["spec"], part=condition["kind"])
        checks.check_task_conditions(task["conditions"])
        trace_path = (pack_dir / entry["trace"]).resolve()
        if not trace_path.is_relative_to(pack_dir / "golden"):
            raise ValueError("Golden trace must stay inside golden directory")
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        contracts.validate("trace", trace)
        actual = grade_task(task, trace)
        conditions = actual["conditions"]
        forbidden = any(c["kind"] == "forbidden" and not conditions[str(c["seq"])] for c in task["conditions"])
        if (actual["success"] != expected["success"] or conditions != expected["conditions"]
                or forbidden != expected["forbidden_action"]):
            raise ValueError(f"{entry['kind']}: golden expectation mismatch")
        results.append({"template": entry["template"], "kind": entry["kind"], "success": actual["success"], "conditions": conditions})
    return {"registered": len(results), "temporary_checks_passed": True,
            "product_grader_verified": False, "independent_review_completed": False,
            "classification_verified": False, "results": results}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--product-rules", action="store_true")
    args = parser.parse_args()
    report = verify_product_rules() if args.product_rules else verify_golden(template_code=None if args.all else "DEPLOY_LATEST_SUCCESS")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.product_rules and not report["all_matched"]:
        raise SystemExit(1)
