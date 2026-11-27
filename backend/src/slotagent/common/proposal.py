"""plan-proposal — 제안 만들기와, 저장할 때 다시 만들어 비교하기 (담당 ①, 3차 5).

부르는 곳: api/eng_plan_proposal.py (화면·chatbot 에 제안) · intake.service.create_experiment_draft (④ 저장).
④는 "고쳤는지"를 적지 않는다. create 요청의 proposal = {request, as_of} 로 서버가 제안을 다시 만들어
저장할 값과 비교하고, plan.proposal = {request, as_of, hash, edited, edited_fields} 를 채운다.

같은 (request, as_of) 면 같은 제안이 나와야 함:
- settings 는 valid_from <= as_of 인 행만 (setting_at)
- task_exposures 는 seen_at <= as_of 인 행만, 문항 고르기 seed 는 canonical_hash(request) 에서
- as_of 는 지금부터 MAX_AGE 안이어야 함 (아주 옛 기본값으로 "제안 그대로"를 만들지 못하게) → 넘으면 proposal_stale
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from slotagent.packs.select import select_tasks

from . import contracts
from .checks import CheckError, check_experiment_candidates
from .hashing import canonical_hash

MAX_AGE = timedelta(hours=24)
CLOCK_SKEW = timedelta(minutes=5)
EXPERIMENT_FIELDS = ("reps", "budget_krw", "candidates")


def proposal_hash(prereg: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    """제안 {prereg, plan} 의 해시. plan 의 proposal 칸은 빼고 계산."""
    return canonical_hash({"prereg": prereg, "plan": {k: v for k, v in plan.items() if k != "proposal"}})


def setting_at(conn, key: str, as_of: datetime, scope: str = "global", scope_ref: str = ""):
    """settings 는 추가만 → as_of 시점에 살아 있던 값 (같은 키의 valid_from <= as_of 중 가장 최근)."""
    r = conn.execute("""SELECT value FROM sa_settings WHERE scope=%s AND scope_ref=%s AND key=%s AND valid_from <= %s
                        ORDER BY valid_from DESC, setting_id DESC LIMIT 1""", (scope, scope_ref, key, as_of)).fetchone()
    return None if r is None else r[0]


def propose(conn, req: Mapping[str, Any], *, as_of: datetime | None = None) -> dict:
    """저장 없이 시점별 설정과 미열람 문항으로 파일럿 계획을 제안한다."""
    as_of = as_of or datetime.now(UTC)
    slot = conn.execute(
        "SELECT agent_version_id FROM sa_slots WHERE slot_id = %s", (req["slot_id"],),
    ).fetchone()
    if slot is None:
        raise CheckError("not_found", ["존재하지 않는 Slot입니다."])
    candidates = conn.execute(
        "SELECT slot_id, is_baseline FROM sa_candidates WHERE candidate_id = ANY(%s)",
        (req["candidate_ids"],),
    ).fetchall()
    if len(candidates) != len(req["candidate_ids"]):
        raise CheckError("not_found", ["존재하지 않는 후보가 있습니다."])
    if slot[0] != req["agent_version_id"] or any(slot_id != req["slot_id"] for slot_id, _ in candidates):
        raise CheckError("wrong_slot", ["에이전트 버전과 후보의 Slot이 일치해야 합니다."])
    check_experiment_candidates(
        {"slot_id": slot_id, "is_baseline": baseline} for slot_id, baseline in candidates
    )

    try:
        tasks = select_tasks(
            conn, req["pack_version_id"], None, split=req.get("split", "held"),
            as_of=as_of, seed=canonical_hash(req),
        )
    except ValueError as exc:
        raise CheckError("invalid_plan", ["잠긴 평가팩에 선택한 분할의 미열람 문항이 필요합니다."]) from exc

    prereg = {
        "schema_version": 1,
        "primary_metric": "success_rate",
        "test": "ni_then_sup",
        "margin_pp": setting_at(conn, "ni_margin_pp", as_of),
        "alpha": setting_at(conn, "alpha", as_of),
        "regression_limit": setting_at(conn, "regression_limit", as_of),
        "max_env_retries": setting_at(conn, "max_env_retries", as_of),
        "outcome_rules": {
            "agent_error": "fail",
            "timeout": "fail",
            "env_error": "retry_then_exclude",
            "grader_error": "exclude",
            "undecidable": "exclude",
            "out_of_scope": "fail",
            "env_error_reasons": setting_at(conn, "env_error_reasons", as_of),
        },
    }
    if contracts.errors("prereg", prereg):
        raise CheckError("invalid_plan", ["실험 기본 설정을 확인해 주세요."])
    n_templates = conn.execute(
        "SELECT count(DISTINCT template_id) FROM sa_tasks WHERE task_id = ANY(%s)",
        ([task["task_id"] for task in tasks],),
    ).fetchone()[0]
    reps = req.get("reps", 1)
    return {
        "prereg": prereg,
        "plan": {"schema_version": 1, "tasks": tasks},
        "as_of": as_of.isoformat(),
        "n_templates": n_templates,
        "n_tasks": len(tasks),
        "trials": len(candidates) * len(tasks) * reps,
        "reps": reps,
        "warnings": ["검정력 계산이 아직 적용되지 않아 미열람 문항 전체를 파일럿으로 제안합니다."],
    }


def check_as_of(as_of: datetime, now: datetime) -> None:
    if as_of > now + CLOCK_SKEW or now - as_of > MAX_AGE:
        raise CheckError("proposal_stale", [f"제안 시각({as_of.isoformat()})이 너무 오래됐거나 미래입니다. plan-proposal 을 다시 받으세요"])


def _top_level_diff(prefix: str, a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    keys = (set(a) | set(b)) - {"proposal"}
    return [f"{prefix}.{k}" for k in sorted(keys) if canonical_hash(a.get(k)) != canonical_hash(b.get(k))]


def edited_fields(proposed: Mapping[str, Any], saved: Mapping[str, Any]) -> list[str]:
    """proposed = plan-proposal 응답 + 요청의 실험 칸, saved = 저장할 값. 둘 다 {prereg, plan, reps, budget_krw, candidates}.
    prereg·plan 은 맨 위 칸 단위로, 실험 칸은 이름 그대로 (plan.schema proposal.edited_fields 패턴과 같음)."""
    out = _top_level_diff("prereg", proposed["prereg"], saved["prereg"]) + _top_level_diff("plan", proposed["plan"], saved["plan"])
    for k in EXPERIMENT_FIELDS:
        a, b = proposed.get(k), saved.get(k)
        if k == "candidates":
            a, b = sorted(a or []), sorted(b or [])
        if canonical_hash(a) != canonical_hash(b):
            out.append(k)
    return out


def record(request: Mapping[str, Any], as_of: str, proposed: Mapping[str, Any], saved: Mapping[str, Any]) -> dict:
    """plan.proposal 칸 (서버가 씀). proposed 에는 다시 만든 제안, saved 에는 ④가 저장하려는 값."""
    fields = edited_fields(proposed, saved)
    return {"request": dict(request), "as_of": as_of, "hash": proposal_hash(proposed["prereg"], proposed["plan"]),
            "edited": bool(fields), "edited_fields": fields}


def proposed_values(request: Mapping[str, Any], response: Mapping[str, Any]) -> dict:
    """plan-proposal 응답 + 요청 → 비교용 {prereg, plan, reps, budget_krw, candidates}."""
    return {"prereg": response["prereg"], "plan": response["plan"], "reps": response["reps"],
            "budget_krw": request.get("budget_krw"), "candidates": list(request["candidate_ids"])}


def verify(conn, req_proposal: Mapping[str, Any], saved: Mapping[str, Any], *, now: datetime | None = None) -> dict:
    """④ 저장 함수가 부름. req_proposal = create 요청의 proposal {request, as_of}. 돌려주는 값: plan.proposal 칸."""
    as_of = datetime.fromisoformat(req_proposal["as_of"])
    check_as_of(as_of, now or datetime.now(UTC))
    response = propose(conn, req_proposal["request"], as_of=as_of)
    return record(req_proposal["request"], req_proposal["as_of"], proposed_values(req_proposal["request"], response), saved)
