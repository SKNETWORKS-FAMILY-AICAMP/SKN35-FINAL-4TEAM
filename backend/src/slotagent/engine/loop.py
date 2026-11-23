"""① DB를 모르는 실행 코어. 모델·읽기 도구·시계·중단 신호를 외부에서 주입합니다.

첫 단계는 읽기 실행만 지원합니다. 쓰기·확인·검색을 처리한 척하지 않고 연결 전에는 명시적으로 막습니다.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from jsonschema import Draft202012Validator

from slotagent.common import checks, contracts
from slotagent.common.llm import ChatModel, ModelError, Price, openai_tools
from slotagent.engine.tracing import Recorder


class RunCancelled(RuntimeError):
    """취소·임대 상실은 후보 실패로 채점하지 않고 호출자에게 돌려줍니다."""


class ToolEnvironmentError(RuntimeError):
    def __init__(self, reason: str = "env_mcp_server_down"):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Dependencies:
    model: ChatModel
    call_tool: Callable[[str, dict, float], str]
    price: Price = field(default_factory=Price)
    cancelled: Callable[[], bool] = lambda: False
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


@dataclass(frozen=True)
class RunResult:
    trace: dict

    @property
    def outcome(self) -> str:
        return self.trace["run_outcome"]


def run_agent(snap: dict, task_prompt: str, seed: int, deps: Dependencies, *, prereg: dict) -> RunResult:
    """설정·정답 없는 문항만 받아 trace를 만듭니다. 입력 dict는 변경하지 않습니다."""
    snap = copy.deepcopy(contracts.validate("config_snapshot", snap))
    if snap.get("tool_search"):
        raise NotImplementedError("도구 검색 실행은 다음 단계입니다.")
    runtime = snap["runtime"]
    started = deps.clock()
    deadline = started + runtime["timeout_sec"]
    record = Recorder(seed)
    messages = [{"role": "system", "content": snap["instructions"]}, {"role": "user", "content": task_prompt}]
    definitions = {t["name"]: t for t in snap["tools"]}
    tools = openai_tools(snap["tools"])
    final = None
    steps = 0

    def remaining() -> float:
        if deps.cancelled():
            raise RunCancelled("풀이가 취소됐거나 현재 시도의 소유권을 잃었습니다.")
        seconds = deadline - deps.clock()
        if seconds <= 0:
            raise TimeoutError
        return seconds

    def finish(reason: str | None = None) -> RunResult:
        return RunResult(record.finish(checks.run_outcome_for(reason, prereg), reason, final))

    try:
        for _ in range(runtime["max_steps"]):
            if steps >= runtime["max_steps"]:
                return finish("agent_max_steps")
            seconds = remaining()
            steps += 1
            at = deps.now()
            try:
                reply = deps.model.chat(
                    provider=snap["model"]["provider"],
                    model=snap["model"]["name"],
                    messages=copy.deepcopy(messages),
                    tools=tools,
                    temperature=snap["model"]["temperature"],
                    seed=seed,
                    max_tokens=runtime.get("max_output_tokens"),
                    max_api_retries=runtime.get("max_api_retries", 0),
                    timeout_sec=seconds,
                    price=deps.price,
                )
            except ModelError as exc:
                record.model_error(snap["model"]["name"], at, exc)
                return finish(exc.reason)
            record.model(snap["model"]["name"], at, reply)
            remaining()
            messages.append(reply.message())
            if reply.finish_reason == "refusal":
                return finish("agent_llm_refused")
            if not reply.tool_calls:
                final = reply.text
                return finish()
            if len({c.id for c in reply.tool_calls}) != len(reply.tool_calls):
                return finish("agent_invalid_tool_call")
            for call in reply.tool_calls:
                if steps >= runtime["max_steps"]:
                    return finish("agent_max_steps")
                seconds = remaining()
                steps += 1
                at, before = deps.now(), deps.clock()
                args, error, result, reason = {}, None, "", None
                definition = definitions.get(call.name)
                try:
                    args = json.loads(call.arguments)
                    if not isinstance(args, dict) or definition is None:
                        raise ValueError
                    if list(Draft202012Validator(definition["parameters"]).iter_errors(args)):
                        raise ValueError
                except (ValueError, TypeError):
                    if not isinstance(args, dict):
                        args = {}
                    error = "agent_invalid_tool_call"
                    result = json.dumps({"error": error}, ensure_ascii=False)
                if error is None:
                    if definition["access"] != "read" or call.name in snap["write_tools"]:
                        raise NotImplementedError("쓰기 프록시는 아직 연결하지 않았습니다.")
                    elif definition["origin"] == "builtin":
                        raise NotImplementedError("확인 도구 연결은 다음 단계입니다.")
                    else:
                        try:
                            result = deps.call_tool(call.name, args, seconds)
                            if not isinstance(result, str):
                                raise TypeError("도구는 모델에 전달할 문자열을 반환해야 합니다.")
                        except ToolEnvironmentError as exc:
                            error = reason = exc.reason
                            result = json.dumps({"error": error}, ensure_ascii=False)
                        except TimeoutError:
                            error = reason = "timeout_wall_clock"
                            result = json.dumps({"error": error}, ensure_ascii=False)
                record.add(
                    "tool",
                    call.name,
                    at,
                    deps.clock() - before,
                    tool_args=args,
                    tool_result=result,
                    **({"error": error} if error else {}),
                )
                if reason:
                    return finish(reason)
                remaining()
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        return finish("agent_max_steps")
    except TimeoutError:
        return finish("timeout_wall_clock")
