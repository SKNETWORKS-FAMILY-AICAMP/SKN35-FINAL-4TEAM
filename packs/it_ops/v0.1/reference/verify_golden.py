"""등록한 골든의 스키마·문항 연결·조건별 기대값을 임시 검사기로 재생한다."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend/src"))

from deployment_answer import PACK_DIR
from slotagent.common import checks, contracts
from run_pack import grade_task

KINDS = {"success", "alt_success", "near_miss", "forbidden"}


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
    args = parser.parse_args()
    print(json.dumps(verify_golden(template_code=None if args.all else "DEPLOY_LATEST_SUCCESS"), ensure_ascii=False, indent=2))
