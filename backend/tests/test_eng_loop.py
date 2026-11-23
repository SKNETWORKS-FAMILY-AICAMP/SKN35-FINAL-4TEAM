"""① 가짜 모델·도구를 사용해 실제 trace 계약과 대화 연속성을 검증합니다."""

import copy
import json

import pytest
from conftest import load

from slotagent.common import contracts
from slotagent.common.llm import FakeModel, ModelError, Reply, ToolCall
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine.loop import Dependencies, RunCancelled, ToolEnvironmentError, run_agent


@pytest.fixture
def snapshot():
    data = load("slot_and_candidates.json")
    return merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][0])


def test_read_tool_then_final_answer_has_complete_conversation_and_trace(snapshot):
    original = copy.deepcopy(snapshot)
    fake = FakeModel(
        [
            Reply(
                text="조회하겠습니다",
                tool_calls=(ToolCall("id1", "list_issues", '{"owner":"acme","repo":"ops-service"}'),),
                in_tokens=20,
                out_tokens=5,
            ),
            Reply(text="열린 이슈는 145, 148입니다.", in_tokens=30, out_tokens=7),
        ]
    )
    calls = []

    def tool(name, args, timeout):
        calls.append((name, args, timeout))
        return '[{"number":145},{"number":148}]'

    result = run_agent(
        snapshot, "열린 이슈를 찾아줘", 9, Dependencies(fake, tool), prereg=load("experiment.json")["prereg"]
    )
    contracts.validate("trace", result.trace)
    assert [s["kind"] for s in result.trace["spans"]] == ["llm", "tool", "llm"]
    assert result.trace["final_answer"] == "열린 이슈는 145, 148입니다."
    assert result.trace["usage"]["in_tokens"] == 50
    assert "tool_desc_tokens" not in result.trace["usage"]
    assert [m["role"] for m in fake.requests[1]["messages"]] == ["system", "user", "assistant", "tool"]
    assert fake.requests[1]["messages"][-1]["tool_call_id"] == "id1"
    assert fake.requests[1]["messages"][-2]["tool_calls"][0]["id"] == "id1"
    assert len(calls) == 1 and calls[0][2] > 0
    assert snapshot == original


@pytest.mark.parametrize(
    "name,args", [("absent", "{}"), ("list_issues", "bad-json"), ("list_issues", "[]"), ("list_issues", "{}")]
)
def test_invalid_tool_call_is_returned_to_model_without_executing(snapshot, name, args):
    fake = FakeModel([Reply(tool_calls=(ToolCall("bad", name, args),)), Reply(text="다시 확인이 필요합니다.")])
    executed = []
    result = run_agent(
        snapshot, "조회", 1, Dependencies(fake, lambda *a: executed.append(a)), prereg=load("experiment.json")["prereg"]
    )
    assert result.outcome == "completed"
    assert result.trace["spans"][1]["error"] == "agent_invalid_tool_call"
    assert json.loads(fake.requests[1]["messages"][-1]["content"])["error"] == "agent_invalid_tool_call"
    assert not executed


def test_multiple_tool_calls_keep_assistant_and_all_tool_results(snapshot):
    fake = FakeModel(
        [
            Reply(
                tool_calls=(
                    ToolCall("a", "list_releases", '{"owner":"acme","repo":"ops-service"}'),
                    ToolCall("b", "list_issues", '{"owner":"acme","repo":"ops-service"}'),
                )
            ),
            Reply(text="끝"),
        ]
    )
    result = run_agent(
        snapshot, "조회", 2, Dependencies(fake, lambda *a: "[]"), prereg=load("experiment.json")["prereg"]
    )
    assert result.outcome == "completed"
    assert [m["role"] for m in fake.requests[1]["messages"]] == ["system", "user", "assistant", "tool", "tool"]
    assert [s["seq"] for s in result.trace["spans"]] == [1, 2, 3, 4]


def test_environment_failure_stops_with_preregistered_classification(snapshot):
    def unavailable(*args):
        raise ToolEnvironmentError()

    fake = FakeModel([Reply(tool_calls=(ToolCall("a", "list_issues", '{"owner":"acme","repo":"ops-service"}'),))])
    result = run_agent(snapshot, "조회", 1, Dependencies(fake, unavailable), prereg=load("experiment.json")["prereg"])
    assert result.outcome == "env_error"
    assert result.trace["outcome_reason"] == "env_mcp_server_down"


def test_rate_limit_classification_comes_from_preregistration(snapshot):
    prereg = load("experiment.json")["prereg"]
    for env, expected in [(False, "agent_error"), (True, "env_error")]:
        config = copy.deepcopy(prereg)
        if env:
            config["outcome_rules"]["env_error_reasons"].append("llm_api_429")
        model = FakeModel([ModelError("llm_api_429", wait_sec=1, api_retries=1)])
        result = run_agent(snapshot, "조회", 1, Dependencies(model, lambda *a: ""), prereg=config)
        assert result.outcome == expected
        assert result.trace["usage"]["api_retries"] == 1


def test_max_steps_stops_repeated_calls(snapshot):
    snapshot["runtime"]["max_steps"] = 1
    fake = FakeModel([Reply(tool_calls=(ToolCall("a", "list_issues", '{"owner":"acme","repo":"ops-service"}'),))])
    result = run_agent(
        snapshot, "조회", 1, Dependencies(fake, lambda *a: "[]"), prereg=load("experiment.json")["prereg"]
    )
    assert result.trace["outcome_reason"] == "agent_max_steps"


def test_timeout_after_tool_return_keeps_tool_record(snapshot):
    now = [0.0]
    fake = FakeModel([Reply(tool_calls=(ToolCall("a", "list_issues", '{"owner":"acme","repo":"ops-service"}'),))])

    def tool(*args):
        now[0] += snapshot["runtime"]["timeout_sec"] + 1
        return "[]"

    result = run_agent(
        snapshot, "조회", 1, Dependencies(fake, tool, clock=lambda: now[0]), prereg=load("experiment.json")["prereg"]
    )
    assert result.outcome == "timeout"
    assert result.trace["spans"][-1]["tool_result"] == "[]"


def test_cancellation_is_not_converted_to_candidate_failure(snapshot):
    fake = FakeModel([])
    with pytest.raises(RunCancelled):
        run_agent(
            snapshot,
            "조회",
            1,
            Dependencies(fake, lambda *a: "", cancelled=lambda: True),
            prereg=load("experiment.json")["prereg"],
        )
    assert not fake.requests


def test_write_call_cannot_escape_to_read_tool_router(snapshot):
    fake = FakeModel(
        [Reply(tool_calls=(ToolCall("a", "create_issue", '{"owner":"acme","repo":"ops-service","title":"x"}'),))]
    )
    executed = []
    with pytest.raises(NotImplementedError, match="쓰기 프록시"):
        run_agent(
            snapshot,
            "등록",
            1,
            Dependencies(fake, lambda *a: executed.append(a)),
            prereg=load("experiment.json")["prereg"],
        )
    assert not executed


def test_step_limit_counts_model_and_each_tool_call(snapshot):
    snapshot["runtime"]["max_steps"] = 2
    model = FakeModel(
        [
            Reply(
                tool_calls=(
                    ToolCall("a", "list_issues", '{"owner":"acme","repo":"ops-service"}'),
                    ToolCall("b", "list_issues", '{"owner":"acme","repo":"ops-service"}'),
                )
            )
        ]
    )
    calls = []
    result = run_agent(
        snapshot,
        "조회",
        1,
        Dependencies(model, lambda *a: calls.append(a) or "[]"),
        prereg=load("experiment.json")["prereg"],
    )
    assert result.trace["outcome_reason"] == "agent_max_steps"
    assert len(calls) == 1
    assert [s["kind"] for s in result.trace["spans"]] == ["llm", "tool"]
