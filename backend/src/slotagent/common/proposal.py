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

from .checks import CheckError
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


def propose(conn, req: Mapping[str, Any], *, as_of: datetime | None = None, sample_size=None) -> dict:
    """api.plan_proposal_request → api.plan_proposal_response (as_of 포함, plan 에 proposal 칸 없음).
    값: settings(setting_at) + stats.sample_size(③) + 문항 고르기(② packs.select.plan_rows).
    ② select_tasks 는 as_of 를 받지 않아 노출(seen_at <= as_of)만 여기서 읽고 고르는 규칙은 ②의 plan_rows 를 그대로 씀.
    plan_rows 는 정렬 순서대로 고르므로 seed 가 필요 없음. sample_size 는 시험에서만 바꿔 넣음."""
    from slotagent.packs.select import plan_rows
    from slotagent.stats import analyze

    as_of = as_of or datetime.now(UTC)
    _check_request(conn, req)

    def setting(key):
        value = setting_at(conn, key, as_of)
        if value is None:
            raise CheckError("invalid_plan", [f"기본값 settings '{key}' 가 없습니다 (as_of {as_of.isoformat()})"])
        return value

    margin, alpha = setting("ni_margin_pp"), setting("alpha")
    prereg = {
        "schema_version": 1, "primary_metric": "success_rate", "test": "ni_then_sup",
        "margin_pp": margin, "alpha": alpha, "regression_limit": setting("regression_limit"),
        "outcome_rules": {"agent_error": "fail", "timeout": "fail", "env_error": "retry_then_exclude",
                          "grader_error": "exclude", "undecidable": "exclude", "out_of_scope": setting("out_of_scope_rule"),
                          "env_error_reasons": setting("env_error_reasons")},
        "max_env_retries": setting("max_env_retries"),
    }
    n_templates = (sample_size or analyze.sample_size)(margin, alpha, setting("power"), setting("p_base"))["n_templates"]
    rows = conn.execute(
        """SELECT t.template_id, k.task_id,
                  EXISTS(SELECT 1 FROM sa_task_exposures e WHERE e.task_id=k.task_id AND e.seen_at <= %s)
           FROM sa_templates t JOIN sa_tasks k USING(template_id)
           WHERE t.pack_version_id=%s AND t.split=%s ORDER BY t.template_id, k.task_id""",
        (as_of, req["pack_version_id"], req.get("split", "held")),
    ).fetchall()
    try:
        tasks = plan_rows(rows, n_templates)
    except ValueError as exc:
        raise CheckError("invalid_plan", [f"문항을 고를 수 없습니다: {exc}"]) from None
    reps = req.get("reps") or setting("reps")
    return {"prereg": prereg, "plan": {"schema_version": 1, "tasks": tasks}, "reps": reps,
            "n_templates": n_templates, "n_tasks": len(tasks), "trials": len(req["candidate_ids"]) * len(tasks) * reps,
            "as_of": as_of.isoformat()}


def _check_request(conn, req: Mapping[str, Any]) -> None:
    """평가팩은 잠긴 것만, 자리는 그 에이전트 버전의 것, 후보는 그 자리의 것만."""
    pack = conn.execute("SELECT status FROM sa_pack_versions WHERE pack_version_id=%s", (req["pack_version_id"],)).fetchone()
    if pack is None:
        raise CheckError("not_found", ["평가팩 버전이 없습니다."])
    if pack[0] != "locked":
        raise CheckError("invalid_plan", ["잠긴 평가팩만 실험에 쓸 수 있습니다."])
    slot = conn.execute("SELECT agent_version_id FROM sa_slots WHERE slot_id=%s", (req["slot_id"],)).fetchone()
    if slot is None or slot[0] != req["agent_version_id"]:
        raise CheckError("not_found", ["이 에이전트 버전의 자리가 아닙니다."])
    found = conn.execute("SELECT count(*) FROM sa_candidates WHERE slot_id=%s AND candidate_id = ANY(%s)",
                         (req["slot_id"], list(req["candidate_ids"]))).fetchone()[0]
    if found != len(req["candidate_ids"]):
        raise CheckError("wrong_slot", ["이 자리의 후보가 아닌 것이 있습니다."])


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
