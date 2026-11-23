"""해시 한 곳 (담당 ①). spec_hash · config_hash · content_hash 모두 이걸로만 만든다.

규칙
- JSON 키 정렬, 공백 없음, UTF-8 (한글 그대로)
- 정수로 떨어지는 실수는 정수로 (0.0 -> 0). DB numeric(Decimal)도 같게
- 결과 앞에 "sha256:" 을 붙임
화면·다른 언어에서 따로 만들지 않는다. 필요하면 API로 받아 간다.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


def _normalize(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float, Decimal)):
        if isinstance(v, float) and v != v:  # NaN
            raise ValueError("NaN 은 해시할 수 없습니다")
        if v == int(v):
            return int(v)
        return float(v)
    if isinstance(v, dict):
        return {str(k): _normalize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_normalize(x) for x in v]
    raise TypeError(f"해시할 수 없는 값: {type(v).__name__}")


def canonical_json(obj: Any) -> str:
    return json.dumps(_normalize(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def agent_spec_hash(model: str, temperature: Any, instructions: str, spec: dict) -> str:
    """agent_versions.spec_hash — 모델·온도·지시문·구성 명세를 함께."""
    return canonical_hash({"model": model, "temperature": temperature, "instructions": instructions, "spec": spec})
