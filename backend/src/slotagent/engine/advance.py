"""[①] 다음 단계로 넘기기 — 실험 상태 바꾸기와 다음 작업 넣기는 모두 여기서만 (11/22 검토 1·2·5·6).

다른 역할은 상태를 직접 바꾸지 않는다. ③은 판정만 남기고(analyses.method.sequential.stop), ①이 그걸 읽고 실행한다.

실험 상태 (experiments.status)
    draft ──lock_experiment()──▶ locked ──mark_running()──▶ running ──on_reports_done()──▶ done
                                                            ├─ check_budget() 예산 도달 ───▶ stopped (stop_reason='budget')
                                                            ├─ 중간 분석 stop=true ───────▶ stopped (stop_reason='interim')
                                                            ├─ 사용자 멈춤 (POST .../stop) ─▶ stopped (stop_reason='user')
                                                            └─ 채점·분석 작업이 끝내 실패 ──▶ failed  (stop_reason='job_failed')
    stop_reason 값 목록 = contracts $defs/stop_reason = DB CHECK experiments_stop_reason_known
    stopped/failed 가 되면 대기(pending) 풀이는 cancelled, 그 풀이의 run_trial 작업도 cancelled.

예산 (FR-RUN-08)
    풀이(source=trial)와 판정기(source=judge) 비용을 같은 예산에서 셈 — cost_ledger 의 그 실험 행 합계.
    확인은 풀이를 시작하기 전에만 하므로 넘을 수 있음 — 상한: **동시 워커 수 × 풀이 1번 예상 비용**
    (워커마다 같은 남은 예산을 보고 동시에 시작할 수 있으므로) + 진행 중인 채점 비용.
    멈춘 뒤에도 이미 끝난 풀이의 채점은 끝까지 함 (판정을 내기 위해). 예약 장부는 두지 않음 (3차, 필요하면 cost_ledger 에 칸 추가).

부르는 곳
    engine.lock.lock_and_enqueue        → mark_running
    engine.worker.run_trial 시작 전      → check_budget (False 면 실행 안 함)
    engine.worker.run_trial 끝낸 트랜잭션 → on_trial_finished
    grading.eng_pipeline.grade 끝        → on_grading_finished
    stats.analyze.analyze 끝             → on_analysis_done
    reports 끝                           → on_reports_done
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from psycopg import sql
from psycopg.pq import TransactionStatus

from slotagent.common import checks, contracts
from slotagent.common.db_names import col, table

GRADER_VERSION = "0.1.0"
TRIAL_JOB_MAX_ATTEMPTS = 3

# 실행 중 실제 원인이 보존된 분류만 연결합니다. 일반 RuntimeError 등은 추측하지 않습니다.
JOB_FAILURE_REASONS = {
    "ToolEnvironmentError": "env_mcp_server_down",  # 이전 stdio 시작 실패 기록과 호환
    "env_mcp_server_down": "env_mcp_server_down",
    "lease_expired": "env_worker_lost",
    "LeaseLost": "env_worker_lost",
    "env_worker_lost": "env_worker_lost",
    "timeout_wall_clock": "timeout_wall_clock",
}


class UnmappedFailureError(ValueError):
    """원래 분류만으로 계약의 실패 원인을 확정할 수 없어 사람이 검토해야 합니다."""

    def __init__(self, classification):
        super().__init__("기존 실패 원인에 대응하지 않는 작업 오류입니다. 원인을 확인하세요.")
        self.classification = classification


@dataclass(frozen=True)
class ResumeResult:
    job_id: int
    resumed: bool
    exhausted: bool = False


def resume_failed_trial(conn, trial_id: int) -> ResumeResult:
    """사람이 요청한 재개만 처리합니다. 같은 작업·누적 attempts·오류·비용을 보존합니다.

    소진된 경우 종결을 커밋해야 하므로 예외 대신 exhausted=True로 재개 거절을 반환합니다.
    모르는 실패 원인은 상태를 바꾸지 않고 UnmappedFailureError로 보고합니다.
    """
    if isinstance(trial_id, bool) or not isinstance(trial_id, int) or trial_id < 1:
        raise ValueError("유효한 trial 번호가 필요합니다.")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("재개에는 외부 트랜잭션이 없는 연결을 넘기세요.")
    jobs, trials, experiments = (sql.Identifier(table(e)) for e in ("jobs", "trials", "experiments"))
    j = {name: sql.Identifier(col("jobs", name)) for name in (
        "id", "kind", "payload", "status", "attempts", "last_error", "leased_by", "lease_until", "updated_at",
    )}
    t = {name: sql.Identifier(col("trials", name)) for name in (
        "id", "experiment_id", "status", "run_outcome", "outcome_reason", "finished_at",
    )}
    e = {name: sql.Identifier(col("experiments", name)) for name in ("id", "status", "prereg")}
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='5s'")
        # queue.guard/fail과 동일하게 job → experiment → trial 순서로 잠급니다.
        job = conn.execute(sql.SQL(
            "SELECT {id},{status},{attempts},{last_error} FROM {jobs} "
            "WHERE {kind}='run_trial' AND {payload}->>'trial_id'=%s "
            "ORDER BY {id} DESC LIMIT 1 FOR UPDATE"
        ).format(jobs=jobs, **j), (str(trial_id),)).fetchone()
        if job is None:
            raise ValueError("이 풀이의 실행 작업이 없습니다.")
        job_id, job_status, attempts, last_error = job
        exp_row = conn.execute(sql.SQL("SELECT {experiment_id} FROM {trials} WHERE {id}=%s").format(
            trials=trials, **t), (trial_id,)).fetchone()
        if exp_row is None:
            raise ValueError("풀이가 없습니다.")
        exp_id = exp_row[0]
        exp_status, prereg = conn.execute(sql.SQL(
            "SELECT {status},{prereg} FROM {experiments} WHERE {id}=%s FOR UPDATE"
        ).format(experiments=experiments, **e), (exp_id,)).fetchone()
        trial_status = conn.execute(sql.SQL("SELECT {status} FROM {trials} WHERE {id}=%s FOR UPDATE").format(
            trials=trials, **t), (trial_id,)).fetchone()[0]
        if exp_status not in {"locked", "running"}:
            raise ValueError("중단·완료된 실험은 재개할 수 없습니다.")
        if job_status in {"queued", "leased"} and trial_status in {"pending", "running"}:
            return ResumeResult(job_id, False)
        if job_status != "failed" or trial_status != "pending":
            raise ValueError("failed 작업에 남은 pending 풀이만 재개할 수 있습니다.")
        active = conn.execute(sql.SQL(
            "SELECT 1 FROM {jobs} WHERE {kind}='run_trial' AND {payload}->>'trial_id'=%s "
            "AND {status} IN ('queued','leased') LIMIT 1"
        ).format(jobs=jobs, **j), (str(trial_id),)).fetchone()
        if active is not None:
            raise ValueError("같은 풀이의 다른 활성 작업이 있습니다.")
        if attempts >= TRIAL_JOB_MAX_ATTEMPTS:
            reason = JOB_FAILURE_REASONS.get(last_error)
            if reason is None:
                raise UnmappedFailureError(last_error)
            contracts.validate("common", reason, part="outcome_reason")
            outcome = checks.run_outcome_for(reason, prereg)
            conn.execute(sql.SQL(
                "UPDATE {trials} SET {status}='error',{run_outcome}=%s,{outcome_reason}=%s,{finished_at}=now() "
                "WHERE {id}=%s"
            ).format(trials=trials, **t), (outcome, reason, trial_id))
            on_trial_finished(conn, trial_id)
            return ResumeResult(job_id, False, True)
        conn.execute(sql.SQL(
            "UPDATE {jobs} SET {status}='queued',{leased_by}=NULL,{lease_until}=NULL,{updated_at}=now() WHERE {id}=%s"
        ).format(jobs=jobs, **j), (job_id,))
        return ResumeResult(job_id, True)


def _one(conn, sql: str, *args):
    r = conn.execute(sql, args).fetchone()
    return None if r is None else r[0]


def enqueue(conn, payload: dict, priority: int = 0) -> int:
    contracts.validate("job_payload", payload)
    return _one(conn, "INSERT INTO sa_jobs(kind, payload, priority) VALUES (%s, %s::jsonb, %s) RETURNING job_id",
                payload["kind"], json.dumps(payload), priority)


def latest_setting(conn, key: str, scope: str = "global", scope_ref: str = ""):
    """settings 는 추가만 → 같은 키의 가장 최근 valid_from 이 지금 값."""
    return _one(conn, """SELECT value FROM sa_settings WHERE scope=%s AND scope_ref=%s AND key=%s AND valid_from <= now()
                         ORDER BY valid_from DESC, setting_id DESC LIMIT 1""", scope, scope_ref, key)


def mark_running(conn, experiment_id: int) -> None:
    conn.execute("UPDATE sa_experiments SET status='running' WHERE experiment_id=%s AND status='locked'", (experiment_id,))


STOP_REASONS = {"budget", "interim", "user", "job_failed"}


def stop_experiment(conn, experiment_id: int, reason: str) -> int:
    """멈추고 대기 풀이·작업을 취소. reason = job_failed 면 failed, 나머지는 stopped. 돌려주는 값: 취소한 풀이 수."""
    if reason not in STOP_REASONS:
        raise ValueError(f"stop_reason 은 {sorted(STOP_REASONS)} 중 하나")
    status = "failed" if reason == "job_failed" else "stopped"
    conn.execute("UPDATE sa_experiments SET status=%s, stop_reason=%s WHERE experiment_id=%s AND status IN ('locked','running')",
                 (status, reason, experiment_id))
    ids = [r[0] for r in conn.execute(
        "UPDATE sa_trials SET status='cancelled' WHERE experiment_id=%s AND status='pending' RETURNING trial_id", (experiment_id,))]
    if ids:
        conn.execute("""UPDATE sa_jobs SET status='cancelled', updated_at=now()
                        WHERE kind='run_trial' AND status='queued' AND (payload->>'trial_id')::bigint = ANY(%s)""", (ids,))
    return len(ids)


def check_budget(conn, experiment_id: int) -> bool:
    """FR-RUN-08. 비용 장부(cost_ledger) 합이 예산 이상이면 멈추고 False."""
    budget = _one(conn, "SELECT budget_krw FROM sa_experiments WHERE experiment_id=%s", experiment_id)
    if budget is None:
        return True
    spent = _one(conn, "SELECT coalesce(sum(cost_krw), 0) FROM sa_cost_ledger WHERE experiment_id=%s", experiment_id)
    if spent >= budget:
        stop_experiment(conn, experiment_id, "budget")
        return False
    return True


def _scope_for(conn, experiment_id: int, batch_no: int) -> int | None | bool:
    """방금 끝난 풀이의 묶음으로 채점 범위를 정함. 아직 덜 끝났으면 False.
    순차 검정이면 '이 묶음까지', 아니면 전체(None)."""
    prereg = _one(conn, "SELECT prereg FROM sa_experiments WHERE experiment_id=%s", experiment_id)
    seq = (prereg or {}).get("sequential", {"method": "none"})
    upto = batch_no if seq.get("method") == "group_sequential" else None
    if _one(conn, "SELECT grading_scope_unfinished(%s, %s)", experiment_id, upto) > 0:
        return False
    return upto


def on_trial_finished(conn, trial_id: int) -> int | None:
    """범위 안 풀이가 모두 끝났으면 initial 채점 실행 1개 + grade 작업. 이미 있으면 아무것도 안 함.
    워커 여러 개가 동시에 와도 grading_runs_one_initial(0003)이 하나만 남김. 돌려주는 값: 새 grading_run_id 또는 None."""
    exp_id, batch_no = conn.execute("SELECT experiment_id, batch_no FROM sa_trials WHERE trial_id=%s", (trial_id,)).fetchone()
    upto = _scope_for(conn, exp_id, batch_no)
    if upto is False:
        return None
    domain, pack = conn.execute("""SELECT p.domain_code, e.pack_version_id FROM sa_experiments e
                                   JOIN sa_pack_versions p ON p.pack_version_id = e.pack_version_id WHERE e.experiment_id=%s""", (exp_id,)).fetchone()
    judge = latest_setting(conn, "judge.settings", "domain", domain) or {}
    judge_model = latest_setting(conn, "judge.model", "domain", domain) if judge else None
    contracts.validate("grading", judge, part="judge_settings")
    gr = _one(conn, """INSERT INTO sa_grading_runs(experiment_id, pack_version_id, grader_version, judge_model, judge_settings, purpose, upto_batch_no)
                       VALUES (%s, %s, %s, %s, %s::jsonb, 'initial', %s)
                       ON CONFLICT (experiment_id, (coalesce(upto_batch_no, 0))) WHERE purpose = 'initial' DO NOTHING
                       RETURNING grading_run_id""", exp_id, pack, GRADER_VERSION, judge_model, json.dumps(judge), upto)
    if gr is not None:
        enqueue(conn, {"schema_version": 1, "kind": "grade", "grading_run_id": gr})
    return gr


def on_grading_finished(conn, grading_run_id: int) -> int:
    """채점이 끝나면 분석 작업. 마지막 묶음 전이면 중간 분석."""
    exp_id, upto = conn.execute("SELECT experiment_id, upto_batch_no FROM sa_grading_runs WHERE grading_run_id=%s", (grading_run_id,)).fetchone()
    last = _one(conn, "SELECT max(batch_no) FROM sa_trials WHERE experiment_id=%s", exp_id)
    interim = upto is not None and upto < last
    p = {"schema_version": 1, "kind": "analyze", "grading_run_id": grading_run_id, "is_interim": interim}
    if interim:
        p["batch_no"] = upto
    return enqueue(conn, p)


def on_analysis_done(conn, analysis_id: int) -> None:
    """③의 판정을 실행: 중간 분석이 stop 이면 멈추고 리포트, 계속이면 아무것도 안 함(다음 묶음 풀이가 이어서 돎). 최종이면 리포트."""
    exp_id, interim, method = conn.execute("SELECT experiment_id, is_interim, method FROM sa_analyses WHERE analysis_id=%s",
                                           (analysis_id,)).fetchone()
    stop = bool(method.get("sequential", {}).get("stop"))
    if interim and not stop:
        return
    if interim and stop:
        stop_experiment(conn, exp_id, "interim")
    enqueue(conn, {"schema_version": 1, "kind": "report", "analysis_id": analysis_id, "report_kinds": ["one_pager", "detail"]})


def on_reports_done(conn, experiment_id: int) -> None:
    conn.execute("UPDATE sa_experiments SET status='done' WHERE experiment_id=%s AND status='running'", (experiment_id,))
