"""① 이미 받은 모델 응답의 비용. 결과 저장과 달리 현재 작업 소유권을 요구하지 않습니다."""

from decimal import Decimal

import psycopg


class CostPersistenceError(RuntimeError):
    """비용 DB 저장 실패. 별도 재시도 없이 기존 작업 재시도 상한을 따릅니다."""


class CostConflictError(ValueError):
    """같은 호출 키에 다른 비용·사용량을 기록하려 한 영구 오류입니다."""


def record_trial_cost(conn, *, trial_id, attempt, span, experiment_id, price_setting_id):
    """같은 호출을 한 번만 저장하고 기존 행과 값이 다르면 오류를 냅니다.

    중간 기록에서는 외부 트랜잭션 없는 연결을 사용해 즉시 커밋합니다.
    최종 저장에서도 같은 함수를 부르되 기존 결과 트랜잭션의 일부로 처리합니다.
    임대·현재 attempt·실험 상태는 검사하지 않으며 호출 시 고정한 식별자를 사용합니다.
    """
    key = (trial_id, attempt, span["seq"])
    values = (
        experiment_id,
        span["name"],
        span["in_tokens"],
        span["out_tokens"],
        Decimal(span["attributes"]["cost_krw"]),
        price_setting_id,
    )
    try:
        with conn.transaction():
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
        raise CostPersistenceError("모델 호출 비용을 저장하지 못했습니다. 다음 호출을 중단합니다.") from None
