"""① 이미 받은 모델 응답의 비용. 결과 저장과 달리 현재 작업 소유권을 요구하지 않습니다."""

import time
from decimal import Decimal

import psycopg

from slotagent.common import queue
from slotagent.common.llm import _tokens, storage_cost


class CostPersistenceError(ValueError):
    """비용 DB 저장 실패. 영수증만 제한 재시도한 뒤 작업 자동 재호출을 금지합니다."""


class CostConflictError(ValueError):
    """같은 호출 키에 다른 비용·사용량을 기록하려 한 영구 오류입니다."""


def _record_trial_cost(conn, *, trial_id, attempt, span, experiment_id, price_setting_id):
    """같은 호출을 한 번만 저장하고 기존 행과 값이 다르면 오류를 냅니다.

    중간 기록에서는 외부 트랜잭션 없는 연결을 사용해 즉시 커밋합니다.
    최종 저장에서도 같은 함수를 부르되 기존 결과 트랜잭션의 일부로 처리합니다.
    임대·현재 attempt·실험 상태는 검사하지 않으며 호출 시 고정한 식별자를 사용합니다.
    """
    key = (trial_id, attempt, span["seq"])
    _tokens(span["in_tokens"])
    _tokens(span["out_tokens"])
    raw_cost = span["attributes"]["cost_krw"]
    if isinstance(raw_cost, bool):
        raise ValueError("bool은 비용이 아닙니다.")
    try:
        cost = Decimal(raw_cost)
    except (ArithmeticError, TypeError, ValueError):
        raise ValueError("비용 숫자 형식이 올바르지 않습니다.") from None
    storage_cost(cost)
    values = (
        experiment_id,
        span["name"],
        span["in_tokens"],
        span["out_tokens"],
        cost,
        price_setting_id,
    )
    try:
        with queue.transaction(conn):
            inserted = conn.execute(
                """INSERT INTO sa_cost_ledger(source,ref_id,attempt,span_seq,experiment_id,model,
                   in_tokens,out_tokens,cost_krw,price_setting_id)
                   VALUES ('trial',%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (ref_id,attempt,span_seq) WHERE source='trial' DO NOTHING
                   RETURNING cost_ledger_id""",
                (*key, *values),
            ).fetchone()
            if inserted is None:
                previous = conn.execute(
                    """SELECT experiment_id,model,in_tokens,out_tokens,cost_krw,price_setting_id
                       FROM sa_cost_ledger WHERE source='trial' AND ref_id=%s AND attempt=%s AND span_seq=%s""",
                    key,
                ).fetchone()
                if previous != values:
                    raise CostConflictError("같은 모델 호출의 비용 또는 사용량이 기존 기록과 다릅니다.")
    except psycopg.Error:
        raise


def record_trial_cost(conn, **values):
    """동일 영수증만 최대 3회 재전달합니다. 모델 호출 재시도는 하지 않습니다."""
    for attempt in range(3):
        try:
            return _record_trial_cost(conn, **values)
        except psycopg.Error as exc:
            retryable = isinstance(exc, (psycopg.OperationalError, psycopg.errors.QueryCanceled))
            if not retryable or attempt == 2:
                raise CostPersistenceError(
                    "수신한 모델 비용 저장 실패: 영수증 재시도 상한 도달 또는 영구 DB 오류. 자동 모델 재호출 금지."
                ) from None
            time.sleep(0.1 * (attempt + 1))
