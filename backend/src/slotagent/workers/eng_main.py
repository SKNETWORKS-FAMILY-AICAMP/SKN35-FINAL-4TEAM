"""① 읽기 풀이 작업 하나 처리. deps와 연결 팩터리는 호출자가 명시합니다.

미구현 채점·분석 핸들러나 유료 모델을 기본값으로 실행하지 않습니다.
반복 실행 간격은 배포 진입점이 정합니다.

재시도 규칙: 설정·미지원 오류(ValueError·TypeError·NotImplementedError)는 다시 돌려도 같은
이유로 실패하고, 실행 도중에 난 것이면 실제 모델을 다시 불러 비용만 나갑니다. 그래서 바로
작업을 failed 로 두고 풀이는 pending 으로 남깁니다(원인을 고친 뒤 작업을 다시 등록).
그 밖의 오류와 죽은 워커의 만료 임대는 작업 시도가 max_attempts 에 닿기 전까지만 다시 넣습니다.
"""

from dataclasses import replace
from threading import Event, Thread

from slotagent.common import queue
from slotagent.engine.worker import run_trial

MAX_ATTEMPTS = 3
# 같은 원인으로 반복 실패하는 오류. contracts.ContractError 는 ValueError 라 여기에 들어갑니다.
PERMANENT_ERRORS = (ValueError, TypeError, NotImplementedError)


def should_retry(exc: BaseException, attempts: int, max_attempts: int = MAX_ATTEMPTS) -> bool:
    if isinstance(exc, PERMANENT_ERRORS):
        return False
    return attempts < max_attempts


def run_once(connect, worker_id, *, deps, heartbeat_sec=20, max_attempts=MAX_ATTEMPTS) -> bool:
    """만료 회수 후 풀이 하나를 처리합니다. 작업이 없으면 False, 오류는 원래대로 올립니다."""
    if heartbeat_sec <= 0 or heartbeat_sec > 20:
        # 최소 임대 60초에서도 충분히 일찍 연장하도록 제한합니다.
        raise ValueError("임대 연장 간격은 0초 초과 20초 이하여야 합니다.")
    if max_attempts < 1:
        raise ValueError("최대 시도 횟수는 1 이상이어야 합니다.")
    with connect() as conn:
        queue.reclaim(conn, max_attempts=max_attempts)
        job = queue.lease(conn, worker_id)
        if job is None:
            return False
        stopped, lost = Event(), Event()

        def heartbeat():
            try:
                with connect() as heartbeat_conn:
                    while not stopped.wait(heartbeat_sec):
                        if not queue.renew(heartbeat_conn, job):
                            lost.set()
                            return
            except Exception:
                lost.set()  # DB 연결이 끊기면 다음 단계부터 호출을 막습니다.

        active_deps = replace(deps, cancelled=lambda: lost.is_set() or deps.cancelled())
        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            run_trial(conn, job["payload"]["trial_id"], deps=active_deps, job=job)
        except BaseException as exc:
            try:
                queue.fail(conn, job, retry=should_retry(exc, job["attempts"], max_attempts), error=type(exc).__name__)
            except queue.LeaseLost:
                pass
            except Exception as recovery_error:
                exc.add_note(f"작업 반환 실패({type(recovery_error).__name__}): 임대 만료 뒤 회수가 필요합니다.")
            raise
        finally:
            stopped.set()
            thread.join(timeout=1)
        return True
