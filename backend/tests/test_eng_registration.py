"""① 자체 조회 도구의 고정 응답 실행과, ④가 등록 때 부르는 검사·자리 목록을 확인합니다."""

import copy
import json

import pytest
from conftest import load
from eng_write_examples import call, run, snapshot

from slotagent.common import checks, contracts
from slotagent.engine import eng_docker
from slotagent.engine.eng_stdio import LocalStdioConfig
from slotagent.engine.tool_search import SEARCH
from slotagent.engine.write_proxy import BUILTIN_NAMES

CUSTOM = {
    "name": "get_owner", "description": "담당자 조회", "service": "github", "access": "read", "origin": "custom",
    "capabilities": ["github.issues.read"],
    "parameters": {"type": "object", "required": ["service"], "properties": {
        "service": {"type": "string"}, "flag": {"type": ["boolean", "integer"]},
        "region": {"type": "string", "default": "kr"}}},
    "fixed_responses": [
        {"when": {"service": "flagged", "flag": True}, "result": "참"},
        {"when": {"service": "ops", "region": "kr"}, "result": '{"owner":"kim"}'},
        {"when": {"service": "ops"}, "result": "다른 지역"}],
}


def custom_snapshot(only=False):
    snap = snapshot()
    tools = [t for t in snap["tools"] if t["access"] == "write"] if only else snap["tools"]
    snap["tools"] = sorted([*tools, copy.deepcopy(CUSTOM)], key=lambda t: t["name"])
    if only:
        snap["mcp_servers"] = []
    return snap


def answer(**args):
    trace, model = run([call("get_owner", **args)], "끝", snap=custom_snapshot())
    contracts.validate("trace", trace)
    return next(s for s in trace["spans"] if s["kind"] == "tool"), trace, model


@pytest.mark.parametrize("args,want", [
    ({"service": "ops"}, '{"owner":"kim"}'),  # 기본값(region=kr)까지 채워 비교, 맞는 첫 항목
    ({"service": "ops", "region": "us"}, "다른 지역"),
    ({"service": "flagged", "flag": True}, "참"),
])
def test_custom_read_returns_fixed_response(args, want):
    span, trace, model = answer(**args)  # 밖으로 나가면 run 이 실패함
    assert span["tool_result"] == want and "error" not in span
    assert span["tool_args"] == args and span["attributes"]["fixed_response"] is True
    assert model.requests[1]["messages"][-1]["content"] == want
    assert "fixed_responses" not in json.dumps(model.requests[0]["tools"])  # 정답이 모델에 안 보임


@pytest.mark.parametrize("args", [{"service": "other"}, {"service": "flagged", "flag": 1}])
def test_no_match_is_tool_error_and_run_continues(args):
    span, trace, _ = answer(**args)
    assert span["error"] == "tool_error"
    assert json.loads(span["tool_result"]) == {"error": "no_fixed_response"}
    assert trace["run_outcome"] == "completed"


def test_invalid_arguments_do_not_match():
    span, _, _ = answer(service=1)
    assert span["error"] == "agent_invalid_tool_call"


def stdio():
    return LocalStdioConfig({"github": ["eng-does-not-exist"]}), {}


def docker(monkeypatch):
    monkeypatch.setattr(eng_docker, "DockerControl", lambda *a, **k: None)
    setting = eng_docker.DockerStdioConfig({"github": eng_docker.DockerServer("x@sha256:" + "0" * 64)}, scope="t")
    return setting, {"execution": dict.fromkeys(("trial_id", "attempt", "job_id", "lease_attempt"), 1)}


@pytest.mark.parametrize("kind", ["stdio", "docker"])
def test_only_custom_reads_need_no_server(kind, monkeypatch):
    setting, extra = stdio() if kind == "stdio" else docker(monkeypatch)
    with setting.open(custom_snapshot(only=True), **extra) as call_tool, pytest.raises(ValueError):
        call_tool("get_owner", {}, 1)


@pytest.mark.parametrize("kind", ["stdio", "docker"])
def test_mixed_tools_connect_only_mcp(kind, monkeypatch):
    setting, extra = stdio() if kind == "stdio" else docker(monkeypatch)
    from contextlib import nullcontext

    from slotagent.engine import eng_stdio

    seen = []

    def fake(*args, **kwargs):
        seen.extend(args[1] if kind == "stdio" else args[2])
        return nullcontext(lambda *a: "mcp")

    monkeypatch.setattr(eng_stdio if kind == "stdio" else eng_docker,
                        "StdioTools" if kind == "stdio" else "DockerStdioTools", fake)
    with setting.open(custom_snapshot(), **extra) as call_tool:
        assert call_tool("list_issues", {}, 1) == "mcp"
    assert seen and all(t["origin"] == "mcp:github" for t in seen)


def test_builtin_read_is_still_rejected():
    snap = custom_snapshot()
    tool = next(t for t in snap["tools"] if t["name"] == "get_owner")
    tool["origin"] = "builtin"
    del tool["fixed_responses"]
    with pytest.raises(NotImplementedError), stdio()[0].open(snap):
        pass


# ---- 등록 --------------------------------------------------------------
def spec(*extra):
    value = copy.deepcopy(load("agent_version.json")["spec"])
    value["tools"].extend(copy.deepcopy(extra))
    return value


def test_reserved_names_follow_engine():
    assert checks.RESERVED_TOOL_NAMES == BUILTIN_NAMES | {SEARCH}


def test_slots_from_example():
    checks.check_registration("spec_upload", spec())
    slots = {s["name"]: s for s in checks.build_slots("spec_upload", "C2", spec())}
    assert set(slots) == {"GitHub 조회", "GitHub 쓰기", "Slack 쓰기"}
    assert slots["GitHub 조회"]["comparable"] and slots["GitHub 조회"]["not_comparable_reason"] is None
    assert slots["Slack 쓰기"]["not_comparable_reason"] == checks.NOT_COMPARABLE_WRITE
    for slot in slots.values():  # 비교할 수 없는 자리도 기준 A 를 만들 수 있음
        contracts.validate("component_spec", checks.baseline_component(spec(), slot))


@pytest.mark.parametrize("connection,level,reason", [
    ("spec_upload", "C2", checks.NOT_COMPARABLE_CUSTOM),
    ("runner", "C2", None),
    ("runner", "C1", checks.NOT_COMPARABLE_API),
    ("api", "C1", checks.NOT_COMPARABLE_API),
])
def test_custom_read_slot(connection, level, reason):
    slots = checks.build_slots(connection, level, spec(CUSTOM))
    read = next(s for s in slots if s["access"] == "read")
    assert read["not_comparable_reason"] == reason and read["comparable"] is (reason is None)


def test_write_slot_is_not_comparable_in_any_mode():
    value = spec()
    for t in value["tools"]:
        if t["access"] == "write":
            t["write_mode"] = "exclude_tasks"
    checks.check_registration("spec_upload", value)
    assert not any(s["comparable"] for s in checks.build_slots("spec_upload", "C2", value) if s["access"] == "write")


@pytest.mark.parametrize("change,text", [
    (lambda s: s["tools"].append(copy.deepcopy(s["tools"][0])), "도구 이름"),
    (lambda s: s["services"].append({"code": "github", "name": "다른 이름"}), "서비스 code"),
    (lambda s: s["services"].append({"code": "gh2", "name": "GitHub"}), "서비스 이름"),
    (lambda s: s["services"].pop(), "services 에 없습니다"),
    (lambda s: s["tools"][0].update(name="search_tools"), "엔진이 쓰는"),
    (lambda s: s["tools"][0].update(name="request_user_confirmation"), "엔진이 쓰는"),
    (lambda s: s["tools"][-1].pop("capabilities"), "이름표"),
    (lambda s: s["tools"][-1].update(write_mode="dry_run"), "write_mode"),
])
def test_registration_rejects(change, text):
    value = spec()
    change(value)
    with pytest.raises(checks.CheckError, match=text) as caught:
        checks.check_registration("spec_upload", value)
    assert caught.value.code == "invalid_spec"
