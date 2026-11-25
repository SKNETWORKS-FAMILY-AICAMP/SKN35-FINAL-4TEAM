"""① DB를 모르는 실행 코어. 모델·읽기 도구·시계·중단 신호를 외부에서 주입합니다.

쓰기와 확인 도구는 write_proxy가 밖으로 보내지 않고 처리합니다. 도구 검색 후보는 검색으로 찾은 도구만 모델에 보입니다.
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
from slotagent.common.llm import ChatModel, ModelError, Price, openai_tools, storage_text
from slotagent.engine import fixed_tools
from slotagent.engine.tool_search import SEARCH, SEARCH_TOOL, ToolSearch
from slotagent.engine.tracing import Recorder, storable_args
from slotagent.engine.write_proxy import InvalidCall, WriteProxy, fill_defaults


class RunCancelled(RuntimeError):
    """취소·임대 상실은 후보 실패로 채점하지 않고 호출자에게 돌려줍니다."""


class ToolEnvironmentError(RuntimeError):
    def __init__(self, reason: str = "env_mcp_server_down"):
        super().__init__(reason)
        self.reason = reason


class ToolExecutionError(Exception):
    """유효한 도구 실패 응답. 원문을 기록·피드백하고 대화는 계속합니다."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


@dataclass
class Dependencies:
    model: ChatModel
    call_tool: Callable[[str, dict, float], str]
    price: Price = field(default_factory=Price)
    cancelled: Callable[[], bool] = lambda: False
    clock: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    on_model_span: Callable[[dict], None] = lambda span: None


@dataclass(frozen=True)
class RunResult:
    trace: dict

    @property
    def outcome(self) -> str:
        return self.trace["run_outcome"]


def run_agent(
    snap: dict,
    task_prompt: str,
    seed: int,
    deps: Dependencies,
    *,
    prereg: dict,
    confirmation: dict | None = None,
    write_scenario: dict | None = None,
) -> RunResult:
    """설정·정답 없는 문항만 받아 trace를 만듭니다. 입력 dict는 변경하지 않습니다.

    confirmation(P-05 고정 답)과 write_scenario는 엔진 전용이며 모델 메시지에 넣지 않습니다.
    """
    snap = copy.deepcopy(contracts.validate("config_snapshot", snap))
    search = ToolSearch(snap) if snap.get("tool_search") else None
    proxy = WriteProxy(snap, confirmation, write_scenario)
    runtime = snap["runtime"]
    started = deps.clock()
    deadline = started + runtime["timeout_sec"]
    record = Recorder(seed)
    messages = [{"role": "system", "content": snap["instructions"]}, {"role": "user", "content": task_prompt}]
    every = [*snap["tools"], *proxy.tools, *([SEARCH_TOOL] if search else [])]
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
        return RunResult(record.finish(checks.run_outcome_for(reason, prereg), reason, final, proxy.intents))

    try:
        for _ in range(runtime["max_steps"]):
            if steps >= runtime["max_steps"]:
                return finish("agent_max_steps")
            seconds = remaining()
            steps += 1
            at = deps.now()
            # 이번 요청에 보여 준 도구만 부를 수 있습니다. 같은 응답에서 검색한 도구는 다음 요청부터입니다.
            definitions = {t["name"]: t for t in every if search is None or t["name"] not in search.hidden}
            tools = openai_tools(list(definitions.values()))
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
            # 소유권·취소 검사보다 먼저, 이미 받은 응답의 비용을 호출자에게 넘깁니다.
            deps.on_model_span(copy.deepcopy(record.spans[-1]))
            storage_text(reply.message())
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
                args, error, result, reason, attributes = {}, None, "", None, {}
                definition = definitions.get(call.name)
                try:
                    args = json.loads(call.arguments)
                    # 저장할 수 없는 인자(NaN·Infinity, 너무 깊은 중첩)는 읽기 도구라도 실행하지 않습니다.
                    if not isinstance(args, dict) or definition is None or not storable_args(args):
                        raise ValueError
                    if list(Draft202012Validator(definition["parameters"]).iter_errors(args)):
                        raise ValueError
                    if proxy.handles(call.name):
                        args = proxy.normalize(call.name, args)
                except InvalidCall:
                    args, error = {}, "agent_invalid_tool_call"
                    result = json.dumps({"error": error}, ensure_ascii=False)
                except (ValueError, TypeError, RecursionError):
                    if not isinstance(args, dict):
                        args = {}
                    error = "agent_invalid_tool_call"
                    result = json.dumps({"error": error}, ensure_ascii=False)
                storage_text(args)
                if error is None:
                    if search is not None and call.name == SEARCH:
                        answer, attributes = search.run(args)
                        result = json.dumps(answer, ensure_ascii=False)
                    elif proxy.handles(call.name):
                        result, attributes = proxy.run(call.name, args, record.plan(at), record.spans)
                    elif fixed_tools.is_fixed_read(definition):
                        attributes = {"origin": "custom", "fixed_response": True}
                        result = fixed_tools.match(definition, fill_defaults(definition["parameters"], args))
                        if result is None:
                            error, result = "tool_error", fixed_tools.no_match()
                    else:
                        try:
                            result = deps.call_tool(call.name, args, seconds)
                            if not isinstance(result, str):
                                raise TypeError("도구는 모델에 전달할 문자열을 반환해야 합니다.")
                        except ToolExecutionError as exc:
                            error, result = "tool_error", exc.text
                        except ToolEnvironmentError as exc:
                            error = reason = exc.reason
                            result = json.dumps({"error": error}, ensure_ascii=False)
                        except TimeoutError:
                            error = reason = "timeout_wall_clock"
                            result = json.dumps({"error": error}, ensure_ascii=False)
                storage_text(result)
                record.add(
                    "tool",
                    call.name,
                    at,
                    deps.clock() - before,
                    tool_args=args,
                    tool_result=result,
                    **({"error": error} if error else {}),
                    **({"attributes": attributes} if attributes else {}),
                )
                if reason:
                    return finish(reason)
                remaining()
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        return finish("agent_max_steps")
    except TimeoutError:
        return finish("timeout_wall_clock")
