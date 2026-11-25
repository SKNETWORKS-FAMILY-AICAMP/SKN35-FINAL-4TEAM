"""① 코드를 받지 못한 자체(custom) 도구를 정해 둔 고정 응답으로 실행합니다 (기획서 1.3 5.8)."""

from __future__ import annotations

import json

from slotagent.common.hashing import canonical_hash


def is_fixed_read(tool: dict) -> bool:
    return tool["access"] == "read" and tool["origin"] == "custom"


def match(tool: dict, args: dict) -> str | None:
    """인자가 맞는 첫 응답의 원문. 없으면 None. 값은 JSON 으로 비교합니다 (true 와 1 은 다름)."""
    for fixed in tool.get("fixed_responses", []):
        if all(k in args and canonical_hash(args[k]) == canonical_hash(v) for k, v in fixed["when"].items()):
            return fixed["result"]
    return None


def no_match() -> str:
    """모델에 돌려주는 도구 오류. 다른 값을 지어내거나 실행을 멈추지 않습니다."""
    return json.dumps({"error": "no_fixed_response"}, ensure_ascii=False)
