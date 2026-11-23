"""실행 기록을 생성하고 오답·출처 누락·금지 행동을 구별하는지 확인한다."""

import importlib.util
import json
import sys
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parents[2] / "packs" / "it_ops" / "v0.1"
sys.path.insert(0, str(PACK_DIR / "reference"))
spec = importlib.util.spec_from_file_location("deployment_smoke", PACK_DIR / "reference" / "smoke_run.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_smoke_matrix_and_evidence(tmp_path):
    report = smoke.run(tmp_path)
    assert report["runs"] == 190
    assert report["unsupported_templates"] == []
    assert report["all_matched"]
    assert len(list(tmp_path.glob("*.trace.json"))) == 190
    tasks = {t["code"]: t for t in json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))["tasks"]}
    for result in report["results"]:
        conditions = {c["seq"]: c for c in result["conditions"]}
        task = tasks[result["task_code"]]
        info_seqs = [c["seq"] for c in task["conditions"] if c["kind"] in {"info", "link"}]
        if result["scenario"] in {"success", "alternate"}:
            assert all(conditions[seq]["span_seqs"] for seq in info_seqs)
        if result["scenario"] == "ungrounded":
            assert all(not conditions[seq]["passed"] for seq in info_seqs)
        if result["scenario"] == "forbidden":
            assert all(conditions[seq]["passed"] for seq in info_seqs)
            assert all(not c["passed"] for seq, c in conditions.items() if seq not in info_seqs)


def test_regrading_and_answer_tampering(tmp_path):
    smoke.run(tmp_path)
    task = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))["tasks"][0]
    trace = json.loads((tmp_path / f"{task['code']}.success.trace.json").read_text(encoding="utf-8"))
    assert smoke.grade_smoke(task, trace) == smoke.grade_smoke(task, trace)
    trace["final_answer"] = '{"finished_at":"18:20","version":"v0.0.0"}'
    assert not smoke.grade_smoke(task, trace)["success"]


def test_release_requires_both_sources_and_relation(tmp_path):
    smoke.run(tmp_path)
    pack = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))
    task = next(t for t in pack["tasks"] if t["code"] == "DEPLOY_RELEASE_LINK-001")
    source = json.loads((tmp_path / f"{task['code']}.success.trace.json").read_text(encoding="utf-8"))
    for missing in ("list_operation_runs", "list_operation_releases"):
        trace = {**source, "spans": [s for s in source["spans"] if s.get("name") != missing]}
        assert not smoke.grade_smoke(task, trace)["success"]
    trace = json.loads(json.dumps(source))
    releases = next(s for s in trace["spans"] if s.get("name") == "list_operation_releases")
    rows = json.loads(releases["tool_result"])
    next(r for r in rows if r["sha"] == "repo1-latest")["sha"] = "wrong-sha"
    releases["tool_result"] = json.dumps(rows)
    assert not smoke.grade_smoke(task, trace)["success"]
    trace["final_answer"] = "invalid JSON"
    assert not smoke.grade_smoke(task, trace)["success"]
