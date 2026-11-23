"""packs/it_ops/v1.0/pack.json (contracts/examples/pack.json 모양) → DB. 잠그기 전 검사: 골든 궤적 4종 채점 결과 = expected"""

from psycopg.types.json import Jsonb

from slotagent.common import contracts
from slotagent.common.hashing import canonical_hash


def confirmation_for_storage(task: dict) -> dict | None:
    """생략/NULL은 SQL NULL. 유효한 정책만 저장하고 slot_values에는 넣지 않는다."""
    policy = task.get("confirmation")
    if policy is not None:
        contracts.validate("pack", policy, part="confirmation")
    return policy


def store_task_confirmation(conn, task_id: int, task: dict) -> None:
    """기존 문항에 정책 저장. 트랜잭션은 호출자가 관리, 잠긴 문항은 DB 트리거가 차단."""
    policy = confirmation_for_storage(task)
    result = conn.execute("UPDATE sa_tasks SET confirmation = %s WHERE task_id = %s",
                          (Jsonb(policy) if policy is not None else None, task_id))
    if result.rowcount != 1:
        raise ValueError(f"Unknown task_id: {task_id}")


def pack_content_hash(pack: dict) -> str:
    """① 해시에 사용할 원본 해시. confirmation 포함, 생략과 NULL은 같은 의미로 정규화."""
    tasks = [{**task, "confirmation": confirmation_for_storage(task)} for task in pack["tasks"]]
    return canonical_hash({**pack, "tasks": tasks})


def load_pack(conn, pack_dir) -> int:
    raise NotImplementedError


def lock_pack(conn, pack_version_id: int) -> None:
    raise NotImplementedError
