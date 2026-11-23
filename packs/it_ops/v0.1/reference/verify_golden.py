"""등록한 골든의 스키마·문항 연결·조건별 기대값을 임시 검사기로 재생한다."""

import json
from pathlib import Path

from deployment_answer import PACK_DIR
from slotagent.common import checks, contracts
from smoke_run import grade_smoke

KINDS = {"success", "alt_success", "near_miss", "forbidden"}


def verify_golden(pack_dir: Path = PACK_DIR) -> dict:
    pack_dir = pack_dir.resolve()
    pack = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    tasks = {t["code"]: t for t in pack["tasks"]}
    entries = [g for g in pack["golden"] if g["template"] == "DEPLOY_LATEST_SUCCESS"]
    if len(entries) != 4 or {g["kind"] for g in entries} != KINDS:
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
        actual = grade_smoke(task, trace)
        conditions = {str(c["seq"]): c["passed"] for c in actual["conditions"]}
        forbidden = any(c["kind"] == "forbidden" and not conditions[str(c["seq"])] for c in task["conditions"])
        if (actual["success"] != expected["success"] or conditions != expected["conditions"]
                or forbidden != expected["forbidden_action"]):
            raise ValueError(f"{entry['kind']}: golden expectation mismatch")
        results.append({"kind": entry["kind"], "success": actual["success"], "conditions": conditions})
    return {"registered": len(results), "temporary_checks_passed": True,
            "product_grader_verified": False, "independent_review_completed": False,
            "classification_verified": False, "results": results}


if __name__ == "__main__":
    print(json.dumps(verify_golden(), ensure_ascii=False, indent=2))
