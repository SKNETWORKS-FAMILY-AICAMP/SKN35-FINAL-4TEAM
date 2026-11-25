"""① 규칙 채점에 넘길 신뢰 문맥. config_snapshot과 문항에서만 만들고 trace 값은 쓰지 않습니다."""

from __future__ import annotations

from slotagent.engine.tool_search import SEARCH
from slotagent.engine.write_proxy import BUILTIN_NAMES
from slotagent.grading.eng_rules import ConfirmationContext


def from_tools(tools: list[dict], confirmation: dict | None, builtins: frozenset = BUILTIN_NAMES) -> dict:
    """도구 정의(name·access·capabilities)로 eng_rules.check 의 키워드 인자를 만듭니다.

    실행된 도구는 스냅숏의 도구와 엔진 내장 도구가 전부이므로 완전한 문맥입니다.
    """
    access = {t["name"]: t["access"] for t in tools}
    if len(access) != len(tools) or set(access) & builtins:
        raise ValueError("도구 이름이 겹치거나 엔진 내장 도구와 같습니다.")
    return {
        "tool_access": {**access, **dict.fromkeys(builtins, "builtin")},
        "tool_access_complete": True,
        "confirmation": ConfirmationContext(
            confirmation,
            frozenset(name for name, value in access.items() if value == "write"),
            {t["name"]: list(t.get("capabilities", [])) for t in tools},
        ),
    }


def from_snapshot(snapshot: dict, confirmation: dict | None) -> dict:
    # 검색 도구는 검색 후보에만 있으므로 다른 후보에서는 이름을 예약하지 않습니다.
    builtins = BUILTIN_NAMES | {SEARCH} if snapshot.get("tool_search") else BUILTIN_NAMES
    return from_tools(snapshot["tools"], confirmation, builtins)
