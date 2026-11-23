"""DB 오류 → api.error code. 문구로 고르지 않음 (11/22 검토 20).

고르는 순서
1. DB 가 붙인 HINT (0003 마이그레이션: RAISE ... USING HINT = 'experiment_locked')
2. 제약·인덱스 이름 (UNIQUE 위반 등 HINT 를 붙일 수 없는 것)
3. 그 밖은 internal
사용자 문구는 contracts/examples/api_and_jobs.json 의 api.error 예시를 기준으로 화면·API 가 붙임.
"""
from __future__ import annotations

API_CODES = {"invalid_spec", "invalid_plan", "limit_exceeded", "baseline_exists", "label_taken", "wrong_slot",
             "immutable", "experiment_locked", "not_lockable", "not_found", "budget_exceeded", "proposal_stale", "internal"}

CONSTRAINT_TO_CODE = {
    "sa_candidates_one_baseline": "baseline_exists",
    "sa_candidates_label_per_slot": "label_taken",
    "sa_experiment_one_baseline": "invalid_spec",
    "sa_experiment_candidates_label_per_experiment": "label_taken",
    "sa_experiments_budget_positive": "invalid_spec",
}


def to_api_code(exc) -> str:
    """psycopg.errors.Error → api.error code."""
    diag = getattr(exc, "diag", None)
    hint = getattr(diag, "message_hint", None)
    if hint in API_CODES:
        return hint
    name = getattr(diag, "constraint_name", None)
    if name in CONSTRAINT_TO_CODE:
        return CONSTRAINT_TO_CODE[name]
    return "internal"


def to_api_error(exc) -> dict:
    """api.error 모양. message 는 DB 원문이 아니라 화면이 code 로 고른 문구를 씀 — 여기서는 DB 원문을 detail 에만."""
    diag = getattr(exc, "diag", None)
    return {"code": to_api_code(exc), "message": getattr(diag, "message_primary", None) or str(exc),
            "detail": {"sqlstate": getattr(exc, "sqlstate", None), "constraint": getattr(diag, "constraint_name", None)}}
