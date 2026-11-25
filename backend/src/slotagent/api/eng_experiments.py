"""① 실험 실행·중지·상태. 라우터와 DB 조회만 하고, 상태 바꾸기는 engine.lock·advance 로만 합니다.

POST /api/experiments/{id}/run    잠금 + 풀이 작업 넣기. 같은 요청을 반복해도 한 번만
POST /api/experiments/{id}/stop   사용자 멈춤. 이미 멈춘 실험이면 지금 상태만 돌려줌
GET  /api/experiments/{id}/status
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.concurrency import run_in_threadpool

from slotagent.common import contracts, queue
from slotagent.common.checks import CheckError
from slotagent.engine import advance
from slotagent.engine.lock import lock_and_enqueue

router = APIRouter(prefix="/api/experiments")
ExperimentId = Annotated[int, Path(ge=1, le=2**63 - 1)]
STATES = ("pending", "running", "finished", "error", "cancelled")


def status(conn, experiment_id: int) -> dict:
    """계획 단위(후보, 문항, 반복)마다 마지막 실행으로 셉니다. 초안은 풀이 행이 없으므로 계획 수를 pending 으로 셉니다."""
    with queue.transaction(conn):
        # 한 문장으로 읽어 세는 동안 상태·풀이가 바뀌어도 같은 시점입니다.
        row = conn.execute(
            """SELECT e.status, e.stop_reason, e.budget_krw,
                 CASE WHEN jsonb_typeof(e.plan->'tasks')='array' THEN jsonb_array_length(e.plan->'tasks') ELSE 0 END * e.reps
                   * (SELECT count(*) FROM sa_experiment_candidates c WHERE c.experiment_id=e.experiment_id),
                 (SELECT coalesce(jsonb_object_agg(s, n), '{}') FROM (
                    SELECT status AS s, count(*) AS n FROM (
                      SELECT DISTINCT ON (experiment_candidate_id, task_id, rep) status FROM sa_trials t
                      WHERE t.experiment_id=e.experiment_id
                      ORDER BY experiment_candidate_id, task_id, rep, run_no DESC) last GROUP BY status) counts),
                 (SELECT count(*) FROM sa_trials t WHERE t.experiment_id=e.experiment_id AND t.run_no > 1),
                 (SELECT coalesce(sum(cost_krw),0) FROM sa_cost_ledger l WHERE l.experiment_id=e.experiment_id),
                 (SELECT max(grading_run_id) FROM sa_grading_runs g WHERE g.experiment_id=e.experiment_id),
                 (SELECT max(analysis_id) FROM sa_analyses a WHERE a.experiment_id=e.experiment_id)
               FROM sa_experiments e WHERE e.experiment_id=%s""",
            (experiment_id,),
        ).fetchone()
    if row is None:
        raise CheckError("not_found", ["실험이 없습니다."])
    state, stop_reason, budget, planned, counts, reruns, cost, grading, analysis = row
    trials = {name: counts.get(name, 0) for name in STATES}
    if state == "draft":
        trials["pending"] = planned
    if not sum(trials.values()):
        raise CheckError("invalid_plan", ["실험에 후보나 문항이 없습니다."])
    return contracts.validate(
        "api",
        {
            "experiment_id": experiment_id,
            "status": state,
            "stop_reason": stop_reason,
            "trials_total": sum(trials.values()),
            "trials": trials,
            "env_reruns": reruns,
            "cost_krw": float(cost),
            "budget_krw": None if budget is None else float(budget),
            "latest_grading_run_id": grading,
            "latest_analysis_id": analysis,
        },
        part="status_response",
    )


def stop(conn, experiment_id: int) -> dict:
    with queue.transaction(conn):
        row = conn.execute(
            "SELECT status FROM sa_experiments WHERE experiment_id=%s FOR UPDATE", (experiment_id,)
        ).fetchone()
        if row is None:
            raise CheckError("not_found", ["실험이 없습니다."])
        if row[0] == "draft":
            raise CheckError("not_lockable", ["아직 시작하지 않은 실험입니다."])
        if row[0] in {"done", "failed"}:
            raise CheckError("experiment_locked", ["이미 끝난 실험입니다."])
        if row[0] in {"locked", "running"}:
            advance.stop_experiment(conn, experiment_id, "user")
    return status(conn, experiment_id)


@router.post("/{experiment_id}/run")
def run_route(request: Request, experiment_id: ExperimentId):
    with request.app.state.connect() as conn:
        return lock_and_enqueue(conn, experiment_id)


@router.post("/{experiment_id}/stop")
async def stop_route(request: Request, experiment_id: ExperimentId):
    raw = await request.body()
    if raw.strip():
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError):
            raise CheckError("invalid_spec", ["본문이 JSON 이 아닙니다."]) from None
        if contracts.errors("api", body, part="stop_request"):
            raise CheckError("invalid_spec", ["멈춤 요청에는 본문을 넣지 않습니다."])

    def work():
        with request.app.state.connect() as conn:
            return stop(conn, experiment_id)

    return await run_in_threadpool(work)


@router.get("/{experiment_id}/status")
def status_route(request: Request, experiment_id: ExperimentId):
    with request.app.state.connect() as conn:
        return status(conn, experiment_id)
