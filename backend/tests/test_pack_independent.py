"""② 독립 준비물: 전체 골든·MCP 원본·묶음 선택 검증."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from slotagent.packs.select import plan_rows
from slotagent.packs.groups import load_group

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "packs/it_ops/v0.1"
sys.path.insert(0, str(PACK / "reference"))


def test_all_fifteen_golden_suites():
    from smoke_run import grade_smoke

    pack = load_group(PACK, "lookup")
    tasks = {t["code"]: t for t in pack["tasks"]}
    assert len(pack["golden"]) == 60
    for template in pack["templates"]:
        entries = [g for g in pack["golden"] if g["template"] == template["code"]]
        assert {g["kind"] for g in entries} == {"success", "alt_success", "near_miss", "forbidden"}
        for entry in entries:
            trace = json.loads((PACK / entry["trace"]).read_text(encoding="utf-8"))
            actual = grade_smoke(tasks[entry["task_code"]], trace)
            assert actual["success"] == entry["expected"]["success"]
            assert {str(c["seq"]): c["passed"] for c in actual["conditions"]} == entry["expected"]["conditions"]


def test_server_filters_and_schema_validation(tmp_path):
    spec = importlib.util.spec_from_file_location("practice_server", PACK / "practice/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = module.PracticeData(PACK / "practice/servers.json", PACK / "data")
    assert len(data.metadata()["tools"]) == 5
    assert data.call("list_issues", {"repo": "acme/missing"}) == []
    assert {r["repo"] for r in data.call("list_deployments", {"repo": "acme/ops-service"})} == {"acme/ops-service"}
    with pytest.raises(ValidationError):
        data.call("list_issues", {"unexpected": True})
    with pytest.raises(ValueError, match="Unknown tool"):
        data.call("write", {})
    for path in (PACK / "data").glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    path = tmp_path / "deployments.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["deployments"][0]["version"] = "tampered"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen snapshot mismatch"):
        module.PracticeData(PACK / "practice/servers.json", tmp_path)


def test_plan_rows_excludes_whole_exposed_type_and_keeps_groups():
    rows = [(3, 31, False), (1, 11, False), (1, 12, True), (2, 21, False),
            (3, 32, False), (4, 41, False)]
    assert plan_rows(rows, 3, 2) == [{"task_id": 21, "batch_no": 1}, {"task_id": 31, "batch_no": 1},
                                     {"task_id": 32, "batch_no": 1}, {"task_id": 41, "batch_no": 2}]
    with pytest.raises(ValueError, match="fresh templates"):
        plan_rows(rows, 4)
    with pytest.raises(ValueError):
        plan_rows(rows, 1, 2)
    with pytest.raises(ValueError):
        plan_rows(rows, True)
