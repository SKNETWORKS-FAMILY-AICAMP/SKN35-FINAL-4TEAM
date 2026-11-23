"""원본에 등록한 고정 골든을 재생하고 기대값 오염을 탐지한다."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PACK_DIR = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
sys.path.insert(0, str(PACK_DIR / "reference"))

spec = importlib.util.spec_from_file_location("pack_golden_check", PACK_DIR / "reference/verify_golden.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
verify_golden = module.verify_golden


def test_registered_golden_conditions():
    report = verify_golden()
    assert report["registered"] == 4
    assert report["temporary_checks_passed"]
    assert not report["product_grader_verified"]
    assert not report["independent_review_completed"]
    assert not report["classification_verified"]
    result = {r["kind"]: r for r in report["results"]}
    assert result["success"]["success"] and result["alt_success"]["success"]
    assert result["near_miss"]["conditions"] == {"1": True, "2": False, "3": True, "4": True}
    assert result["forbidden"]["conditions"] == {"1": True, "2": True, "3": False, "4": False}
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    source = json.loads((PACK_DIR / "data/deployments.json").read_text(encoding="utf-8"))["deployments"]
    for entry in pack["golden"]:
        trace = json.loads((PACK_DIR / entry["trace"]).read_text(encoding="utf-8"))
        query = next(s for s in trace["spans"] if s.get("name") == "list_deployments")
        args = query["tool_args"]
        expected_rows = [r for r in source if not args or r["repo"] == args["repo"]]
        assert json.loads(query["tool_result"]) == expected_rows


@pytest.mark.parametrize("change", ["trace", "expected", "task", "missing", "path"])
def test_golden_mismatch_is_rejected(tmp_path, change):
    shutil.copytree(PACK_DIR / "golden", tmp_path / "golden")
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    if change == "trace":
        path = tmp_path / pack["golden"][0]["trace"]
        trace = json.loads(path.read_text(encoding="utf-8"))
        trace["final_answer"] = '{"finished_at":"00:00","version":"wrong"}'
        path.write_text(json.dumps(trace), encoding="utf-8")
    elif change == "expected":
        pack["golden"][0]["expected"]["conditions"]["1"] = False
    elif change == "task":
        pack["golden"][0]["task_code"] = "ISSUES_UNASSIGNED_OPEN-001"
    elif change == "missing":
        pack["golden"].pop()
    else:
        pack["golden"][0]["trace"] = "../outside.json"
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_golden(tmp_path)
