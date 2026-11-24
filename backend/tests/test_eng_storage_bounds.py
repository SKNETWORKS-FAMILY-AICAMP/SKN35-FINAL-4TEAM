"""① 저장 불가 사용량·문자열은 비용 보존 후 모델 재호출을 막습니다."""

import json
from dataclasses import replace
from decimal import Decimal, localcontext

import psycopg
import pytest
from test_eng_costs import case as case
from test_eng_costs import ledger, states
from test_eng_stdio import ARGS
from test_eng_worker import dependencies
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import llm
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.workers.eng_main import run_once


@pytest.mark.parametrize("value", [2**31 - 1, 2**31, 2**63, -1, True, False])
@pytest.mark.parametrize("field", ["in_tokens", "out_tokens"])
def test_token_storage_range(case, engine_db, field, value):
    conn, _, trial, job_id = case
    deps = dependencies()
    deps.model = FakeModel([Reply(text="끝", **{field: value})])
    if value == 2**31 - 1:
        assert run_once(lambda: psycopg.connect(engine_db), "bounds", deps=deps)
        assert ledger(conn, trial)[0] == 1
    else:
        with pytest.raises(ValueError):
            run_once(lambda: psycopg.connect(engine_db), "bounds", deps=deps)
        assert states(conn, trial, job_id) == (("pending", 2), ("failed", 1))
        assert not run_once(lambda: psycopg.connect(engine_db), "bounds", deps=dependencies())
        assert ledger(conn, trial)[0] == 0
    assert len(deps.model.requests) == 1


def test_cost_storage_range():
    maximum = llm.MAX_COST_KRW
    with localcontext() as context:
        context.prec = 400
        too_large = maximum + 1
    assert llm.storage_cost(maximum) == maximum
    for value in (
        too_large,
        Decimal("1e309"),
        Decimal(-1),
        True,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e-16384"),
    ):
        with pytest.raises(ValueError):
            llm.storage_cost(value)
    # 2**63원이 int 저장 한계는 아닙니다. cost는 numeric이고 trace 표현 범위 안입니다.
    assert llm.storage_cost(Decimal(2**63)) == Decimal(2**63)


@pytest.mark.parametrize("case_name", ["max", "plus_one", "int64", "negative", "bool"])
def test_cost_worker_range(case, engine_db, case_name):
    conn, _, trial, job_id = case
    with localcontext() as context:
        context.prec = 400
        values = {
            "max": llm.MAX_COST_KRW,
            "plus_one": llm.MAX_COST_KRW + 1,
            "int64": Decimal(2**63),
            "negative": Decimal(-1),
            "bool": True,
        }
    value = values[case_name]
    deps = dependencies()
    deps.model = FakeModel([Reply(text="끝")])
    original = deps.model.chat
    deps.model.chat = lambda **kwargs: replace(original(**kwargs), cost_krw=value)
    if case_name in {"max", "int64"}:
        assert run_once(lambda: psycopg.connect(engine_db), "cost", deps=deps)
        assert ledger(conn, trial) == (1, value)
    else:
        with pytest.raises(ValueError):
            run_once(lambda: psycopg.connect(engine_db), "cost", deps=deps)
        assert states(conn, trial, job_id)[1] == ("failed", 1)
        assert not run_once(lambda: psycopg.connect(engine_db), "cost", deps=dependencies())
    assert len(deps.model.requests) == 1


def test_tokens_adapter_and_aggregate():
    assert llm._tokens(2**31 - 1) == 2**31 - 1
    for value in (2**31, 2**63, -1, True):
        with pytest.raises(ValueError):
            llm._tokens(value)


@pytest.mark.parametrize("field", ["cache_creation_input_tokens", "cache_read_input_tokens"])
@pytest.mark.parametrize("value", [True, False])
def test_anthropic_cache_bool_is_not_missing(field, value):
    from test_eng_llm import provider_response, setup_provider

    response = provider_response("anthropic")
    setattr(response.usage, field, value)
    model, client, _, args = setup_provider("anthropic", [response])
    with pytest.raises(ValueError):
        model.chat(**args)
    assert len(client.requests) == 1


@pytest.mark.parametrize("location", ["final", "model_text", "tool_result", "tool_args", "tool_args_invalid"])
@pytest.mark.parametrize("bad", ["a\x00b", "a\ud800b"], ids=["nul", "surrogate"])
def test_unstorable_text_stops_paid_retry(case, engine_db, location, bad):
    conn, _, trial, job_id = case
    arguments = {**ARGS, **({"owner": bad} if location.startswith("tool_args") else {})}
    if location == "tool_args_invalid":
        arguments.pop("repo")
    args = json.dumps(arguments)
    first = Reply(text=bad if location in {"final", "model_text"} else "", in_tokens=100, out_tokens=10)
    if location != "final":
        first = replace(first, tool_calls=(ToolCall("one", "list_issues", args),))
    model = FakeModel([first, Reply(text="끝", in_tokens=120, out_tokens=12)])
    deps = dependencies(lambda *args: bad if location == "tool_result" else "[]")
    deps.model = model
    with pytest.raises(ValueError):
        run_once(lambda: psycopg.connect(engine_db), "text", deps=deps)
    assert states(conn, trial, job_id) == (("pending", 2), ("failed", 1))
    assert not run_once(lambda: psycopg.connect(engine_db), "text", deps=dependencies())
    assert len(model.requests) == 1
    assert ledger(conn, trial) == (1, Decimal("0.12"))
    assert conn.execute("SELECT count(*) FROM sa_spans WHERE trial_id=%s", (trial,)).fetchone() == (0,)
    assert bad in (
        first.text
        if location in {"final", "model_text"}
        else (bad if location == "tool_result" else json.loads(first.tool_calls[0].arguments)["owner"])
    )
