"""① 읽기 실행 코어를 제품 DB와 임대 작업에 연결합니다.

첫 단계는 명시적으로 주입한 모델·읽기 도구만 실행합니다. 기본값으로 실제 모델을 과금 호출하지 않습니다.
실행 중 DB 트랜잭션을 붙잡지 않고 시작/소유권 확인/최종 저장만 짧게 처리합니다.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal

from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from slotagent.common import contracts, queue
from slotagent.common.hashing import canonical_hash
from slotagent.common.llm import Price
from slotagent.common.snapshot import HARNESS_VERSION, trial_seed
from slotagent.engine import advance
from slotagent.engine.loop import Dependencies, RunCancelled, RunResult, run_agent


def run_trial(conn, trial_id: int, *, deps: Dependencies | None = None, job: dict | None = None) -> RunResult | None:
    """풀이 하나를 시작하고 결과와 다음 단계 요청을 저장합니다.

    외부 트랜잭션이 없는 연결을 넘겨야 합니다. 완료된 풀이·예산 중단은 아무것도 실행하지 않습니다.
    큐 실행은 job을 넘겨 임대·시도 토큰을 함께 검사합니다. job 생략은 독립 실행·검증용입니다.
    """
    if deps is None:
        raise NotImplementedError("모델과 읽기 도구 어댑터를 deps로 명시하세요. Docker 연결은 다음 단계입니다.")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("실행 시작 전 외부 트랜잭션을 끝내고 독립된 연결을 넘기세요.")
    with conn.transaction():
        if job is not None:
            if job["kind"] != "run_trial" or job["payload"]["trial_id"] != trial_id:
                raise ValueError("풀이와 작업이 일치하지 않습니다.")
            queue.guard(conn, job)
        conn.execute(
            """SELECT e.experiment_id FROM sa_experiments e JOIN sa_trials t USING (experiment_id)
               WHERE t.trial_id=%s FOR UPDATE OF e""",
            (trial_id,),
        )
        with conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                """SELECT t.*, ec.config_snapshot, ec.config_hash, k.prompt, k.seed, e.prereg, e.status AS exp_status
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
        if snap.get("tool_search"):
            raise NotImplementedError("검색 후보 실행은 다음 단계입니다.")
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
        return _execute_trial(conn, row, snap, price_id, price, deps, job)
    except BaseException as exc:
        # 모델·도구·최종 저장 어디서 실패해도 현재 시도만 반환합니다.
        # 자동 재호출은 하지 않습니다. 호출자가 원인을 고친 뒤 다시 실행합니다.
        try:
            if job is None:
                _release_attempt(conn, trial_id, row["attempt"], row["experiment_id"])
            else:
                with conn.transaction():
                    queue.guard(conn, job)
                    _release_attempt(conn, trial_id, row["attempt"], row["experiment_id"])
        except queue.LeaseLost:
            pass  # 만료 뒤의 상태 복구는 회수 워커만 담당합니다.
        except Exception as recovery_error:
            exc.add_note(f"풀이 상태 복구 실패({type(recovery_error).__name__}): DB 연결과 현재 attempt를 확인하세요.")
        raise


def _release_attempt(conn, trial_id, attempt, experiment_id):
    with conn.transaction():
        status = conn.execute(
            "SELECT status FROM sa_experiments WHERE experiment_id=%s FOR UPDATE", (experiment_id,)
        ).fetchone()[0]
        released = conn.execute(
            """UPDATE sa_trials SET status='pending', attempt=attempt+1, started_at=NULL
               WHERE trial_id=%s AND status='running' AND attempt=%s RETURNING trial_id""",
            (trial_id, attempt),
        ).fetchone()
        if released and status in {"stopped", "failed"}:
            conn.execute("UPDATE sa_trials SET status='cancelled' WHERE trial_id=%s", (trial_id,))


def _execute_trial(conn, row, snap, price_id, price, deps, job):
    trial_id = row["trial_id"]

    def cancelled() -> bool:
        if deps.cancelled():
            return True
        with conn.transaction():
            if job is not None:
                try:
                    queue.guard(conn, job)
                except queue.LeaseLost:
                    return True
            current = conn.execute("SELECT status, attempt FROM sa_trials WHERE trial_id=%s", (trial_id,)).fetchone()
        return current != ("running", row["attempt"])

    result = run_agent(
        snap,
        row["prompt"],
        trial_seed(row["seed"], row["rep"]),
        replace(deps, price=price, cancelled=cancelled),
        prereg=row["prereg"],
    )
    trace = copy.deepcopy(result.trace)
    trace.update(trial_id=trial_id, attempt=row["attempt"])
    contracts.validate("trace", trace)
    with conn.transaction():
        if job is not None:
            queue.guard(conn, job)
        conn.execute(
            "SELECT experiment_id FROM sa_experiments WHERE experiment_id=%s FOR UPDATE", (row["experiment_id"],)
        )
        current = conn.execute(
            "SELECT status, attempt FROM sa_trials WHERE trial_id=%s FOR UPDATE", (trial_id,)
        ).fetchone()
        if current != ("running", row["attempt"]):
            raise RunCancelled("현재 시도의 소유권을 잃어 결과를 저장하지 않습니다.")
        total_cost = Decimal(0)
        for span in trace["spans"]:
            attrs = dict(span.get("attributes", {}))
            conn.execute(
                """INSERT INTO sa_spans(trial_id,attempt,seq,kind,name,started_at,duration_sec,wait_sec,
                   in_tokens,out_tokens,output,tool_args,tool_result,error,attributes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
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
            )
            if span["kind"] == "llm" and "in_tokens" in span:
                total_cost += Decimal(attrs["cost_krw"])
                conn.execute(
                    """INSERT INTO sa_cost_ledger(source,ref_id,experiment_id,model,in_tokens,out_tokens,cost_krw,price_setting_id)
                       VALUES ('trial',%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        trial_id,
                        row["experiment_id"],
                        span["name"],
                        span["in_tokens"],
                        span["out_tokens"],
                        Decimal(attrs["cost_krw"]),
                        price_id,
                    ),
                )
        usage = trace["usage"]
        conn.execute(
            """UPDATE sa_trials SET status=%s,run_outcome=%s,outcome_reason=%s,finished_at=now(),final_answer=%s,
               in_tokens=%s,out_tokens=%s,tool_desc_tokens=%s,cost_krw=%s,llm_sec=%s,tool_sec=%s,wait_sec=%s,api_retries=%s
               WHERE trial_id=%s AND attempt=%s""",
            (
                "finished" if result.outcome == "completed" else "error",
                result.outcome,
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
    return RunResult(trace)
