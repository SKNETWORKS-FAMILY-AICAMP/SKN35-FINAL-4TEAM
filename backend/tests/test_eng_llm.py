"""① 외부 API 없이 모델 응답 정규화·재시도·시간 한도를 검증합니다."""

import copy
import json
import traceback
from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest
from conftest import load
from openai import RateLimitError

from slotagent.common.llm import (
    DEEPSEEK_BASE_URL,
    GEMINI_BASE_URL,
    FakeModel,
    ModelError,
    OpenAIModel,
    Price,
    ProviderModel,
    Reply,
    ToolCall,
    openai_tools,
)
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine.loop import Dependencies, run_agent


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Client:
    def __init__(self, responses, clock):
        self.responses = iter(responses)
        self.clock = clock
        self.requests = []
        self.options = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **options):
        self.options.append(options)
        return self

    def create(self, **request):
        self.requests.append(copy.deepcopy(request))
        self.clock.value += 0.1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def response():
    message = SimpleNamespace(
        content="이슈를 조회합니다",
        refusal=None,
        tool_calls=[
            SimpleNamespace(id="call_1", function=SimpleNamespace(name="list_issues", arguments='{"repo":"ops"}'))
        ],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
        model="resolved-model",
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )


def request():
    return dict(
        provider="openai",
        model="model",
        messages=[{"role": "user", "content": "조회"}],
        tools=[],
        temperature=0,
        seed=5,
        max_tokens=100,
        max_api_retries=1,
        timeout_sec=10,
        price=Price(Decimal("2"), Decimal("4")),
    )


def rate_limit():
    return RateLimitError(
        "비공개 오류 내용",
        response=httpx.Response(429, request=httpx.Request("POST", "https://unit.invalid")),
        body=None,
    )


def test_openai_response_and_usage_are_normalized():
    clock = Clock()
    client = Client([response()], clock)
    reply = OpenAIModel(client, clock=clock, sleep=clock.sleep).chat(**request())
    assert reply.tool_calls == (ToolCall("call_1", "list_issues", '{"repo":"ops"}'),)
    assert reply.message()["tool_calls"][0]["function"]["name"] == "list_issues"
    assert reply.model == "resolved-model"
    assert (reply.in_tokens, reply.out_tokens, reply.cost_krw) == (100, 20, Decimal("0.28"))
    assert reply.source == "openai"
    assert client.requests[0]["max_completion_tokens"] == 100
    assert client.options[0]["max_retries"] == 0


def test_retry_records_wait_separately_and_keeps_same_input():
    clock = Clock()
    client = Client([rate_limit(), response()], clock)
    reply = OpenAIModel(client, clock=clock, sleep=clock.sleep).chat(**request())
    assert reply.api_retries == 1
    assert reply.wait_sec == 1
    assert reply.duration_sec == pytest.approx(0.2)
    assert client.requests[0] == client.requests[1]
    assert client.options[1]["timeout"] < client.options[0]["timeout"]


def test_exhausted_rate_limit_has_safe_reason_and_measurements():
    clock = Clock()
    client = Client([rate_limit(), rate_limit()], clock)
    with pytest.raises(ModelError) as exc:
        OpenAIModel(client, clock=clock, sleep=clock.sleep).chat(**request())
    assert exc.value.reason == "llm_api_429"
    assert exc.value.api_retries == 1
    assert "비공개" not in str(exc.value)
    assert len(client.requests) == 2


def test_retry_wait_cannot_start_another_request_after_deadline():
    clock = Clock()
    client = Client([rate_limit(), response()], clock)
    with pytest.raises(ModelError, match="timeout_wall_clock"):
        OpenAIModel(client, clock=clock, sleep=clock.sleep).chat(**dict(request(), timeout_sec=0.5))
    assert len(client.requests) == 1


def test_other_provider_is_not_silently_sent_to_openai():
    clock = Clock()
    client = Client([], clock)
    with pytest.raises(NotImplementedError):
        OpenAIModel(client).chat(**dict(request(), provider="anthropic"))
    assert not client.requests


def test_fake_model_never_needs_a_key_and_does_not_modify_caller_messages(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake = FakeModel([Reply(text="끝", in_tokens=100, out_tokens=20)])
    args = request()
    reply = fake.chat(**args)
    args["messages"][0]["content"] = "바뀜"
    assert fake.requests[0]["messages"][0]["content"] == "조회"
    assert reply.cost_krw == Decimal("0.28")
    assert reply.source == "fake"


def test_provider_tools_do_not_include_internal_fields():
    tools = openai_tools(
        [
            {
                "name": "read",
                "description": "조회",
                "parameters": {"type": "object"},
                "capabilities": ["github.issues.read"],
                "access": "read",
                "origin": "mcp:github",
            }
        ]
    )
    assert set(tools[0]["function"]) == {"name", "description", "parameters"}


def test_absent_output_limit_uses_provider_default():
    clock = Clock()
    client = Client([response()], clock)
    OpenAIModel(client, clock=clock).chat(**dict(request(), max_tokens=None))
    assert "max_completion_tokens" not in client.requests[0]


PROVIDERS = ("openai", "google", "deepseek", "anthropic")
SECRET = "sdk-secret-DO-NOT-EXPOSE"


@pytest.fixture(autouse=True)
def no_real_sdk_clients(monkeypatch):
    """키가 로컬에 있어도 실제 SDK 클라이언트는 생성할 수 없게 막습니다."""

    def blocked(*args, **kwargs):
        pytest.fail("실제 SDK 클라이언트 생성 금지")

    monkeypatch.setattr(openai, "OpenAI", blocked)
    monkeypatch.setattr(anthropic, "Anthropic", blocked)


class ProviderClient(Client):
    def __init__(self, responses, clock):
        super().__init__(responses, clock)
        self.messages = SimpleNamespace(create=self.create)
        self.closed = False

    def close(self):
        self.closed = True


def provider_response(provider, *, arguments='{"repo":"ops"}', reason="tool_calls"):
    if provider != "anthropic":
        result = response()
        result.choices[0].message.tool_calls[0].function.arguments = arguments
        result.choices[0].finish_reason = reason
        if reason != "tool_calls":
            result.choices[0].message.tool_calls = []
        return result
    content = [SimpleNamespace(type="text", text="이슈를 조회합니다")]
    if reason == "tool_calls":
        content.append(SimpleNamespace(type="tool_use", id="call_1", name="list_issues", input=json.loads(arguments)))
    return SimpleNamespace(
        content=content,
        model="resolved-model",
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        stop_reason={"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}.get(reason, reason),
    )


def sdk_error(provider, status=None, *, timeout=False, connection=False):
    sdk = anthropic if provider == "anthropic" else openai
    req = httpx.Request("POST", "https://unit.invalid", headers={"authorization": SECRET})
    if timeout:
        return sdk.APITimeoutError(request=req)
    if connection:
        return sdk.APIConnectionError(message=SECRET, request=req)
    return sdk.APIStatusError(SECRET, response=httpx.Response(status, request=req), body={"error": SECRET})


def setup_provider(provider, responses):
    clock = Clock()
    client = ProviderClient(responses, clock)
    model = ProviderModel({provider: client}, clock=clock, sleep=clock.sleep)
    return model, client, clock, dict(request(), provider=provider, max_api_retries=2)


def assert_measurements(value, retries, wait, duration):
    assert value.api_retries == retries
    assert value.wait_sec == pytest.approx(wait)
    assert value.duration_sec == pytest.approx(duration)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_429_exhaustion_table(provider):
    model, client, clock, args = setup_provider(provider, [sdk_error(provider, 429) for _ in range(3)])
    with pytest.raises(ModelError, match="llm_api_429") as caught:
        model.chat(**args)
    assert_measurements(caught.value, 2, 3, 0.3)
    assert len(client.requests) == 3
    assert SECRET not in str(caught.value)
    assert caught.value.__suppress_context__
    assert SECRET not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("status", [500, 503, 529])
def test_provider_5xx_then_success_table(provider, status):
    model, client, clock, args = setup_provider(provider, [sdk_error(provider, status), provider_response(provider)])
    reply = model.chat(**args)
    assert_measurements(reply, 1, 1, 0.2)
    assert reply.source == provider
    assert reply.model == "resolved-model"
    assert (reply.in_tokens, reply.out_tokens, reply.cost_krw) == (100, 20, Decimal("0.28"))
    assert client.requests[0] == client.requests[1]
    assert all(options["max_retries"] == 0 for options in client.options)
    assert client.options[1]["timeout"] == pytest.approx(8.9)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_connection_error_retries_table(provider):
    model, client, clock, args = setup_provider(
        provider, [sdk_error(provider, connection=True), provider_response(provider)]
    )
    assert_measurements(model.chat(**args), 1, 1, 0.2)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_5xx_exhaustion(provider):
    model, client, clock, args = setup_provider(provider, [sdk_error(provider, 503) for _ in range(3)])
    with pytest.raises(ModelError, match="env_llm_api_5xx") as caught:
        model.chat(**args)
    assert_measurements(caught.value, 2, 3, 0.3)
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_wait_deadline_table(provider):
    model, client, clock, args = setup_provider(provider, [sdk_error(provider, 429)])
    with pytest.raises(ModelError, match="timeout_wall_clock") as caught:
        model.chat(**dict(args, timeout_sec=0.5))
    assert_measurements(caught.value, 1, 0.4, 0.1)
    assert len(client.requests) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_sdk_timeout_table(provider):
    model, client, clock, args = setup_provider(provider, [sdk_error(provider, timeout=True)])
    with pytest.raises(ModelError, match="timeout_wall_clock") as caught:
        model.chat(**args)
    assert_measurements(caught.value, 0, 0, 0.1)
    assert len(client.requests) == 1
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("status", [400, 401, 403])
def test_provider_permanent_4xx_table(provider, status):
    model, client, clock, args = setup_provider(provider, [sdk_error(provider, status)])
    with pytest.raises(ValueError) as caught:
        model.chat(**args)
    assert SECRET not in str(caught.value)
    assert caught.value.__suppress_context__
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert not hasattr(caught.value, "api_retries")
    assert clock.value == pytest.approx(0.1)
    assert len(client.requests) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("missing", ["usage", "input", "output"])
def test_provider_missing_usage_table(provider, missing):
    result = provider_response(provider)
    if missing == "usage":
        result.usage = None
    else:
        name = (
            ("input_tokens" if missing == "input" else "output_tokens")
            if provider == "anthropic"
            else ("prompt_tokens" if missing == "input" else "completion_tokens")
        )
        setattr(result.usage, name, None)
    model, client, clock, args = setup_provider(provider, [result])
    with pytest.raises(ValueError) as caught:
        model.chat(**args)
    assert SECRET not in str(caught.value)
    assert len(client.requests) == 1
    assert clock.value == pytest.approx(0.1)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_empty_object_arguments_table(provider):
    model, client, clock, args = setup_provider(provider, [provider_response(provider, arguments="{}")])
    reply = model.chat(**args)
    assert reply.tool_calls[0].arguments == "{}"
    assert_measurements(reply, 0, 0, 0.1)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_empty_string_arguments_table(provider):
    # Anthropic input=""는 JSON 문자열 '""'로 변환해 원래 값을 보존합니다.
    result = provider_response(provider, arguments='""' if provider == "anthropic" else "")
    model, client, clock, args = setup_provider(provider, [result])
    reply = model.chat(**args)
    assert reply.tool_calls[0].arguments == ('""' if provider == "anthropic" else "")
    assert_measurements(reply, 0, 0, 0.1)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_text_and_tools_table(provider):
    model, client, clock, args = setup_provider(provider, [provider_response(provider)])
    reply = model.chat(**args)
    assert reply.text == "이슈를 조회합니다"
    assert reply.tool_calls == (
        ToolCall("call_1", "list_issues", '{"repo": "ops"}' if provider == "anthropic" else '{"repo":"ops"}'),
    )
    assert_measurements(reply, 0, 0, 0.1)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_missing_key_table(provider, monkeypatch):
    key_names = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    monkeypatch.delenv(key_names[provider], raising=False)
    monkeypatch.setattr("slotagent.common.llm.dotenv_values", lambda *args: {})
    clock = Clock()
    with pytest.raises(ValueError, match=key_names[provider]):
        ProviderModel(clock=clock, sleep=clock.sleep).chat(**dict(request(), provider=provider))
    assert clock.value == 0


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_output_limit_table(provider):
    model, client, clock, args = setup_provider(provider, [provider_response(provider, reason="length")])
    reply = model.chat(**args)
    assert reply.finish_reason == "length"
    assert_measurements(reply, 0, 0, 0.1)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_refusal_mapping(provider):
    model, client, clock, args = setup_provider(provider, [provider_response(provider, reason="refusal")])
    assert model.chat(**args).finish_reason == "refusal"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_factory_uses_own_key_endpoint_and_no_sdk_retries(provider, monkeypatch):
    clock = Clock()
    client = ProviderClient([provider_response(provider)], clock)
    recorded = []

    def factory(**options):
        recorded.append(options)
        return client

    key_names = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    monkeypatch.setenv(key_names[provider], "mock-" + provider)
    monkeypatch.setattr(
        anthropic if provider == "anthropic" else openai, "Anthropic" if provider == "anthropic" else "OpenAI", factory
    )
    reply = ProviderModel(clock=clock, sleep=clock.sleep).chat(**dict(request(), provider=provider))
    assert reply.source == provider
    assert recorded[0]["api_key"] == "mock-" + provider
    assert recorded[0]["max_retries"] == 0
    if provider in {"google", "deepseek"}:
        assert recorded[0]["base_url"] == (GEMINI_BASE_URL if provider == "google" else DEEPSEEK_BASE_URL)
    assert client.closed


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_request_fields_and_tool_filter(provider):
    model, client, clock, args = setup_provider(provider, [provider_response(provider)])
    tool = {
        "type": "function",
        "internal": "secret",
        "function": {
            "name": "list_issues",
            "description": "조회",
            "parameters": {"type": "object"},
            "access": "read",
            "origin": "mcp:github",
            "capabilities": ["github.issues.read"],
        },
    }
    model.chat(**dict(args, tools=[tool]))
    sent = client.requests[0]
    if provider == "anthropic":
        assert set(sent["tools"][0]) == {"name", "description", "input_schema"}
    else:
        assert set(sent["tools"][0]) == {"type", "function"}
        assert set(sent["tools"][0]["function"]) == {"name", "description", "parameters"}
    assert ("seed" in sent) == (provider == "openai")
    assert sent["max_completion_tokens" if provider == "openai" else "max_tokens"] == 100
    assert "access" in tool["function"]


@pytest.mark.parametrize("provider", ["openai", "google", "deepseek"])
def test_compatible_provider_omits_unspecified_output_limit(provider):
    model, client, clock, args = setup_provider(provider, [provider_response(provider)])
    model.chat(**dict(args, max_tokens=None))
    assert "max_tokens" not in client.requests[0]
    assert "max_completion_tokens" not in client.requests[0]


def test_anthropic_requires_explicit_output_limit():
    model, client, clock, args = setup_provider("anthropic", [])
    with pytest.raises(ValueError, match="max_tokens"):
        model.chat(**dict(args, max_tokens=None))
    assert not client.requests
    assert clock.value == 0


def test_unknown_provider_is_rejected_without_dispatch():
    with pytest.raises(NotImplementedError):
        ProviderModel().chat(**dict(request(), provider="unknown"))


def loop_snapshot(provider):
    data = load("slot_and_candidates.json")
    snap = merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][0])
    snap["model"]["provider"] = provider
    snap["runtime"]["max_output_tokens"] = 100
    return snap


def test_anthropic_message_conversion_round_trip_with_parallel_tools():
    first = provider_response("anthropic", arguments='{"owner":"acme","repo":"ops-service"}')
    first.content.append(
        SimpleNamespace(
            type="tool_use", id="call_2", name="list_issues", input={"owner": "acme", "repo": "ops-service"}
        )
    )
    second = provider_response("anthropic", reason="stop")
    model, client, clock, args = setup_provider("anthropic", [first, second])
    snap = loop_snapshot("anthropic")
    calls = []

    def tool(*values):
        calls.append(values)
        return "[]"

    result = run_agent(
        snap, "조회", 5, Dependencies(model, tool, clock=clock), prereg=load("experiment.json")["prereg"]
    )
    assert result.outcome == "completed"
    assert len(calls) == 2
    sent = client.requests[1]
    assert sent["system"] == snap["instructions"]
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]
    uses = [block for block in sent["messages"][1]["content"] if block["type"] == "tool_use"]
    results = sent["messages"][2]["content"]
    assert [b["id"] for b in uses] == [b["tool_use_id"] for b in results] == ["call_1", "call_2"]
    assert all(b["input"] == {"owner": "acme", "repo": "ops-service"} for b in uses)
    assert all(b["type"] == "tool_result" and b["content"] == "[]" for b in results)
    assert sent["messages"][1]["content"][0]["text"] == "이슈를 조회합니다"


@pytest.mark.parametrize("value", [[], [1], "", "bad", 4, False, None])
def test_anthropic_non_object_arguments_are_reported_by_loop_and_model_can_recover(value):
    first = provider_response("anthropic", arguments=json.dumps(value))
    second = provider_response("anthropic", reason="stop")
    model, client, clock, args = setup_provider("anthropic", [first, second])
    executed = []
    result = run_agent(
        loop_snapshot("anthropic"),
        "조회",
        5,
        Dependencies(model, lambda *args: executed.append(args), clock=clock),
        prereg=load("experiment.json")["prereg"],
    )
    assert result.outcome == "completed"
    assert not executed
    assert result.trace["spans"][1]["error"] == "agent_invalid_tool_call"
    assert len(client.requests) == 2
    feedback = client.requests[1]["messages"][-1]["content"][0]
    assert feedback["type"] == "text"
    assert "agent_invalid_tool_call" in feedback["text"]
    original_call = json.loads(client.requests[1]["messages"][-2]["content"][-1]["text"])["invalid_tool_call"]
    assert json.loads(original_call["function"]["arguments"]) == value


def test_gemini_empty_tool_ids_are_unique_and_preserved_in_next_request():
    first = provider_response("google", arguments='{"owner":"acme","repo":"ops-service"}')
    template = first.choices[0].message.tool_calls[0]
    template.id = ""
    first.choices[0].message.tool_calls.append(copy.deepcopy(template))
    first.choices[0].message.tool_calls[1].id = None
    model, client, clock, args = setup_provider("google", [first, provider_response("google", reason="stop")])
    result = run_agent(
        loop_snapshot("google"),
        "조회",
        5,
        Dependencies(model, lambda *args: "[]", clock=clock),
        prereg=load("experiment.json")["prereg"],
    )
    assert result.outcome == "completed"
    messages = client.requests[1]["messages"]
    assistant_ids = [c["id"] for c in messages[-3]["tool_calls"]]
    result_ids = [m["tool_call_id"] for m in messages[-2:]]
    assert all(assistant_ids)
    assert len(set(assistant_ids)) == 2
    assert assistant_ids == result_ids


def test_gemini_generated_id_avoids_existing_and_current_ids(monkeypatch):
    result = provider_response("google")
    template = result.choices[0].message.tool_calls[0]
    template.id = "call_current"
    empty = copy.deepcopy(template)
    empty.id = ""
    result.choices[0].message.tool_calls.append(empty)
    values = iter(["history", "current", "fresh"])
    monkeypatch.setattr("slotagent.common.llm.uuid4", lambda: SimpleNamespace(hex=next(values)))
    model, client, clock, args = setup_provider("google", [result])
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [ToolCall("call_history", "read", "{}").as_dict()]}
    ]
    reply = model.chat(**dict(args, messages=messages))
    assert [c.id for c in reply.tool_calls] == ["call_current", "call_fresh"]
    assert_measurements(reply, 0, 0, 0.1)


@pytest.mark.parametrize("missing", ["absent", "whitespace"])
def test_gemini_omitted_or_whitespace_id_is_filled(missing):
    result = provider_response("google")
    call = result.choices[0].message.tool_calls[0]
    if missing == "absent":
        del call.id
    else:
        call.id = "   "
    model, client, clock, args = setup_provider("google", [result])
    reply = model.chat(**args)
    assert reply.tool_calls[0].id.strip()
    assert_measurements(reply, 0, 0, 0.1)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_no_time_remaining_prevents_request(provider):
    model, client, clock, args = setup_provider(provider, [])
    with pytest.raises(ModelError, match="timeout_wall_clock") as caught:
        model.chat(**dict(args, timeout_sec=0))
    assert_measurements(caught.value, 0, 0, 0)
    assert not client.requests


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_success_after_deadline_is_timeout(provider):
    model, client, clock, args = setup_provider(provider, [provider_response(provider)])
    with pytest.raises(ModelError, match="timeout_wall_clock") as caught:
        model.chat(**dict(args, timeout_sec=0.05))
    assert_measurements(caught.value, 0, 0, 0.1)
    assert len(client.requests) == 1


def test_anthropic_cache_tokens_are_counted_with_caller_price():
    result = provider_response("anthropic")
    result.usage.cache_creation_input_tokens = 10
    result.usage.cache_read_input_tokens = 20
    model, client, clock, args = setup_provider("anthropic", [result])
    reply = model.chat(**args)
    assert reply.in_tokens == 130
    assert reply.cost_krw == Decimal("0.34")


def test_anthropic_mixed_invalid_and_valid_tools_keep_results_before_text():
    first = provider_response("anthropic", arguments="[]")
    first.content.append(
        SimpleNamespace(type="tool_use", id="valid", name="list_issues", input={"owner": "acme", "repo": "ops-service"})
    )
    model, client, clock, args = setup_provider("anthropic", [first, provider_response("anthropic", reason="stop")])
    executed = []

    def tool(*values):
        executed.append(values)
        return "[]"

    result = run_agent(
        loop_snapshot("anthropic"),
        "조회",
        5,
        Dependencies(model, tool, clock=clock),
        prereg=load("experiment.json")["prereg"],
    )
    assert result.outcome == "completed"
    assert len(executed) == 1
    feedback = client.requests[1]["messages"][-1]["content"]
    assert feedback[0] == {"type": "tool_result", "tool_use_id": "valid", "content": "[]"}
    assert feedback[1]["type"] == "text"
    assert "agent_invalid_tool_call" in feedback[1]["text"]
