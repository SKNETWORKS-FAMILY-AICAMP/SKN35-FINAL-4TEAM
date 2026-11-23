"""새 10개 유형의 정답을 생성 코드와 독립적인 기대값으로 검증한다."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1/reference"))

from batch_reference import CODES, PACK_DIR, calculate, verify_batch


def test_thirty_answers_and_template_sizes():
    answers = verify_batch()
    assert len(answers) == 30
    for index in range(1, 4):
        prefix = index * 100
        expected = [
            {"run_ids": [str(prefix+1), str(prefix+5)]},
            {"run_ids": ["103"] if index == 1 else ["201", "203", "205"] if index == 2 else []},
            {"success_count": 1 if index == 3 else 2, "failure_count": 0 if index == 3 else 2},
            {"run_ids": [str(prefix+2)]},
            {"production_version": f"v2.{index}.0", "staging_version": f"v3.{index}.0-rc1"},
            {"issue_ids": ["101"] if index == 1 else ["205"] if index == 2 else []},
            {"issue_ids": ["102"] if index == 1 else ["202", "204"] if index == 2 else []},
            {"issue_ids": [str(prefix+3)]},
            {"bug_count": 2, "urgent_count": 2},
            {"release_tag": f"v3.{index}.0-rc1" if index == 3 else f"v2.{index}.0"},
        ]
        for code, answer in zip(CODES, expected, strict=True):
            assert answers[f"{code}-{index:03d}"] == answer
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    for code in CODES:
        assert sum(t["template"] == code for t in pack["tasks"]) == 3


def test_order_independence_and_broken_release_relation():
    data = json.loads((PACK_DIR / "data/operations.json").read_text(encoding="utf-8"))
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    reversed_data = {k: list(reversed(v)) if isinstance(v, list) else v for k, v in data.items()}
    for task in pack["tasks"]:
        if task["template"] in CODES:
            assert calculate(task["template"], task["slot_values"], data) == calculate(
                task["template"], task["slot_values"], reversed_data)
    task = next(t for t in pack["tasks"] if t["code"] == "DEPLOY_RELEASE_LINK-001")
    broken = copy.deepcopy(data)
    next(r for r in broken["releases"] if r["sha"] == "repo1-latest")["repo"] = "acme/wrong-repo"
    with pytest.raises(ValueError, match="missing or ambiguous"):
        calculate(task["template"], task["slot_values"], broken)


def test_snapshot_drift_rejected(tmp_path):
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    data = json.loads((PACK_DIR / "data/operations.json").read_text(encoding="utf-8"))
    data["runs"][0]["status"] = "success"
    (tmp_path / "data").mkdir()
    (tmp_path / "data/operations.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from snapshot"):
        verify_batch(tmp_path)
