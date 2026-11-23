"""[①] 정답 조건(answer_condition 스키마) × 실행 기록(trace) → condition_results(passed, evidence). 코드로 볼 수 있는 것만."""


def check(kind: str, spec: dict, trace: dict) -> tuple[bool, dict]:
    raise NotImplementedError
