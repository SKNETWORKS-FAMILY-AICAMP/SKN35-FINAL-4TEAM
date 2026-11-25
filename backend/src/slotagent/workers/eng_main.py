"""① 풀이·채점 작업 하나 처리. deps와 연결 팩터리는 호출자가 명시합니다.

미구현 채점·분석 핸들러나 유료 모델을 기본값으로 실행하지 않습니다.
반복 실행 간격은 배포 진입점이 정합니다.

재시도 규칙: 설정·미지원 오류(ValueError·TypeError·NotImplementedError)는 다시 돌려도 같은
이유로 실패하고, 실행 도중에 난 것이면 실제 모델을 다시 불러 비용만 나갑니다. 그래서 바로
작업을 failed 로 두고 풀이는 pending 으로 남깁니다(원인 수정 뒤 advance.resume_failed_trial로 수동 재개).
그 밖의 오류와 죽은 워커의 만료 임대는 작업 시도가 max_attempts 에 닿기 전까지만 다시 넣습니다.
수동 재개도 같은 작업의 누적 3회 한도를 유지하고, 소진 종결은 명시적 재개 함수에서 처리합니다.
"""

from contextlib import contextmanager
from dataclasses import replace
from threading import Event, Thread

from psycopg.pq import TransactionStatus

from slotagent.common import queue
from slotagent.engine import advance
from slotagent.engine.loop import RunCancelled, ToolEnvironmentError
from slotagent.engine.worker import run_trial
from slotagent.grading.eng_pipeline import grade

MAX_ATTEMPTS = advance.TRIAL_JOB_MAX_ATTEMPTS
# 같은 원인으로 반복 실패하는 오류. contracts.ContractError 는 ValueError 라 여기에 들어갑니다.
PERMANENT_ERRORS = (ValueError, TypeError, NotImplementedError)


def should_retry(exc: BaseException, attempts: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    if isinstance(exc, PERMANENT_ERRORS):
        return False
    return attempts < max_attempts


@contextmanager
def _heartbeat(connect, job, heartbeat_sec):
    """임대를 별도 연결로 연장합니다. 잃으면 돌려준 Event 가 켜집니다."""
    stopped, lost = Event(), Event()

    def beat():
        try:
            with connect() as heartbeat_conn:
                wait = heartbeat_sec
                while not stopped.wait(wait):
                    try:
                        renewed = queue.renew(heartbeat_conn, job)
                    except queue.TRANSIENT_ERRORS:
                        # 잠금 경합은 임대 상실이 아닙니다. 실제 만료는 renew·guard가 판정합니다.
                        wait = min(heartbeat_sec, 1)
                        continue
                    if not renewed:
                        lost.set()
                        return
                    wait = heartbeat_sec
        except Exception:
            lost.set()  # DB 연결이 끊기면 다음 단계부터 호출을 막습니다.

    thread = Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stopped.set()
        thread.join(timeout=1)


def _give_back(conn, job, exc, label, max_attempts):
    """오류 난 작업을 돌려줍니다. 원래 오류는 호출자가 다시 올립니다."""
    try:
        queue.fail(conn, job, retry=should_retry(exc, job["attempts"], max_attempts), error=label)
    except queue.LeaseLost:
        pass
    except Exception as recovery_error:
        exc.add_note(f"작업 반환 실패({type(recovery_error).__name__}): 임대 만료 뒤 회수가 필요합니다.")


def _check_limits(heartbeat_sec, max_attempts):
    if heartbeat_sec <= 0 or heartbeat_sec > 20:
        # 최소 임대 60초에서도 충분히 일찍 연장하도록 제한합니다.
        raise ValueError("임대 연장 간격은 0초 초과 20초 이하여야 합니다.")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError("최대 시도 횟수는 1 이상 3 이하여야 합니다.")


def grade_once(connect, worker_id, *, classify, heartbeat_sec=20, max_attempts=MAX_ATTEMPTS) -> bool:
    """채점 작업 하나를 처리합니다. ② 판정 함수가 없으면 작업을 빌리지 않습니다 (실패로 굳지 않게)."""
    if not callable(classify):
        raise ValueError("② 판정 함수를 classify로 명시하세요.")
    _check_limits(heartbeat_sec, max_attempts)
    with connect() as conn:
        queue.reclaim(conn, max_attempts=max_attempts, kinds=("grade",))
        job = queue.lease(conn, worker_id, kinds=("grade",))
        if job is None:
            return False
        with _heartbeat(connect, job, heartbeat_sec) as lost:
            try:
                grade(conn, job["payload"]["grading_run_id"], classify=classify, job=job, cancelled=lost.is_set)
            except BaseException as exc:
                if conn.info.transaction_status != TransactionStatus.IDLE:
                    conn.rollback()  # 판정 함수가 열어 둔 트랜잭션이 작업 반환을 막지 않게 합니다.
                _give_back(conn, job, exc, type(exc).__name__, max_attempts)
                raise
        return True


def run_once(connect, worker_id, *, deps, heartbeat_sec=20, max_attempts=MAX_ATTEMPTS, stdio=None) -> bool:
    """만료 회수 후 풀이 하나를 처리합니다. 작업이 없으면 False, 오류는 원래대로 올립니다."""
    _check_limits(heartbeat_sec, max_attempts)
    with connect() as conn:
        cleanup = getattr(stdio, "reclaim_expired", None)
        queue.reclaim(
            conn,
            max_attempts=max_attempts,
            kinds=("run_trial",),  # 다른 종류는 그 워커가 자기 상한으로 회수합니다.
            cleanup_expired=(lambda jobs: cleanup(jobs, conn=conn)) if cleanup is not None else None,
        )
        job = queue.lease(conn, worker_id)
        if job is None:
            return False
        with _heartbeat(connect, job, heartbeat_sec) as lost:
            active_deps = replace(deps, cancelled=lambda: lost.is_set() or deps.cancelled())
            try:
                run_trial(
                    conn,
                    job["payload"]["trial_id"],
                    deps=active_deps,
                    job=job,
                    stdio=stdio,
                    cancel_signals=(lost.is_set,),
                )
            except BaseException as exc:
                label = type(exc).__name__
                if isinstance(exc, ToolEnvironmentError):
                    label = exc.reason
                elif isinstance(exc, RunCancelled) and lost.is_set():
                    label = "env_worker_lost"
                _give_back(conn, job, exc, label, max_attempts)
                raise
        return True
