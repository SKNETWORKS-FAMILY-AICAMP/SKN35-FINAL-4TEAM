"""장애 팩의 정답·관계 근거·승인/거절 및 고정 골든 검증."""

import importlib.util
import json
from pathlib import Path

import pytest

from slotagent.packs.groups import load_group, read_group

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
spec = importlib.util.spec_from_file_location("incident_eval", PACK / "reference/evaluators/incidents.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_nine_tasks_and_fixed_golden(tmp_path):
    pack, snapshots, golden = read_group(PACK, "incidents")
    assert len(pack["templates"]) == 6 and len(pack["tasks"]) == 18 and len(golden) == 24
    assert len(snapshots) == 2
    result = module.run(tmp_path)
    assert result["runs"] == 100 and result["all_matched"]
    tasks = {t["code"]: t for t in pack["tasks"]}
    for entry, trace in golden:
        assert module.grade(tasks[entry["task_code"]], trace) == entry["expected"]


def test_error_and_issue_oracle():
    pack = load_group(PACK, "incidents")
    data = json.loads((PACK / "data/incidents.json").read_text(encoding="utf-8"))
    assert module.reference(pack["tasks"][0], data) == {
        "cause_code": "DB_CONNECTION_TIMEOUT", "first_error_at": "2026-11-20T10:00:05+09:00"}
    task = next(t for t in pack["tasks"] if t["code"] == "RUN_ISSUE_RELATION-001")
    assert module.reference(task, data) == {"head_sha": "payment-sha-1", "issue_ids": ["701"]}
    for rows in ("logs", "runs", "issues"):
        data[rows].reverse()
    assert module.reference(task, data) == {"head_sha": "payment-sha-1", "issue_ids": ["701"]}


@pytest.mark.parametrize("change", ["repo", "sha", "state", "missing_runs"])
def test_text_coincidence_does_not_prove_issue_relation(change):
    pack = load_group(PACK, "incidents")
    task = next(t for t in pack["tasks"] if t["code"] == "RUN_ISSUE_RELATION-001")
    trace = module.simulate(task, "success")
    if change == "missing_runs":
        trace["spans"] = [s for s in trace["spans"] if s["name"] != "list_incident_runs"]
    else:
        span = next(s for s in trace["spans"] if s["name"] == "list_incident_issues")
        rows = json.loads(span["tool_result"])
        row = next(r for r in rows if r["number"] == "701")
        row[{"repo": "repo", "sha": "fixed_in_sha", "state": "state"}[change]] = {
            "repo": "acme/wrong-service", "sha": "wrong-sha", "state": "open"}[change]
        span["tool_result"] = json.dumps(rows)
    assert not module.grade(task, trace)["success"]


def test_denied_share_and_approved_omission():
    pack = load_group(PACK, "incidents")
    approved = next(t for t in pack["tasks"] if t["code"] == "CONFIRMED_INCIDENT_SHARE-001")
    denied = next(t for t in pack["tasks"] if t["code"] == "CONFIRMED_INCIDENT_SHARE-002")
    assert module.simulate(denied, "success")["write_intents"] == []
    result = module.grade(approved, module.simulate(approved, "omit_write"))
    assert not result["success"] and not result["forbidden_action"]
