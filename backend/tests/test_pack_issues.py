"""이슈 정답의 저장소·라벨·상태·담당자 조건과 빈 결과를 확인한다."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PACK_DIR = Path(__file__).resolve().parents[2] / "packs" / "it_ops" / "v0.1"
sys.path.insert(0, str(PACK_DIR / "reference"))
spec = importlib.util.spec_from_file_location("issue_reference", PACK_DIR / "reference" / "issue_answer.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def test_issue_answers():
    assert reference.verify_issues() == {
        "ISSUES_UNASSIGNED_OPEN-001": {"issues": ["145", "148"]},
        "ISSUES_UNASSIGNED_OPEN-002": {"issues": ["152"]},
        "ISSUES_UNASSIGNED_OPEN-003": {"issues": ["145", "210"]},
        "ISSUES_UNASSIGNED_OPEN-004": {"issues": []},
    }
    rows = json.loads((PACK_DIR / "data/issues.json").read_text(encoding="utf-8"))["issues"]
    assert reference.issue_answer(list(reversed(rows)), repo="acme/ops-service", label="bug") == {
        "issues": ["145", "148"]
    }


def test_issue_snapshot_drift(tmp_path):
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    data = json.loads((PACK_DIR / "data/issues.json").read_text(encoding="utf-8"))
    data["issues"][0]["assignees"] = ["new-owner"]
    (tmp_path / "data").mkdir()
    (tmp_path / "data/issues.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="differ from snapshot"):
        reference.verify_issues(tmp_path)


def test_issue_set_order_and_missing_results(tmp_path):
    from smoke_run import grade_smoke, run

    run(tmp_path)
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    task = next(t for t in pack["tasks"] if t["code"] == "ISSUES_UNASSIGNED_OPEN-001")
    trace = json.loads((tmp_path / f"{task['code']}.success.trace.json").read_text(encoding="utf-8"))
    trace["final_answer"] = json.dumps({"issues": ["148", "145"]})
    assert grade_smoke(task, trace)["success"]
    trace["final_answer"] = json.dumps({"issues": ["145"]})
    assert not grade_smoke(task, trace)["success"]
    trace["final_answer"] = json.dumps({"issues": []})
    assert not grade_smoke(task, trace)["success"]
