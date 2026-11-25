"""① 문항별 가짜 쓰기·상태 시나리오 검사. 모양은 contracts write_scenario 가 원본입니다."""

from __future__ import annotations

import copy

from slotagent.common import contracts


def validate(scenario: dict | None) -> dict | None:
    """모델을 부르기 전에 검사합니다. 입력과 분리된 복사본을 돌려줍니다."""
    if scenario is None:
        return None
    contracts.validate("write_scenario", scenario)
    subjects = [s["subject"] for s in scenario.get("states", [])]
    if len(subjects) != len(set(subjects)):
        raise ValueError("같은 상태 대상이 중복됐습니다.")
    for state in scenario.get("states", []):
        marks = [v["from_approvals"] for v in state["versions"]]
        if marks[0] != 0 or any(a >= b for a, b in zip(marks, marks[1:], strict=False)):
            raise ValueError("versions 는 from_approvals 0 부터 커지는 순서여야 합니다.")
    return copy.deepcopy(scenario)
