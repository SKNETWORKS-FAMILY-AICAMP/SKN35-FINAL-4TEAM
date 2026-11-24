"""P-05 계약 초안의 순수 함수. ① 확인 도구·write_proxy에서 호출할 비교 규칙."""

from __future__ import annotations

import json

from slotagent.common import contracts
from slotagent.common.hashing import canonical_json


def same_action(left: dict, right: dict) -> bool:
    """공통 canonical_json으로 전체 인자를 비교. 부분 일치·문자열 정규화는 하지 않는다."""
    for action in (left, right):
        contracts.validate("confirmation", action, part="action")
    return canonical_json(left) == canonical_json(right)


def argument_values(arguments):
    """키를 제외한 JSON 문자열 값. 부분 문자열이나 키 자체는 대상에 포함하지 않는다."""
    if isinstance(arguments, str):
        yield arguments
    elif isinstance(arguments, dict):
        for value in arguments.values():
            yield from argument_values(value)
    elif isinstance(arguments, list):
        for value in arguments:
            yield from argument_values(value)


def fixed_response(policy: dict | None, request: dict, response_index: int,
                   tool_capabilities: dict[str, list[str]]) -> dict:
    """엔진이 소유한 0-based 호출 인덱스로 고정 응답 선택. 실패해도 인덱스는 소비한다."""
    if policy is None:
        policy = {"schema_version": 1, "responses": []}
    contracts.validate("confirmation", policy, part="policy")
    contracts.validate("confirmation", request, part="request")
    if type(response_index) is not int or response_index < 0:
        raise ValueError("response_index must be a nonnegative integer")
    result = {"schema_version": 1, "decision": "no_response", "action": request["action"],
              "response_index": response_index}
    if response_index < len(policy["responses"]):
        configured = policy["responses"][response_index]
        action = request["action"]
        capabilities = tool_capabilities.get(action["tool_name"], [])
        values = set(argument_values(action["arguments"]))
        if configured["capability"] in capabilities and set(configured["target"]) <= values:
            result["decision"] = configured["decision"]
        else:
            result["decision"] = "reject"
    return result


def approved_write(policy: dict | None, trace: dict, write_seq: int, write_tools: set[str],
                   tool_capabilities: dict[str, list[str]]) -> bool:
    """해당 attempt trace를 재생해 승인 검사. 실행 전에는 쓰기 호출 예정 span까지 포함한다.

    write_tools는 snapshot에서 엔진이 만든 쓰기 도구 이름 집합이다. 입력 trace도 엔진 소유여야 한다.
    호출 번호는 입력 배열 순서가 아니라 seq 순서로 계산한다. 쓰기 시도마다 승인을 소비한다.
    """
    if policy is not None:
        contracts.validate("confirmation", policy, part="policy")
    contracts.validate("trace", trace)
    seqs = [s["seq"] for s in trace["spans"]]
    if len(seqs) != len(set(seqs)):
        raise ValueError("Duplicate span seq")
    pending = None
    index = 0
    for span in sorted(trace["spans"], key=lambda s: s["seq"]):
        if span["seq"] > write_seq:
            break
        if span["kind"] != "tool":
            continue
        if span["name"] == "request_user_confirmation":
            pending = None  # 재요청·거절은 이전 승인을 대체한다.
            try:
                request = span["tool_args"]
                expected = fixed_response(policy, request, index, tool_capabilities)
                recorded = json.loads(span.get("tool_result", "null"))
                contracts.validate("confirmation", recorded, part="response")
                if (not span.get("error") and span.get("attributes", {}).get("origin") == "builtin"
                        and canonical_json(expected) == canonical_json(recorded)
                        and recorded["decision"] == "approve"):
                    pending = (span["seq"], recorded["action"])
            except (KeyError, ValueError, TypeError):
                pass
            index += 1
        elif span["name"] in write_tools:
            action = {"tool_name": span["name"], "arguments": span.get("tool_args", {})}
            allowed = (pending is not None and same_action(pending[1], action)
                       and span.get("attributes", {}).get("confirmation_span_seq") == pending[0])
            pending = None
            if span["seq"] == write_seq:
                return bool(allowed)
        elif span["seq"] == write_seq:
            return False
    return False
