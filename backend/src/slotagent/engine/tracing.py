"""① DB 없이 단계 기록을 모읍니다. trace 계약이 원본이며 관측 도구에는 의존하지 않습니다."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from slotagent.common import contracts
from slotagent.common.llm import ModelError, Reply, _tokens, add_cost, storage_cost

MAX_ARGS_DEPTH = 64


def storable_args(value) -> bool:
    """jsonb에 넣을 수 있는 인자인지. 재귀 없이 유한한 수와 중첩 깊이를 봅니다."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, float) and not math.isfinite(item):
            return False
        if isinstance(item, (dict, list)):
            if depth > MAX_ARGS_DEPTH:
                return False
            stack.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
    return True


@dataclass
class Recorder:
    seed: int
    spans: list[dict] = field(default_factory=list)
    cost: Decimal = Decimal(0)

    def plan(self, started_at: datetime) -> dict:
        """다음에 넣을 span의 번호와 시각. 쓰기 승인 검사에 예정 span으로 씁니다."""
        return {"seq": len(self.spans) + 1, "started_at": started_at.astimezone(UTC).isoformat()}

    def add(self, kind: str, name: str, started_at: datetime, duration_sec: float, **fields) -> dict:
        if fields.get("error") == "agent_invalid_tool_call" and not storable_args(fields.get("tool_args")):
            # 실행하지 않은 호출입니다. 모델 원문은 llm span의 tool_calls에 문자열로 남아 있습니다.
            fields["tool_args"] = {}
        span = {
            "seq": len(self.spans) + 1,
            "kind": kind,
            "name": name,
            "started_at": started_at.astimezone(UTC).isoformat(),
            "duration_sec": max(0, duration_sec),
            **fields,
        }
        self.spans.append(span)
        return span

    def model(self, name: str, started_at: datetime, reply: Reply) -> None:
        _tokens(reply.in_tokens)
        _tokens(reply.out_tokens)
        storage_cost(reply.cost_krw)
        self.cost = add_cost(self.cost, reply.cost_krw)
        self.add(
            "llm",
            name,
            started_at,
            reply.duration_sec,
            wait_sec=reply.wait_sec,
            in_tokens=reply.in_tokens,
            out_tokens=reply.out_tokens,
            output=reply.text,
            attributes={
                "model.resolved": reply.model,
                "model.seed": self.seed,
                "model.source": reply.source,
                "model.finish_reason": reply.finish_reason,
                "api_retries": reply.api_retries,
                "cost_krw": str(reply.cost_krw),
                "tool_calls": [c.as_dict() for c in reply.tool_calls],
            },
        )

    def model_error(self, name: str, started_at: datetime, error: ModelError) -> None:
        self.add(
            "llm",
            name,
            started_at,
            error.duration_sec,
            wait_sec=error.wait_sec,
            error=error.reason,
            attributes={"model.seed": self.seed, "api_retries": error.api_retries},
        )

    def finish(self, outcome: str, reason: str | None, final_answer: str | None, write_intents=()) -> dict:
        _tokens(sum(s.get("in_tokens", 0) for s in self.spans))
        _tokens(sum(s.get("out_tokens", 0) for s in self.spans))
        storage_cost(self.cost)
        usage = {
            "in_tokens": sum(s.get("in_tokens", 0) for s in self.spans),
            "out_tokens": sum(s.get("out_tokens", 0) for s in self.spans),
            "cost_krw": float(self.cost),
            "llm_sec": sum(s["duration_sec"] for s in self.spans if s["kind"] == "llm"),
            "tool_sec": sum(s["duration_sec"] for s in self.spans if s["kind"] == "tool"),
            "wait_sec": sum(s.get("wait_sec", 0) for s in self.spans),
            "api_retries": sum(s.get("attributes", {}).get("api_retries", 0) for s in self.spans),
        }
        # 도구 설명만의 토큰 수는 제공자가 분리해서 주지 않으므로 0으로 꾸며 넣지 않습니다.
        trace = {
            "schema_version": 1,
            "spans": self.spans,
            "write_intents": list(write_intents),
            "final_answer": final_answer,
            "run_outcome": outcome,
            "usage": usage,
        }
        if reason:
            trace["outcome_reason"] = reason
        return contracts.validate("trace", trace)
