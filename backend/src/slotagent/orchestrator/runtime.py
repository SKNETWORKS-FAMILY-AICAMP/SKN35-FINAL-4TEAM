"""체크포인트(스키마 orchestrator)와 외부 구동기.

감시는 watch → wait(interrupt) → tick → watch. 구동기는 kind="wait" 대기만 tick 으로 깨웁니다 (승인 대기는 안 건드림).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row

SCHEMA = "orchestrator"
log = logging.getLogger(__name__)


@contextmanager
def checkpointer(database_url: str) -> Iterator[PostgresSaver]:
    """orchestrator 스키마에만 LangGraph 체크포인트 표를 만듭니다 (sa_ 규칙 밖)."""
    with psycopg.connect(database_url, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    with psycopg.connect(database_url, autocommit=True, prepare_threshold=0, row_factory=dict_row,
                         options=f"-c search_path={SCHEMA}") as conn:
        saver = PostgresSaver(conn)
        saver.setup()
        yield saver


def config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def step(graph, value, thread_id: str):
    """한 번 진행. durability=sync: 노드가 끝날 때마다 체크포인트를 쓴 뒤 다음으로 (중간에 죽어도 그 노드부터)."""
    return graph.invoke(value, config(thread_id), durability="sync")


BIGINT = 2**63 - 1
MAX_DEPTH = 32  # 응답은 몇 단계면 충분. 순환·아주 깊은 값도 이 상한에서 끊김 (재귀 한도 전에)


def _bad_value(v, depth: int = 0) -> bool:
    if depth > MAX_DEPTH:
        return True
    if isinstance(v, dict):
        return any(not isinstance(k, str) or _bad_value(x, depth + 1) for k, x in v.items())
    if isinstance(v, list):
        return any(_bad_value(x, depth + 1) for x in v)
    if type(v) is int:
        return not -BIGINT - 1 <= v <= BIGINT  # 체크포인트 직렬화·DB bigint 범위
    if type(v) is float:
        return not math.isfinite(v)  # NaN·Infinity 는 JSON 값이 아니고 해시도 안 됨
    return not (v is None or isinstance(v, (str, bool)))


def resume(graph, thread_id: str, answer):
    """사용자 응답으로 재개하는 유일한 입구. 응답이 dict·JSON 값·bigint 범위가 아니면 그래프에 넣지 않음
    (넣으면 체크포인트에 먼저 저장돼 같은 오류가 반복됨)."""
    if not isinstance(answer, dict) or _bad_value(answer):
        raise ValueError("invalid_answer")
    return step(graph, Command(resume=answer), thread_id)


def waiting(graph, thread_id: str) -> list[dict]:
    """지금 걸려 있는 interrupt 값들."""
    return [i.value for i in graph.get_state(config(thread_id)).interrupts]


def thread_ids(saver: PostgresSaver) -> list[str]:
    # shortcut: 체크포인트 표 전체에서 스레드를 고름, 스레드가 많아지면 대기 목록 표를 따로 둠
    with saver._cursor() as cur:
        cur.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = '' ORDER BY thread_id")
        return [r["thread_id"] for r in cur.fetchall()]


def tick(graph, saver: PostgresSaver) -> list[str]:
    """kind="wait" 로 대기 중인 스레드만 한 번씩 재개. 돌려주는 값: 깨운 thread_id."""
    woke = []
    for tid in thread_ids(saver):
        try:
            state = graph.get_state(config(tid))
            if any(i.value.get("kind") == "wait" for i in state.interrupts):
                step(graph, Command(resume={"action": "tick"}), tid)
                woke.append(tid)
            elif not state.interrupts and state.next == ("watch",):
                step(graph, None, tid)  # 지난 tick 의 watch 가 예외로 멈춤 → 이어서 (승인 대기·쓰기 노드는 안 건드림)
                woke.append(tid)
        except Exception:  # 한 스레드가 깨져도 나머지는 깨움. 깨진 스레드는 체크포인트에 남아 다음 tick 에 다시
            log.exception("tick 실패: %s", tid)
    return woke
