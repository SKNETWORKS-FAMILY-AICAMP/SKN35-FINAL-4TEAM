"""[①] 다음 단계로 넘기기 — 실험 상태 바꾸기와 다음 작업 넣기는 모두 여기서만 (11/22 검토 1·2·5·6).

다른 역할은 상태를 직접 바꾸지 않는다. ③은 판정만 남기고(analyses.method.sequential.stop), ①이 그걸 읽고 실행한다.

실험 상태 (experiments.status)
    draft ──lock_experiment()──▶ locked ──mark_running()──▶ running ──on_reports_done()──▶ done (종료 게이트: completion_blockers 가 빌 때만)
                                                            ├─ check_budget() 예산 도달 ───▶ stopped (stop_reason='budget')
                                                            ├─ 중간 분석 stop=true ───────▶ stopped (stop_reason='interim')
                                                            ├─ 사용자 멈춤 (POST .../stop) ─▶ stopped (stop_reason='user')
                                                            └─ 작업이 끝내 실패 + 사람이 포기 ─▶ failed (job_failed, abandon_failed_experiment)
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

from slotagent.common import checks, contracts, queue
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
    with queue.transaction(conn):
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
    """중단 상태·풀이·작업을 상한 있는 같은 트랜잭션에서 처리합니다."""
    with queue.transaction(conn):
        return _stop_experiment(conn, experiment_id, reason)


def _stop_experiment(conn, experiment_id: int, reason: str) -> int:
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
                        WHERE kind='run_trial' AND status='queued' AND payload->>'trial_id' = ANY(%s)""", ([str(i) for i in ids],))
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
    """채점 실행 행으로 재전달을 직렬화합니다. 기존 작업은 상태와 무관하게 재사용합니다."""
    with queue.transaction(conn):
        exp_id, upto = conn.execute(
            "SELECT experiment_id, upto_batch_no FROM sa_grading_runs WHERE grading_run_id=%s FOR UPDATE",
            (grading_run_id,),
        ).fetchone()
        existing = _event_job(conn, "analyze", "grading_run_id", grading_run_id)
        if existing is not None:
            return existing
        last = _one(conn, "SELECT max(batch_no) FROM sa_trials WHERE experiment_id=%s", exp_id)
        interim = upto is not None and upto < last
        p = {"schema_version": 1, "kind": "analyze", "grading_run_id": grading_run_id, "is_interim": interim}
        if interim:
            p["batch_no"] = upto
        return enqueue(conn, p)


def resume_failed_grading(conn, grading_run_id: int) -> bool:
    """사람이 원인을 고친 뒤 failed 로 끝난 grade 작업을 다시 넣습니다. 저장한 규칙·채점 결과는 이어서 씁니다."""
    with queue.transaction(conn):
        done = _one(conn, "SELECT finished_at IS NOT NULL FROM sa_grading_runs WHERE grading_run_id=%s FOR UPDATE",
                    grading_run_id)
        if done is None:
            raise ValueError("채점 실행이 없습니다.")
        if done:
            return False
        job = _event_job(conn, "grade", "grading_run_id", grading_run_id)
        return job is not None and _one(
            conn, "UPDATE sa_jobs SET status='queued', attempts=0, updated_at=now() WHERE job_id=%s AND status='failed' RETURNING job_id",
            job) is not None


def _event_job(conn, kind: str, field: str, event_id: int) -> int | None:
    """호출자는 대응하는 부모 행을 같은 트랜잭션에서 잠근 뒤 조회합니다."""
    return _one(conn, """SELECT job_id FROM sa_jobs WHERE kind=%s AND payload->>%s=%s
                         ORDER BY job_id LIMIT 1""", kind, field, str(event_id))


def on_analysis_done(conn, analysis_id: int) -> None:
    """③의 판정을 실행: 중간 분석이 stop 이면 멈추고 리포트, 계속이면 아무것도 안 함(다음 묶음 풀이가 이어서 돎). 최종이면 리포트."""
    with queue.transaction(conn):
        exp_id, interim, method = conn.execute(
            "SELECT experiment_id, is_interim, method FROM sa_analyses WHERE analysis_id=%s FOR UPDATE",
            (analysis_id,),
        ).fetchone()
        stop = bool(method.get("sequential", {}).get("stop"))
        if interim and not stop:
            return
        if _event_job(conn, "report", "analysis_id", analysis_id) is not None:
            return
        if interim and stop:
            stop_experiment(conn, exp_id, "interim")
        enqueue(conn, {"schema_version": 1, "kind": "report", "analysis_id": analysis_id, "report_kinds": list(REPORT_KINDS)})


REPORT_KINDS = ("one_pager", "detail")


def completion_blockers(conn, experiment_id: int) -> list[str]:
    """정상 완료(done)를 막는 이유. 비면 끝내도 됨. 호출자가 실험 행을 잠근 뒤 부르면 결과가 바뀌지 않습니다.

    trials_unfinished  대기·실행 중 풀이가 있음 (작업이 끝내 실패해 pending 으로 남은 것 포함)
    trials_cancelled   멈추지 않은 실험에 취소된 풀이가 있음
    analysis_missing   전체를 채점한 최종 분석이 없음 (일부만 채점한 이른 분석은 세지 않음)
    reports_missing    그 분석의 리포트 두 종류가 다 있지 않음
    """
    blockers = []
    unfinished, cancelled = conn.execute(
        """SELECT count(*) FILTER (WHERE status IN ('pending','running')),
                  count(*) FILTER (WHERE status='cancelled') FROM sa_trials WHERE experiment_id=%s""",
        (experiment_id,),
    ).fetchone()
    if unfinished:
        blockers.append("trials_unfinished")
    if cancelled:
        blockers.append("trials_cancelled")
    # 채점 범위가 전체이고, 지금 유효한 풀이가 그 채점에 하나도 빠지지 않은 최종 분석
    analyses = [
        r[0]
        for r in conn.execute(
            """SELECT a.analysis_id FROM sa_analyses a JOIN sa_grading_runs g USING (grading_run_id)
               WHERE a.experiment_id=%s AND NOT a.is_interim AND g.finished_at IS NOT NULL
                 AND (g.upto_batch_no IS NULL OR g.upto_batch_no >=
                      (SELECT max(batch_no) FROM sa_trials m WHERE m.experiment_id=a.experiment_id))
                 AND NOT EXISTS (
                   SELECT 1 FROM sa_effective_trials t WHERE t.experiment_id=a.experiment_id AND t.run_outcome<>'env_error'
                     AND NOT EXISTS (SELECT 1 FROM sa_trial_grades tg
                                     WHERE tg.grading_run_id=g.grading_run_id AND tg.trial_id=t.trial_id))
               ORDER BY a.analysis_id""",
            (experiment_id,),
        )
    ]
    if not analyses:
        blockers.append("analysis_missing")
    elif not conn.execute(
        """SELECT 1 FROM sa_reports WHERE experiment_id=%s AND analysis_id=ANY(%s) AND kind=ANY(%s)
           GROUP BY analysis_id HAVING count(DISTINCT kind)=%s LIMIT 1""",
        (experiment_id, analyses, list(REPORT_KINDS), len(REPORT_KINDS)),
    ).fetchone():
        blockers.append("reports_missing")
    return blockers


def on_reports_done(conn, experiment_id: int) -> list[str]:
    """종료 게이트: 막는 이유가 없을 때만 running → done. 돌려주는 값은 막은 이유(끝냈거나 할 일이 없으면 []).

    막혀도 오류로 올리지 않습니다. 남은 풀이가 끝나면 채점·분석·리포트가 다시 이어져 여기로 돌아옵니다.
    리포트 저장과 같은 트랜잭션에서 불러도 됩니다. 실험을 가리키는 행을 넣을 때의 외래키 잠금과 부딪히지 않게
    FOR NO KEY UPDATE 로 잠급니다. 상태를 바꾸는 쪽끼리는 그대로 서로 기다립니다.
    """
    with queue.transaction(conn):
        status = _one(conn, "SELECT status FROM sa_experiments WHERE experiment_id=%s FOR NO KEY UPDATE", experiment_id)
        if status is None:
            raise ValueError("실험이 없습니다.")
        if status != "running":
            return []
        blockers = completion_blockers(conn, experiment_id)
        if not blockers:
            conn.execute("UPDATE sa_experiments SET status='done' WHERE experiment_id=%s", (experiment_id,))
        return blockers


# 이 실험에서 아직 안 끝난 일(풀이·채점·분석·리포트)마다 가장 최근 작업만 봅니다. 앞 작업이 실패했어도
# 뒤 작업이 이어받았거나 결과가 이미 있으면 회복한 것입니다. 같은 행을 다시 넣는 재개는 그 행의 상태가 바뀝니다.
# payload 는 글자로 견줍니다. 숫자로 바꾸면 다른 실험의 잘못된 payload 하나가 전체를 막습니다.
_LAST_FAILED_JOB = """
WITH events(kind, event) AS (
    SELECT 'run_trial', trial_id::text FROM sa_trials WHERE experiment_id=%(e)s AND status='pending'
    UNION ALL
    SELECT 'grade', grading_run_id::text FROM sa_grading_runs WHERE experiment_id=%(e)s AND finished_at IS NULL
    UNION ALL
    SELECT 'analyze', grading_run_id::text FROM sa_grading_runs g WHERE experiment_id=%(e)s
      AND NOT EXISTS (SELECT 1 FROM sa_analyses a WHERE a.grading_run_id=g.grading_run_id AND a.experiment_id=%(e)s)
    UNION ALL
    SELECT 'report', analysis_id::text FROM sa_analyses a WHERE experiment_id=%(e)s
      AND (SELECT count(DISTINCT r.kind) FROM sa_reports r WHERE r.analysis_id=a.analysis_id
             AND r.experiment_id=%(e)s AND r.kind=ANY(%(kinds)s)) < cardinality(%(kinds)s)
), latest AS (
    SELECT DISTINCT ON (kind, event) j.status FROM (
        SELECT job_id, kind, status, payload->>(CASE kind WHEN 'run_trial' THEN 'trial_id'
                 WHEN 'report' THEN 'analysis_id' ELSE 'grading_run_id' END) AS event
        FROM sa_jobs WHERE kind IN ('run_trial','grade','analyze','report')) j
    JOIN events USING (kind, event) ORDER BY kind, event, j.job_id DESC
)
SELECT 1 FROM latest WHERE status='failed' LIMIT 1"""


def abandon_failed_experiment(conn, experiment_id: int) -> int:
    """사람이 재개를 포기할 때만 부릅니다. 끝내 실패한 작업이 있는 실험을 failed 로 끝내고 남은 풀이·작업을 취소합니다.

    기록·비용·이미 끝난 풀이는 남깁니다. 실패한 작업이 없으면 거절합니다(일반 멈춤은 stop_experiment).
    이미 failed 면 아무것도 하지 않고 0. 돌려주는 값: 취소한 풀이 수.
    """
    with queue.transaction(conn):
        status = _one(conn, "SELECT status FROM sa_experiments WHERE experiment_id=%s FOR NO KEY UPDATE", experiment_id)
        if status is None:
            raise ValueError("실험이 없습니다.")
        if status == "failed":
            return 0
        if status not in {"locked", "running"}:
            raise ValueError("진행 중인 실험만 실패로 끝낼 수 있습니다.")
        failed = conn.execute(_LAST_FAILED_JOB, {"e": experiment_id, "kinds": list(REPORT_KINDS)}).fetchone()
        if failed is None:
            raise ValueError("끝내 실패한 작업이 없습니다. 멈추려면 stop_experiment 를 쓰세요.")
        return _stop_experiment(conn, experiment_id, "job_failed")
