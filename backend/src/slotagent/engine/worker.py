"""① 읽기 실행 코어를 제품 DB와 임대 작업에 연결합니다.

모델은 명시적으로 주입하고 읽기 도구는 deps 또는 신뢰한 stdio 설정으로 연결합니다.
stdio 설정이 있으면 풀이마다 새 세션을 열어 모델 호출 전에 검사하고 최종 저장 전에 닫습니다.
기본값으로 실제 모델을 과금 호출하지 않습니다.
실행 중 DB 트랜잭션을 붙잡지 않고 시작·소유권 확인·응답별 비용·최종 저장을 짧게 처리합니다.
"""

from __future__ import annotations

import copy
import time
from contextlib import ExitStack
from dataclasses import replace
from decimal import Decimal

from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from slotagent.common import contracts, queue
from slotagent.common.db_names import col
from slotagent.common.hashing import canonical_hash
from slotagent.common.llm import Price, add_cost
from slotagent.common.snapshot import HARNESS_VERSION, trial_seed
from slotagent.engine import advance
from slotagent.engine.costs import record_trial_cost
from slotagent.engine.loop import Dependencies, RunCancelled, RunResult, run_agent

# 시도 사이 대기(초). 시도마다 잠금 대기 상한이 따로 있습니다.
FINAL_SAVE_DELAYS = (0.5, 1, 2, 4)


def run_trial(
    conn,
    trial_id: int,
    *,
    deps: Dependencies | None = None,
    job: dict | None = None,
    stdio=None,
    cancel_signals=(),
) -> RunResult | None:
    """풀이 하나를 시작하고 결과와 다음 단계 요청을 저장합니다.

    외부 트랜잭션이 없는 연결을 넘겨야 합니다. 완료된 풀이·예산 중단은 아무것도 실행하지 않습니다.
    큐 실행은 job을 넘겨 임대·시도 토큰을 함께 검사합니다. job 생략은 독립 실행·검증용입니다.
    """
    if deps is None:
        raise NotImplementedError("모델과 읽기 도구 어댑터를 deps로 명시하세요. Docker 연결은 다음 단계입니다.")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("실행 시작 전 외부 트랜잭션을 끝내고 독립된 연결을 넘기세요.")
    with queue.transaction(conn):
        if job is not None:
            if job["kind"] != "run_trial" or job["payload"]["trial_id"] != trial_id:
                raise ValueError("풀이와 작업이 일치하지 않습니다.")
            queue.guard(conn, job)
        conn.execute(
            """SELECT e.experiment_id FROM sa_experiments e JOIN sa_trials t USING (experiment_id)
               WHERE t.trial_id=%s FOR NO KEY UPDATE OF e""",
            (trial_id,),
        )
        with conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                """SELECT t.*, ec.config_snapshot, ec.config_hash, k.prompt, k.seed, k.confirmation, k.write_scenario, e.prereg, e.status AS exp_status
                   FROM sa_trials t JOIN sa_experiment_candidates ec USING (experiment_candidate_id)
                   JOIN sa_tasks k USING (task_id) JOIN sa_experiments e ON e.experiment_id=t.experiment_id
                   WHERE t.trial_id=%s FOR UPDATE OF t""",
                (trial_id,),
            ).fetchone()
        if row is None:
            raise ValueError("풀이가 없습니다.")
        if row["status"] in {"finished", "error", "cancelled"} or row["exp_status"] not in {"locked", "running"}:
            if job is not None:
                queue.finish(conn, job)
            return None
        if row["status"] != "pending":
            raise ValueError("이미 실행 중인 풀이는 임대 회수 절차 없이 다시 시작할 수 없습니다.")
        snap = contracts.validate("config_snapshot", row["config_snapshot"])
        if canonical_hash(snap) != row["config_hash"]:
            raise ValueError("실행 스냅샷의 해시가 일치하지 않습니다.")
        if row["record_source"] != "platform":
            raise ValueError("러너·고객 기록은 전용 수신 경로를 사용하세요.")
        price_row = conn.execute(
            """SELECT setting_id, value FROM sa_settings WHERE scope='global' AND scope_ref='' AND key=%s
               AND valid_from<=now() ORDER BY valid_from DESC, setting_id DESC LIMIT 1""",
            ("price." + snap["model"]["name"],),
        ).fetchone()
        price_id, price = None, Price()
        if price_row:
            price_id, value = price_row
            contracts.validate("settings", value, part="price")
            price = Price(Decimal(str(value["in_per_1k_krw"])), Decimal(str(value["out_per_1k_krw"])))
        elif not deps.model.is_fake:
            raise ValueError("실제 모델 호출 전에 settings 가격표를 등록하세요.")
        if not advance.check_budget(conn, row["experiment_id"]):
            if job is not None:
                queue.finish(conn, job)
            return None
        advance.mark_running(conn, row["experiment_id"])
        conn.execute(
            "UPDATE sa_trials SET status='running', started_at=now(), harness_version=%s WHERE trial_id=%s",
            (HARNESS_VERSION, trial_id),
        )

    try:
        return _execute_trial(conn, row, snap, price_id, price, deps, job, stdio, cancel_signals)
    except BaseException as exc:
        # 모델·도구·최종 저장 어디서 실패해도 현재 시도만 반환합니다.
        # 자동 재호출은 하지 않습니다. 호출자가 원인을 고친 뒤 다시 실행합니다.
        try:
            if job is None:
                _release_attempt(conn, trial_id, row["attempt"], row["experiment_id"])
            else:
                with queue.transaction(conn):
                    queue.guard(conn, job)
                    _release_attempt(conn, trial_id, row["attempt"], row["experiment_id"])
        except queue.LeaseLost:
            pass  # 만료 뒤의 상태 복구는 회수 워커만 담당합니다.
        except Exception as recovery_error:
            exc.add_note(f"풀이 상태 복구 실패({type(recovery_error).__name__}): DB 연결과 현재 attempt를 확인하세요.")
        raise


def _release_attempt(conn, trial_id, attempt, experiment_id):
    with queue.transaction(conn):
        status = conn.execute(
            "SELECT status FROM sa_experiments WHERE experiment_id=%s FOR NO KEY UPDATE", (experiment_id,)
        ).fetchone()[0]
        released = conn.execute(
            """UPDATE sa_trials SET status='pending', attempt=attempt+1, started_at=NULL
               WHERE trial_id=%s AND status='running' AND attempt=%s RETURNING trial_id""",
            (trial_id, attempt),
        ).fetchone()
        if released and status in {"stopped", "failed"}:
            conn.execute("UPDATE sa_trials SET status='cancelled' WHERE trial_id=%s", (trial_id,))


def _execute_trial(conn, row, snap, price_id, price, deps, job, stdio=None, cancel_signals=()):
    trial_id = row["trial_id"]

    def cancelled() -> bool:
        if deps.cancelled():
            return True
        with queue.transaction(conn):
            if job is not None:
                try:
                    queue.guard(conn, job)
                except queue.LeaseLost:
                    return True
            current = conn.execute(
                """SELECT t.status,t.attempt,e.status FROM sa_trials t JOIN sa_experiments e USING (experiment_id)
                   WHERE t.trial_id=%s""",
                (trial_id,),
            ).fetchone()
        return current is None or current[:2] != ("running", row["attempt"]) or current[2] not in {"locked", "running"}

    def model_received(span):
        # 임대 상실 뒤 도착한 응답도 비용은 보존합니다. 결과 펜싱과 분리합니다.
        record_trial_cost(
            conn,
            trial_id=trial_id,
            attempt=row["attempt"],
            span=span,
            experiment_id=row["experiment_id"],
            price_setting_id=price_id,
        )
        deps.on_model_span(span)

    with ExitStack() as stack:
        active = replace(deps, price=price, cancelled=cancelled, on_model_span=model_received)
        if stdio is not None:
            execution = {
                "trial_id": trial_id,
                "attempt": row[col("trials", "attempt")],
                "job_id": job[col("jobs", "id")] if job else None,
                "lease_attempt": job[col("jobs", "attempts")] if job else None,
            }
            call_tool = stack.enter_context(
                stdio.open(snap, cancel_signals=(deps.cancelled, *cancel_signals), execution=execution)
            )
            active = replace(active, call_tool=call_tool)
        result = run_agent(
            snap,
            row["prompt"],
            trial_seed(row["seed"], row["rep"]),
            active,
            prereg=row["prereg"],
            confirmation=row["confirmation"],
            write_scenario=row["write_scenario"],
        )
    trace = copy.deepcopy(result.trace)
    trace.update(trial_id=trial_id, attempt=row["attempt"])
    contracts.validate("trace", trace)
    _save_with_retry(conn, row, trace, result.outcome, price_id, job)
    return RunResult(trace)


def _save_with_retry(conn, row, trace, outcome, price_id, job):
    """일시 잠금이면 저장 트랜잭션만 다시 시도합니다. 모델·도구는 다시 부르지 않습니다.

    실패한 시도는 모두 롤백되고, 시도마다 임대·실험 상태·attempt를 다시 검사합니다.
    상한을 넘으면 원래 오류를 올려 기존 작업 재시도 규칙을 따릅니다.
    """
    for delay in (*FINAL_SAVE_DELAYS, None):
        try:
            return _save_result(conn, row, trace, outcome, price_id, job)
        except queue.TRANSIENT_ERRORS:
            if delay is None:
                raise
        time.sleep(delay)


def _save_result(conn, row, trace, outcome, price_id, job):
    """결과·trace·비용 확인·다음 단계·작업 완료를 한 트랜잭션으로 저장합니다."""
    trial_id = row["trial_id"]
    with queue.transaction(conn):
        if job is not None:
            queue.guard(conn, job)
        exp_status = conn.execute(
            "SELECT status FROM sa_experiments WHERE experiment_id=%s FOR NO KEY UPDATE", (row["experiment_id"],)
        ).fetchone()[0]
        if exp_status not in {"locked", "running"}:
            raise RunCancelled("실험이 중단되어 결과를 저장하지 않습니다.")
        current = conn.execute(
            "SELECT status, attempt FROM sa_trials WHERE trial_id=%s FOR UPDATE", (trial_id,)
        ).fetchone()
        if current != ("running", row["attempt"]):
            raise RunCancelled("현재 시도의 소유권을 잃어 결과를 저장하지 않습니다.")
        total_cost, span_ids = Decimal(0), {}
        for span in trace["spans"]:
            attrs = dict(span.get("attributes", {}))
            span_ids[span["seq"]] = conn.execute(
                """INSERT INTO sa_spans(trial_id,attempt,seq,kind,name,started_at,duration_sec,wait_sec,
                   in_tokens,out_tokens,output,tool_args,tool_result,error,attributes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING span_id""",
                (
                    trial_id,
                    row["attempt"],
                    span["seq"],
                    span["kind"],
                    span["name"],
                    span["started_at"],
                    span["duration_sec"],
                    span.get("wait_sec", 0),
                    span.get("in_tokens"),
                    span.get("out_tokens"),
                    span.get("output"),
                    Jsonb(span["tool_args"]) if "tool_args" in span else None,
                    span.get("tool_result"),
                    span.get("error"),
                    Jsonb(attrs),
                ),
            ).fetchone()[0]
            if span["kind"] == "llm" and "in_tokens" in span:
                total_cost = add_cost(total_cost, Decimal(attrs["cost_krw"]))
                record_trial_cost(
                    conn,
                    trial_id=trial_id,
                    attempt=row["attempt"],
                    span=span,
                    experiment_id=row["experiment_id"],
                    price_setting_id=price_id,
                )
        # DB 트리거가 running 상태와 현재 시도의 span인지 확인하므로 풀이 상태를 바꾸기 전에 넣습니다.
        for intent in trace["write_intents"]:
            conn.execute(
                """INSERT INTO sa_write_intents(trial_id,span_id,tool_name,payload,in_rule_list,user_confirmed)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    trial_id,
                    span_ids[intent["span_seq"]],
                    intent["tool_name"],
                    Jsonb(intent["payload"]),
                    intent["in_rule_list"],
                    intent["user_confirmed"],
                ),
            )
        usage = trace["usage"]
        conn.execute(
            """UPDATE sa_trials SET status=%s,run_outcome=%s,outcome_reason=%s,finished_at=now(),final_answer=%s,
               in_tokens=%s,out_tokens=%s,tool_desc_tokens=%s,cost_krw=%s,llm_sec=%s,tool_sec=%s,wait_sec=%s,api_retries=%s
               WHERE trial_id=%s AND attempt=%s""",
            (
                "finished" if outcome == "completed" else "error",
                outcome,
                trace.get("outcome_reason"),
                trace["final_answer"],
                usage["in_tokens"],
                usage["out_tokens"],
                usage.get("tool_desc_tokens"),
                total_cost,
                usage["llm_sec"],
                usage["tool_sec"],
                usage["wait_sec"],
                usage["api_retries"],
                trial_id,
                row["attempt"],
            ),
        )
        advance.on_trial_finished(conn, trial_id)
        if job is not None:
            queue.finish(conn, job)
