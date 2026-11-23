"""① 모델 호출 공통 경로. DB를 직접 알지 않고 정규화된 사용량·비용을 반환합니다.

워커·판정기·chatbot이 반환된 호출 결과를 각자의 DB 문맥에 한 번만 저장합니다.
ProviderModel은 네 회사를 선택하며 OpenAIModel은 기존 OpenAI 전용 인터페이스를 유지합니다.
SDK 자동 재시도를 끄고 공용 루프에서 시간·횟수를 제어합니다. 다른 모델로 자동 전환하지 않습니다.
"""

from __future__ import annotations

import copy
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from dotenv import dotenv_values


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str

    def as_dict(self) -> dict:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": self.arguments}}


@dataclass(frozen=True)
class Price:
    in_per_1k_krw: Decimal = Decimal(0)
    out_per_1k_krw: Decimal = Decimal(0)

    def __post_init__(self):
        if not self.in_per_1k_krw.is_finite() or not self.out_per_1k_krw.is_finite():
            raise ValueError("가격은 유한한 값이어야 합니다.")
        if min(self.in_per_1k_krw, self.out_per_1k_krw) < 0:
            raise ValueError("가격은 음수일 수 없습니다.")

    def calculate(self, in_tokens: int, out_tokens: int) -> Decimal:
        return (in_tokens * self.in_per_1k_krw + out_tokens * self.out_per_1k_krw) / 1000


@dataclass(frozen=True)
class Reply:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    in_tokens: int = 0
    out_tokens: int = 0
    model: str = "fake"
    finish_reason: str = "stop"
    duration_sec: float = 0
    wait_sec: float = 0
    api_retries: int = 0
    cost_krw: Decimal = Decimal(0)
    source: str = "fake"

    def message(self) -> dict:
        message: dict[str, Any] = {"role": "assistant", "content": self.text or None}
        if self.tool_calls:
            message["tool_calls"] = [call.as_dict() for call in self.tool_calls]
        return message


class ModelError(RuntimeError):
    """기존 이유 코드와 측정값만 노출하고 SDK의 원문 오류는 포함하지 않습니다."""

    def __init__(self, reason: str, *, duration_sec: float = 0, wait_sec: float = 0, api_retries: int = 0):
        super().__init__(reason)
        self.reason = reason
        self.duration_sec = duration_sec
        self.wait_sec = wait_sec
        self.api_retries = api_retries


class ChatModel(Protocol):
    is_fake: bool

    def chat(
        self,
        *,
        provider: str,
        model: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float,
        seed: int,
        max_tokens: int | None,
        max_api_retries: int,
        timeout_sec: float,
        price: Price,
    ) -> Reply: ...


# 공식 연결 주소: https://aistudio.google.com/docs/openai?hl=ko · https://api-docs.deepseek.com/
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def _with_retries(send, *, errors, timeouts, max_api_retries, timeout_sec, clock, sleep):
    """네 회사가 공유하는 유일한 재시도 루프. 대기와 요청 시간을 나눠 기록합니다."""
    started, wait, retries = clock(), 0.0, 0

    def measurements():
        return dict(duration_sec=max(0, clock() - started - wait), wait_sec=wait, api_retries=retries)

    while True:
        remaining = timeout_sec - (clock() - started)
        if remaining <= 0:
            raise ModelError("timeout_wall_clock", **measurements())
        try:
            reply = send(remaining)
        except errors as exc:
            status = getattr(exc, "status_code", None)
            if isinstance(exc, timeouts):
                reason, retryable = "timeout_wall_clock", False
            elif status == 429:
                reason, retryable = "llm_api_429", True
            elif status is not None and status < 500:
                raise ValueError("모델 API 인증 또는 요청 설정을 확인하세요.") from None
            else:
                reason, retryable = "env_llm_api_5xx", True
            if not retryable or retries >= max_api_retries:
                raise ModelError(reason, **measurements()) from None
            remaining = timeout_sec - (clock() - started)
            delay = min(2**retries, max(0, remaining))
            before = clock()
            sleep(delay)
            wait += max(0, clock() - before)
            retries += 1
        else:
            # 호출이 제한 시간을 넘겨 반환한 경우에도 뒤늦은 성공으로 처리하지 않습니다.
            if clock() - started >= timeout_sec:
                raise ModelError("timeout_wall_clock", **measurements())
            return replace(reply, **measurements())


def _api_key(provider):
    name = _KEY_NAMES[provider]
    key = os.environ.get(name)
    if key is None:
        key = dotenv_values(Path(__file__).resolve().parents[4] / ".env").get(name)
    if not key or not key.strip():
        raise ValueError(f"{name}가 없습니다. 실제 호출을 시작하지 않았습니다.")
    return key


def _tokens(value):
    if type(value) is not int or value < 0:
        raise ValueError("모델 API 사용량이 없거나 올바르지 않아 비용을 확정할 수 없습니다.")
    return value


def _provider_tools(tools, provider):
    """이미 OpenAI 모양인 도구에서도 내부 속성을 제거합니다."""
    definitions = [t["function"] if t.get("type") == "function" else t for t in tools]
    if provider == "anthropic":
        return anthropic_tools(definitions)
    return openai_tools(definitions)


def anthropic_tools(tools: list[dict]) -> list[dict]:
    """이름·설명·입력 스키마만 Anthropic 도구 정의로 변환합니다."""
    return [
        {"name": t["name"], "description": t["description"], "input_schema": copy.deepcopy(t["parameters"])}
        for t in tools
    ]


def anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """system 분리와 tool_use/tool_result 변환. 잘못된 호출은 글로 보존해 수정 기회를 줍니다."""
    system, converted, invalid_ids = [], [], set()

    def append(role, blocks):
        if not blocks:
            return
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})
        if role == "user":
            # 정상 호출과 잘못된 호출이 섞여도 API가 요구하는 tool_result 선행 순서를 지킵니다.
            converted[-1]["content"].sort(key=lambda block: block["type"] != "tool_result")

    for message in messages:
        role, content = message["role"], message.get("content")
        if role == "system":
            system.append(content or "")
        elif role == "tool":
            call_id = message["tool_call_id"]
            if call_id in invalid_ids:
                # input 객체가 아닌 tool_use는 API로 재전송할 수 없습니다. 원문과 오류는 글로 보존합니다.
                append(
                    "user",
                    [
                        {
                            "type": "text",
                            "text": json.dumps({"tool_call_id": call_id, "tool_result": content}, ensure_ascii=False),
                        }
                    ],
                )
            else:
                append("user", [{"type": "tool_result", "tool_use_id": call_id, "content": content or ""}])
        elif role in {"user", "assistant"}:
            blocks = [{"type": "text", "text": content}] if content else []
            for call in message.get("tool_calls", []):
                function = call["function"]
                try:
                    args = json.loads(function["arguments"])
                except (ValueError, TypeError):
                    args = None
                if isinstance(args, dict):
                    blocks.append({"type": "tool_use", "id": call["id"], "name": function["name"], "input": args})
                else:
                    invalid_ids.add(call["id"])
                    blocks.append({"type": "text", "text": json.dumps({"invalid_tool_call": call}, ensure_ascii=False)})
            append(role, blocks)
        else:
            raise ValueError("Anthropic 메시지 역할을 확인하세요.")
    return "\n\n".join(system), converted


def _openai_reply(response, provider, price, messages):
    try:
        choice, usage = response.choices[0], response.usage
        msg = choice.message
        in_tokens, out_tokens = _tokens(usage.prompt_tokens), _tokens(usage.completion_tokens)
        raw_calls = msg.tool_calls or []
        # Gemini의 빈 ID만 보완합니다. 받은 중복 ID는 루프의 기존 검사에 맡깁니다.
        used = {getattr(c, "id", None) for c in raw_calls if getattr(c, "id", None)}
        used.update(c["id"] for m in messages for c in m.get("tool_calls", []) if c.get("id"))
        used.update(m["tool_call_id"] for m in messages if m.get("tool_call_id"))
        calls = []
        for call in raw_calls:
            call_id = getattr(call, "id", None)
            if provider == "google" and (not call_id or isinstance(call_id, str) and not call_id.strip()):
                call_id = "call_" + uuid4().hex
                while call_id in used:
                    call_id = "call_" + uuid4().hex
                used.add(call_id)
            arguments = call.function.arguments
            calls.append(ToolCall(call_id, call.function.name, arguments if arguments is not None else ""))
        return Reply(
            text=msg.content or "",
            tool_calls=tuple(calls),
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            model=response.model,
            finish_reason="refusal" if getattr(msg, "refusal", None) else choice.finish_reason,
            cost_krw=price.calculate(in_tokens, out_tokens),
            source=provider,
        )
    except (AttributeError, IndexError, TypeError):
        raise ValueError("모델 API 응답 또는 사용량이 올바르지 않습니다.") from None


def _anthropic_reply(response, price):
    try:
        usage = response.usage
        in_tokens = _tokens(usage.input_tokens)
        for name in ("cache_creation_input_tokens", "cache_read_input_tokens"):
            in_tokens += _tokens(getattr(usage, name, None) or 0)
        out_tokens = _tokens(usage.output_tokens)
        calls, text = [], []
        for block in response.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                # 목록·문자열·null도 원래 JSON 값 그대로 돌려 루프가 잘못된 호출로 처리하게 합니다.
                calls.append(ToolCall(block.id, block.name, json.dumps(block.input, ensure_ascii=False)))
        reasons = {"end_turn": "stop", "tool_use": "tool_calls", "max_tokens": "length", "refusal": "refusal"}
        return Reply(
            text="".join(text),
            tool_calls=tuple(calls),
            in_tokens=in_tokens,
            out_tokens=out_tokens,
            model=response.model,
            finish_reason=reasons.get(response.stop_reason, response.stop_reason),
            cost_krw=price.calculate(in_tokens, out_tokens),
            source="anthropic",
        )
    except (AttributeError, TypeError):
        raise ValueError("모델 API 응답 또는 사용량이 올바르지 않습니다.") from None


class ProviderModel:
    """provider로 실제 회사를 고릅니다. clients 주입은 SDK 모의 검증에 사용합니다."""

    is_fake = False

    def __init__(
        self, clients=None, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep
    ):
        self.clients = dict(clients or {})
        self.clock, self.sleep = clock, sleep

    def chat(
        self, *, provider, model, messages, tools, temperature, seed, max_tokens, max_api_retries, timeout_sec, price
    ):
        if provider not in _KEY_NAMES:
            raise NotImplementedError("지원하지 않는 모델 공급자입니다.")
        if timeout_sec <= 0:
            raise ModelError("timeout_wall_clock")
        if provider == "anthropic" and max_tokens is None:
            raise ValueError("Anthropic 호출에는 max_tokens를 명시해야 합니다.")
        request = {"model": model, "temperature": temperature}
        if provider == "anthropic":
            import anthropic

            errors = (anthropic.APIStatusError, anthropic.APIConnectionError)
            timeouts = (anthropic.APITimeoutError,)
            factory = anthropic.Anthropic
            system, converted = anthropic_messages(messages)
            request.update(messages=converted, max_tokens=max_tokens)
            if system:
                request["system"] = system
        else:
            import openai

            errors = (openai.APIStatusError, openai.APIConnectionError)
            timeouts = (openai.APITimeoutError,)
            factory = openai.OpenAI
            request["messages"] = copy.deepcopy(messages)
            # 호환 API의 공식 인자 목록에 seed가 없으므로 OpenAI에만 전달합니다.
            if provider == "openai":
                request["seed"] = seed
            if max_tokens is not None:
                request["max_completion_tokens" if provider == "openai" else "max_tokens"] = max_tokens
        if tools:
            request["tools"] = _provider_tools(tools, provider)
        client = self.clients.get(provider)
        owned = client is None
        if owned:
            options = {"api_key": _api_key(provider), "max_retries": 0}
            if provider in {"google", "deepseek"}:
                options["base_url"] = GEMINI_BASE_URL if provider == "google" else DEEPSEEK_BASE_URL
            client = factory(**options)
        try:

            def send(remaining):
                configured = client.with_options(max_retries=0, timeout=remaining)
                if provider == "anthropic":
                    return _anthropic_reply(configured.messages.create(**copy.deepcopy(request)), price)
                response = configured.chat.completions.create(**copy.deepcopy(request))
                return _openai_reply(response, provider, price, messages)

            return _with_retries(
                send,
                errors=errors,
                timeouts=timeouts,
                max_api_retries=max_api_retries,
                timeout_sec=timeout_sec,
                clock=self.clock,
                sleep=self.sleep,
            )
        finally:
            if owned:
                client.close()


class OpenAIModel(ProviderModel):
    """기존 OpenAI 전용 클래스. 다른 회사를 조용히 OpenAI로 보내지 않습니다."""

    def __init__(
        self, client=None, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep
    ):
        super().__init__({"openai": client} if client is not None else None, clock=clock, sleep=sleep)
        self.client = client

    def chat(
        self, *, provider, model, messages, tools, temperature, seed, max_tokens, max_api_retries, timeout_sec, price
    ):
        if provider != "openai":
            raise NotImplementedError("OpenAIModel은 OpenAI 전용입니다. 다른 회사는 ProviderModel을 사용하세요.")
        return super().chat(
            provider=provider,
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens,
            max_api_retries=max_api_retries,
            timeout_sec=timeout_sec,
            price=price,
        )


@dataclass
class FakeModel:
    """정해 둔 응답을 차례로 반환하며 외부 API에 연결하지 않습니다."""

    replies: Sequence[Reply | ModelError]
    is_fake: bool = field(default=True, init=False)
    requests: list[dict] = field(default_factory=list, init=False)

    def chat(self, **request) -> Reply:
        self.requests.append(copy.deepcopy({k: v for k, v in request.items() if k != "price"}))
        index = len(self.requests) - 1
        if index >= len(self.replies):
            raise RuntimeError("가짜 모델에 준비한 응답이 부족합니다.")
        reply = self.replies[index]
        if isinstance(reply, ModelError):
            raise reply
        return Reply(
            **{
                **reply.__dict__,
                "cost_krw": request["price"].calculate(reply.in_tokens, reply.out_tokens),
                "source": "fake",
            }
        )


def openai_tools(tools: list[dict]) -> list[dict]:
    """공급자에 필요한 필드만 전달하고 정답·권한 같은 내부 속성은 보내지 않습니다."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": copy.deepcopy(t["parameters"]),
            },
        }
        for t in tools
    ]
