"""임시 데이터 변이로 쓰기 내용·조회 근거·승인 무결성을 검증한다."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from slotagent.packs.groups import load_group

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
spec = importlib.util.spec_from_file_location("write_context_eval", PACK / "reference/evaluators/writes.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TASKS = [t for t in load_group(PACK, "writes")["tasks"] if t["template"] in {"CONFIRMED_RELEASE_SHARE", "CONFIRMED_ISSUE_CREATE"}]


@pytest.fixture
def context_copy(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    data = json.loads((PACK / "data/context.json").read_text(encoding="utf-8"))
    path = tmp_path / "data/context.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return path, data


@pytest.mark.parametrize("original", TASKS, ids=lambda t: t["code"])
def test_context_version_mutation_and_stale_trace(context_copy, original):
    path, data = context_copy
    task = copy.deepcopy(original)
    old_trace = module.simulate(task, "normal")
    data["contexts"][0]["version"] = "v2.2.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    task["prompt"] = task["prompt"].replace("v2.1.0", "v2.2.0")
    for scenario in ("normal", "alternate"):
        trace = module.simulate(task, scenario)
        request = next(s for s in trace["spans"] if s["name"] == "request_user_confirmation")
        args = request["tool_args"]["action"]["arguments"]
        assert "v2.2.0" in args.get("text", args.get("title", ""))
        assert module.grade(task, trace)["success"]
    assert not module.grade(task, old_trace)["success"]
    # 조회 기록만 최신 데이터로 위조해도 이전 버전 요청/쓰기는 내용 검사에서 실패해야 한다.
    old_trace["spans"][0]["tool_result"] = json.dumps(data["contexts"][0])
    assert not module.grade(task, old_trace)["success"]


@pytest.mark.parametrize("code", ["CONFIRMED_RELEASE_SHARE-001", "CONFIRMED_ISSUE_CREATE-001"])
@pytest.mark.parametrize("bad", ["v2.1.00", "v2.1.0-old", "v2.1.0 v9.0.0", "버전 없음"])
def test_approved_but_wrong_content_is_not_completion(context_copy, code, bad):
    task = next(t for t in TASKS if t["code"] == code)
    trace = module.simulate(task, "normal")
    # 승인 요청과 실제 인자는 똑같이 변경: 승인 일치만으로 잘못된 내용이 통과하면 안 된다.
    for span in trace["spans"]:
        if span["name"] == "request_user_confirmation":
            args = span["tool_args"]["action"]["arguments"]
        elif span["name"] in module.CAPS:
            args = span["tool_args"]
        else:
            continue
        args["text" if "text" in args else "title"] = bad
    trace["write_intents"][0]["payload"] = copy.deepcopy(trace["spans"][-1]["tool_args"])
    # 엔진 응답 역시 해당 요청에 대한 정상 승인으로 재생한다.
    request = next(s for s in trace["spans"] if s["name"] == "request_user_confirmation")
    request["tool_result"] = json.dumps(module.fixed_response(task["confirmation"], request["tool_args"], 0, module.CAPS))
    result = module.grade(task, trace)
    assert not result["success"] and not result["conditions"]["2"]
    assert not result["forbidden_action"]


@pytest.mark.parametrize("change", ["missing_id", "duplicate_id", "missing_version", "wrong_target"])
def test_invalid_context_fails_before_confirmation(context_copy, change):
    path, data = context_copy
    task = copy.deepcopy(TASKS[0])
    if change == "missing_id":
        task["slot_values"]["context_id"] = "missing"
    elif change == "duplicate_id":
        data["contexts"].append(copy.deepcopy(data["contexts"][0]))
    elif change == "missing_version":
        del data["contexts"][0]["version"]
    else:
        data["contexts"][0]["channel"] = "wrong-channel"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        module.simulate(task, "normal")


@pytest.mark.parametrize("change", ["omit", "forge", "late", "changed_after_approval"])
def test_lookup_evidence_and_approval_integrity(context_copy, change):
    task = TASKS[0]
    trace = module.simulate(task, "changed_after_approval" if change == "changed_after_approval" else "normal")
    if change == "omit":
        trace["spans"].pop(0)
    elif change == "forge":
        trace["spans"][0]["tool_result"] = "{}"
    elif change == "late":
        trace["spans"][0]["seq"] = 100
    result = module.grade(task, trace)
    assert not result["success"]
    if change == "changed_after_approval":
        assert result["forbidden_action"]
