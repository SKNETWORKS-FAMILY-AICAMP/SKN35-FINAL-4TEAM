"""① 풀이 하나의 답·과정 상태 (과정 채점 진단). 순수 함수이며 리포트 집계 정의는 ③과 확정합니다.

기존 성공률은 관문(gate) 조건의 충족 여부이고, 이 상태는 비관문 조건까지 포함한 각 축의 충족 여부입니다.
두 숫자는 다른 질문에 대한 답이라 리포트에서도 다른 이름으로 둡니다.

축 상태는 다음 순서로 정합니다.
1. 확정된 위반이 하나라도 있음 → violation (판정 불가가 섞여 있어도)
2. 위반은 없고 판정 불가가 있음 → undecided
3. 적용 조건을 모두 통과 → passed
4. 적용할 조건이 없음 → none
"""

from __future__ import annotations

from collections.abc import Iterable

ANSWER_KINDS = frozenset({"info", "end_state", "exact_writes"})
PROCESS_KINDS = frozenset({"order", "forbidden", "link", "uses"})


def axis_state(results: Iterable[bool | None]) -> str:
    values = list(results)
    if any(v is False for v in values):
        return "violation"
    if any(v is None for v in values):
        return "undecided"
    return "passed" if values else "none"


def trial_states(conditions, policy=()) -> dict[str, str]:
    """conditions: kind·passed 가 있는 ConditionResult 들, policy: passed 가 있는 PolicyResult 들."""
    conditions = list(conditions)
    unknown = {c.kind for c in conditions} - ANSWER_KINDS - PROCESS_KINDS
    if unknown:
        raise ValueError(f"답·과정 어느 쪽인지 정하지 않은 조건 종류입니다: {sorted(unknown)}")
    return {
        "answer": axis_state(c.passed for c in conditions if c.kind in ANSWER_KINDS),
        "process": axis_state([c.passed for c in conditions if c.kind in PROCESS_KINDS] + [p.passed for p in policy]),
    }


def extra_calls(trace: dict, reference: dict) -> int:
    """참조(골든) 풀이 대비 추가 도구 호출 수. 음수도 그대로 둡니다. 골든은 유효한 풀이의 한 예라 진단용입니다."""

    def count(t):
        return sum(1 for s in t["spans"] if s["kind"] == "tool")

    return count(trace) - count(reference)
