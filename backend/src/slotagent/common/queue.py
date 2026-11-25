"""① DB 큐 임대. 전용 연결에서 짧은 트랜잭션을 쓰며 attempts와 임대마다 새로 만드는 leased_by를 토큰으로 씁니다.

만료 뒤 연장·완료·실패를 거부합니다. 풀이 복구와 작업 반환은 같은 트랜잭션으로 처리합니다.
재시도 상한은 호출자가 정합니다(fail 의 retry, reclaim 의 max_attempts).
"""

from contextlib import contextmanager
from uuid import uuid4

from psycopg import errors
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from slotagent.common import contracts

SQL_LOCK_TIMEOUT_MS = 1000
SQL_STATEMENT_TIMEOUT_MS = 5000
# 서버가 롤백을 확정한 일시 오류. 커밋 여부를 모르는 연결 오류는 넣지 않습니다.
TRANSIENT_ERRORS = (errors.LockNotAvailable, errors.QueryCanceled, errors.DeadlockDetected)


@contextmanager
def transaction(conn, *, lock_ms=None, statement_ms=None):
    """중첩 성공·롤백 모두 기존 설정을 복원하는 짧은 DB 작업 상한입니다."""
    lock_ms = SQL_LOCK_TIMEOUT_MS if lock_ms is None else lock_ms
    statement_ms = SQL_STATEMENT_TIMEOUT_MS if statement_ms is None else statement_ms
    if any(type(value) is not int or value < 1 for value in (lock_ms, statement_ms)):
        raise ValueError("SQL 상한은 양의 정수 밀리초여야 합니다.")
    with conn.transaction():
        previous = conn.execute(
            "SELECT current_setting('lock_timeout'),current_setting('statement_timeout')"
        ).fetchone()
        conn.execute(
            "SELECT set_config('lock_timeout',%s,true),set_config('statement_timeout',%s,true)",
            (f"{lock_ms}ms", f"{statement_ms}ms"),
        )
        yield
        conn.execute("SELECT set_config('lock_timeout',%s,true),set_config('statement_timeout',%s,true)", previous)


class LeaseLost(RuntimeError):
    """이미 만료되거나 다른 워커에게 넘어간 작업입니다."""


def _idle(conn):
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("큐에는 외부 트랜잭션이 없는 전용 연결을 넘기세요.")


def _duration(conn, seconds):
    if seconds is None:
        row = conn.execute(
            """SELECT value FROM sa_settings WHERE scope='global' AND scope_ref='' AND key='queue.lease_sec'
               AND valid_from<=now() ORDER BY valid_from DESC, setting_id DESC LIMIT 1"""
        ).fetchone()
        seconds = row[0] if row else 600
    contracts.validate("settings", seconds, part="queue.lease_sec")
    return seconds


def lease(conn, worker_id: str, *, kinds=("run_trial",), lease_sec=None) -> dict | None:
    """우선순위순으로 작업 하나를 빌립니다. 잠긴 행은 건너뜁니다."""
    _idle(conn)
    if not worker_id.strip() or not kinds:
        raise ValueError("워커 이름과 처리할 종류가 필요합니다.")
    # 수동 재개가 attempts를 0으로 되돌려도 같은 워커의 옛 임대가 되살아나지 않게 합니다.
    owner = f"{worker_id}#{uuid4().hex}"
    with transaction(conn):
        seconds = _duration(conn, lease_sec)
        with conn.cursor(row_factory=dict_row) as cur:
            job = cur.execute(
                """WITH ready AS (
                     SELECT job_id FROM sa_jobs WHERE status='queued' AND kind=ANY(%s)
                     ORDER BY priority DESC, job_id FOR UPDATE SKIP LOCKED LIMIT 1
                   ) UPDATE sa_jobs j SET status='leased', attempts=attempts+1, leased_by=%s,
                     lease_until=clock_timestamp()+%s*interval '1 second', updated_at=clock_timestamp()
                   FROM ready WHERE j.job_id=ready.job_id RETURNING j.*""",
                (list(kinds), owner, seconds),
            ).fetchone()
        if job:
            contracts.validate("job_payload", job["payload"])
        return job


def guard(conn, job: dict) -> None:
    """호출자 트랜잭션에서 임대를 잠가 최종 저장·회수의 순서를 고정합니다."""
    if conn.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("임대 검사와 결과 저장을 같은 트랜잭션으로 감싸세요.")
    row = conn.execute(
        """SELECT job_id FROM sa_jobs WHERE job_id=%s AND status='leased' AND attempts=%s
           AND leased_by=%s AND lease_until>clock_timestamp() FOR UPDATE""",
        (job["job_id"], job["attempts"], job["leased_by"]),
    ).fetchone()
    # 행 잠금을 기다리는 동안 시간이 지날 수 있어 획득 뒤에도 만료를 확인합니다.
    if (
        not row
        or not conn.execute(
            "SELECT lease_until>clock_timestamp() FROM sa_jobs WHERE job_id=%s", (job["job_id"],)
        ).fetchone()[0]
    ):
        raise LeaseLost("작업 임대가 만료됐거나 소유권을 잃었습니다.")


def renew(conn, job: dict, *, lease_sec=None) -> bool:
    _idle(conn)
    with transaction(conn):
        seconds = _duration(conn, lease_sec)
        try:
            guard(conn, job)
        except LeaseLost:
            return False
        conn.execute(
            """UPDATE sa_jobs SET lease_until=clock_timestamp()+%s*interval '1 second', updated_at=clock_timestamp()
               WHERE job_id=%s""",
            (seconds, job["job_id"]),
        )
        return True


def finish(conn, job: dict) -> None:
    """호출자 트랜잭션에서 결과 저장과 함께 완료합니다."""
    guard(conn, job)
    _return_job(conn, job, "done")


def _return_job(conn, job, status, error=None):
    conn.execute(
        """UPDATE sa_jobs SET status=%s, leased_by=NULL, lease_until=NULL, last_error=%s,
           updated_at=clock_timestamp() WHERE job_id=%s""",
        (status, error, job["job_id"]),
    )


def _recover_trial(conn, job):
    if job["kind"] != "run_trial":
        return "queued"
    trial_id = job["payload"]["trial_id"]
    exp = conn.execute("SELECT experiment_id FROM sa_trials WHERE trial_id=%s", (trial_id,)).fetchone()
    if not exp:
        raise ValueError("작업이 가리키는 풀이가 없습니다.")
    status = conn.execute("SELECT status FROM sa_experiments WHERE experiment_id=%s FOR NO KEY UPDATE", exp).fetchone()[
        0
    ]
    trial = conn.execute("SELECT status FROM sa_trials WHERE trial_id=%s FOR UPDATE", (trial_id,)).fetchone()[0]
    if trial in {"finished", "error"}:
        return "done"
    if trial == "cancelled":
        return "cancelled"
    if trial == "running":
        conn.execute(
            "UPDATE sa_trials SET status='pending', attempt=attempt+1, started_at=NULL WHERE trial_id=%s", (trial_id,)
        )
    if status in {"stopped", "failed"}:
        conn.execute("UPDATE sa_trials SET status='cancelled' WHERE trial_id=%s", (trial_id,))
        return "cancelled"
    return "queued"


def fail(conn, job: dict, *, retry: bool, error: str = "worker_error") -> None:
    """오류에는 비밀값 없는 분류명만 전달합니다. 재시도 여부는 호출자가 정합니다."""
    _idle(conn)
    with transaction(conn):
        guard(conn, job)
        status = _recover_trial(conn, job)
        if not retry and status == "queued":
            status = "failed"
        _return_job(conn, job, status, error)


def reclaim(
    conn, *, limit: int = 100, max_attempts: int | None = None, cleanup_expired=None, kinds=None
) -> int:
    """죽거나 DB가 끊긴 워커의 만료 임대와 실행 중 풀이를 원자적으로 회수합니다.

    max_attempts 를 주면 그 횟수만큼 빌려 간 작업은 다시 넣지 않고 failed 로 둡니다
    (매번 프로세스를 죽이는 작업이 끝없이 돌지 않게). None 이면 상한 없이 다시 넣습니다.
    kinds 를 주면 그 종류만 회수합니다 (채점 워커가 컨테이너 정리 없이 풀이를 회수하지 않게).
    """
    _idle(conn)
    if limit < 1:
        raise ValueError("회수 개수는 1 이상이어야 합니다.")
    if max_attempts is not None and max_attempts < 1:
        raise ValueError("최대 시도 횟수는 1 이상이어야 합니다.")
    with transaction(conn):
        with conn.cursor(row_factory=dict_row) as cur:
            jobs = cur.execute(
                """SELECT * FROM sa_jobs WHERE status='leased' AND lease_until<=clock_timestamp()
                   AND (%s::text[] IS NULL OR kind=ANY(%s)) ORDER BY job_id FOR UPDATE SKIP LOCKED LIMIT %s""",
                (None if kinds is None else list(kinds), None if kinds is None else list(kinds), limit),
            ).fetchall()
        if cleanup_expired is not None:
            # 만료 임대 잠금을 유지한 채 해당 컨테이너부터 정리합니다. 실패하면 DB도 반환하지 않습니다.
            cleanup_expired(jobs)
        for job in jobs:
            status = _recover_trial(conn, job)
            if status == "queued" and max_attempts is not None and job["attempts"] >= max_attempts:
                status = "failed"
            _return_job(conn, job, status, "lease_expired")
        return len(jobs)
