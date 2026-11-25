"""① 실행된 쓰기의 대상·횟수를 정확히 비교하는 순수 함수 (계약 초안, eng_rules 에는 아직 연결하지 않음).

조건 예: {"schema_version": 1, "writes": [{"capability": "slack.messages.write", "target": ["ops-alerts"],
         "attempts": 1, "applied": 1}]}
- attempts: 승인되어 가짜로 실행된 호출 수, applied: 그중 반영된 수. 둘 다 정확히 같아야 함
- 어느 항목에도 안 맞는 실행된 쓰기가 있으면 실패. writes 가 [] 이면 실행된 쓰기가 없어야 함
- 막힌 쓰기는 세지 않음 (금지 행동은 forbidden 이 봄). 내용 검사는 args_include(선택)
"""

from __future__ import annotations

from collections.abc import Mapping

from jsonschema import Draft202012Validator
from referencing.jsonschema import EMPTY_REGISTRY

from slotagent.common import contracts
from slotagent.common.confirmation import argument_values
from slotagent.grading.eng_rules import RulePolicyRequired, _includes

_COUNT = {"type": "integer", "minimum": 0}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "writes"],
    "properties": {
        "schema_version": {"const": 1},
        "writes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["capability", "target", "attempts", "applied"],
                "properties": {
                    "capability": {"type": "string", "minLength": 1},
                    "target": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
                    "args_include": {"type": "object"},
                    "attempts": _COUNT,
                    "applied": _COUNT,
                },
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA, registry=EMPTY_REGISTRY)


def check_exact_writes(
    spec: dict, trace: dict, tool_capabilities: Mapping[str, list[str]]
) -> tuple[bool, dict]:
    """통과 여부와 근거. 실행 상태 기록이 없거나 조건이 겹치면 판정하지 않습니다."""
    errors = [e.message for e in _VALIDATOR.iter_errors(spec)]
    if errors:
        raise ValueError("쓰기 조건 형식 오류: " + "; ".join(errors[:5]))
    contracts.validate("trace", trace)
    spans = {s["seq"]: s for s in trace["spans"]}
    counts = [[0, 0] for _ in spec["writes"]]
    extra, blocked, executed = [], [], []
    for intent in trace["write_intents"]:
        span = spans.get(intent["span_seq"])
        if span is None or span["kind"] != "tool":
            raise ValueError("쓰기 기록의 span 참조가 올바르지 않습니다.")
        attributes = span.get("attributes", {})
        status = attributes.get("write_status")
        if status not in {"ok", "failed", "unknown", "blocked"} or type(attributes.get("write_applied")) is not bool:
            raise RulePolicyRequired("write_status_missing")
        if status == "blocked":
            blocked.append(intent["span_seq"])
            continue
        if intent["tool_name"] not in tool_capabilities:
            raise RulePolicyRequired("tool_capabilities_missing")
        executed.append(intent["span_seq"])
        values = set(argument_values(intent["payload"]))
        matched = [
            number
            for number, want in enumerate(spec["writes"])
            if want["capability"] in tool_capabilities[intent["tool_name"]]
            and set(want["target"]) <= values
            and _includes(intent["payload"], want.get("args_include", {}))
        ]
        if len(matched) > 1:
            raise RulePolicyRequired("ambiguous_write_selector")
        if not matched:
            extra.append(intent["span_seq"])
            continue
        counts[matched[0]][0] += 1
        counts[matched[0]][1] += attributes["write_applied"]
    passed = not extra and all(
        got == [want["attempts"], want["applied"]] for got, want in zip(counts, spec["writes"], strict=True)
    )
    return passed, {"span_seqs": executed, "counts": counts, "extra": extra, "blocked": blocked}
