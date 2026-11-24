"""단일 IT 운영 평가팩의 가짜 실행 및 그룹별 임시 채점 진입점."""

import argparse
import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[2] / "backend/src"))
sys.path.insert(0, str(ROOT / "reference"))

from slotagent.packs.groups import load_groups


@lru_cache
def evaluator(group):
    if group == "lookup":
        import smoke_run
        return smoke_run
    if group not in load_groups(ROOT):
        raise ValueError("Unknown task group")
    path = ROOT / "reference/evaluators" / f"{group}.py"
    spec = importlib.util.spec_from_file_location(f"it_ops_{group}_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grade_task(task, trace):
    group = next(name for name, entry in load_groups(ROOT).items()
                 if task["template"] in entry["template_codes"])
    module = evaluator(group)
    if group != "lookup":
        return module.grade(task, trace)
    result = module.grade_smoke(task, trace)
    conditions = {str(c["seq"]): c["passed"] for c in result["conditions"]}
    return {"success": result["success"], "conditions": conditions,
            "forbidden_action": any(c["kind"] == "forbidden" and not conditions[str(c["seq"])]
                                    for c in task["conditions"])}


def run(output_dir, group=None):
    groups = load_groups(ROOT)
    if group is not None and group not in groups:
        raise ValueError("Unknown task group")
    output_dir = Path(output_dir)
    reports = {name: evaluator(name).run(output_dir / name)
               for name in groups if group is None or name == group}
    report = {"pack_code": "it_ops", "pack_version": "v0.1", "simulation": True,
              "product_grader_verified": False,
              "runs": sum(r["runs"] for r in reports.values()),
              "all_matched": all(r["all_matched"] for r in reports.values()),
              "groups": {name: {k: r[k] for k in ("runs", "all_matched")} for name, r in reports.items()}}
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=list(load_groups(ROOT)))
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/it-ops-smoke"))
    args = parser.parse_args()
    result = run(args.output_dir, args.group)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["all_matched"] else 1)
