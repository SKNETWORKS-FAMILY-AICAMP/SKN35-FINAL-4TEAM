"""① 문항별 가짜 쓰기·상태 시나리오 (계약 초안, 4명 확인 전).

확정되면 SCHEMA 를 contracts/ 로 옮기고 이 파일은 검사 함수만 남깁니다. 엔진 전용이며 모델 입력에 넣지 않습니다.
"""

from __future__ import annotations

import copy

from jsonschema import Draft202012Validator
from referencing.jsonschema import EMPTY_REGISTRY

_TEXT = {"type": "string", "minLength": 1}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "문항별 쓰기 시나리오 초안 v1",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version"],
    "properties": {
        "schema_version": {"const": 1},
        "writes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["capability", "target", "outcomes"],
                "properties": {
                    "capability": {"type": "string", "pattern": r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$"},
                    "target": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _TEXT},
                    "outcomes": {
                        "description": "맞는 쓰기가 실행된 순서대로. 다 쓰면 마지막 값을 반복",
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["status"],
                            "properties": {
                                "status": {"enum": ["ok", "failed", "unknown"]},
                                "applied": {"description": "unknown 만. 실제로 반영됐는지", "type": "boolean"},
                                "reason": _TEXT,
                                "result": {"description": "성공 응답·결과 조회에 보일 값", "type": "object"},
                            },
                            "if": {"properties": {"status": {"const": "unknown"}}},
                            "then": {"required": ["applied"]},
                            "else": {"not": {"required": ["applied"]}},
                        },
                    },
                },
            },
        },
        "states": {
            "description": "승인 뒤 바뀌는 업무 상태. get_work_state 로만 보임",
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["subject", "versions"],
                "properties": {
                    "subject": _TEXT,
                    "versions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["from_approvals", "value"],
                            "properties": {
                                "from_approvals": {"type": "integer", "minimum": 0},
                                "value": {"type": "object"},
                            },
                        },
                    },
                },
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA, registry=EMPTY_REGISTRY)


def validate(scenario: dict | None) -> dict | None:
    """모델을 부르기 전에 검사합니다. 입력과 분리된 복사본을 돌려줍니다."""
    if scenario is None:
        return None
    errors = [e.message for e in _VALIDATOR.iter_errors(scenario)]
    if errors:
        raise ValueError("쓰기 시나리오 형식 오류: " + "; ".join(errors[:5]))
    subjects = [s["subject"] for s in scenario.get("states", [])]
    if len(subjects) != len(set(subjects)):
        raise ValueError("같은 상태 대상이 중복됐습니다.")
    for state in scenario.get("states", []):
        marks = [v["from_approvals"] for v in state["versions"]]
        if marks[0] != 0 or any(a >= b for a, b in zip(marks, marks[1:], strict=False)):
            raise ValueError("versions 는 from_approvals 0 부터 커지는 순서여야 합니다.")
    return copy.deepcopy(scenario)
