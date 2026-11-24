"""① 실험 잠금·풀이 생성·작업 등록을 한 트랜잭션으로 처리합니다."""

from slotagent.common import contracts, queue
from slotagent.engine import advance


def lock_and_enqueue(conn, experiment_id: int) -> dict:
    """같은 요청을 반복해도 풀이와 작업은 한 번만 만듭니다."""
    with queue.transaction(conn):
        row = conn.execute(
            "SELECT status FROM sa_experiments WHERE experiment_id=%s FOR UPDATE", (experiment_id,)
        ).fetchone()
        if row is None:
            raise ValueError("실험이 없습니다.")
        if row[0] == "draft":
            conn.execute("SELECT lock_experiment(%s)", (experiment_id,))
            trials = conn.execute(
                "SELECT trial_id FROM sa_trials WHERE experiment_id=%s ORDER BY trial_id", (experiment_id,)
            ).fetchall()
            for (trial_id,) in trials:
                advance.enqueue(conn, {"schema_version": 1, "kind": "run_trial", "trial_id": trial_id})
            advance.mark_running(conn, experiment_id)
            status = "running"
        elif row[0] in {"locked", "running"}:
            status = row[0]
        else:
            raise ValueError("종료된 실험은 다시 시작할 수 없습니다.")
        count = conn.execute("SELECT count(*) FROM sa_trials WHERE experiment_id=%s", (experiment_id,)).fetchone()[0]
        return contracts.validate(
            "api", {"experiment_id": experiment_id, "status": status, "trials_total": count}, part="run_response"
        )
