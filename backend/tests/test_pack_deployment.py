"""고정 데이터의 날짜·환경 구분과 정답 조건의 정합성을 검증한다."""

import importlib.util
import json
from pathlib import Path

import pytest
from slotagent.common import checks, contracts

PACK_DIR = Path(__file__).resolve().parents[2] / "packs" / "it_ops" / "v0.1"
spec = importlib.util.spec_from_file_location("deployment_answer", PACK_DIR / "reference" / "deployment_answer.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_reference_matches_pack_and_contracts():
    pack = read_json(PACK_DIR / "pack.json")
    contracts.validate("pack", pack["pack_version"]["premises"], part="premises")
    for snapshot in pack["data_snapshots"]:
        contracts.validate("pack", snapshot["design"], part="data_design")
        assert (PACK_DIR / snapshot["location"]).is_file()
    for template in pack["templates"]:
        contracts.validate("pack", template["required_capabilities"], part="required_capabilities")
    for task in pack["tasks"]:
        for condition in task["conditions"]:
            contracts.validate("answer_condition", condition["spec"], part=condition["kind"])
        checks.check_task_conditions(task["conditions"])
    assert len(pack["templates"]) == 12
    assert len(pack["tasks"]) == 38
    assert len({task["code"] for task in pack["tasks"]}) == 38
    template_codes = {t["code"] for t in pack["templates"]}
    assert all(task["template"] in template_codes for task in pack["tasks"])
    assert reference.verify_pack() == {
        "DEPLOY_LATEST_SUCCESS-001": {"finished_at": "18:20", "version": "v1.8.3"},
        "DEPLOY_LATEST_SUCCESS-002": {"finished_at": "00:05", "version": "v1.8.5"},
        "DEPLOY_LATEST_SUCCESS-003": {"finished_at": "19:00", "version": "v1.9.0-rc1"},
        "DEPLOY_LATEST_SUCCESS-004": {"finished_at": "21:00", "version": "v3.0.0"},
    }


@pytest.mark.parametrize("day, expected", [
    ("2026-11-16", {"finished_at": "18:20", "version": "v1.8.3"}),
    ("2026-11-17", {"finished_at": "00:05", "version": "v1.8.5"}),
])
def test_local_date_filters_and_order_independence(day, expected):
    rows = read_json(PACK_DIR / "data" / "deployments.json")["deployments"]
    for ordered in (rows, list(reversed(rows))):
        assert reference.deployment_answer(
            ordered, repo="acme/ops-service", environment="production", day=day
        ) == expected


def test_missing_ambiguous_and_naive_times_are_rejected():
    rows = read_json(PACK_DIR / "data" / "deployments.json")["deployments"]
    args = {"repo": "acme/ops-service", "environment": "production", "day": "2026-11-16"}
    with pytest.raises(ValueError, match="No matching"):
        reference.deployment_answer([], **args)
    winner = next(row for row in rows if row["run_id"] == 306)
    with pytest.raises(ValueError, match="Ambiguous"):
        reference.deployment_answer([winner, dict(winner, run_id=999)], **args)
    with pytest.raises(ValueError, match="timezone"):
        reference.deployment_answer([dict(winner, finished_at="2026-11-16T18:20:00")], **args)


def test_changed_source_or_answer_is_detected(tmp_path):
    pack = read_json(PACK_DIR / "pack.json")
    data = read_json(PACK_DIR / "data" / "deployments.json")
    (tmp_path / "data").mkdir()
    target = tmp_path / "data" / "deployments.json"
    target.write_text(json.dumps(data), encoding="utf-8")
    pack["tasks"][0]["conditions"][0]["spec"]["expected"] = "19:00"
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="differ from snapshot"):
        reference.verify_pack(tmp_path)
    pack["tasks"][0]["conditions"][0]["spec"]["expected"] = "18:20"
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    next(row for row in data["deployments"] if row["run_id"] == 306)["version"] = "v9.9.9"
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="differ from snapshot"):
        reference.verify_pack(tmp_path)
