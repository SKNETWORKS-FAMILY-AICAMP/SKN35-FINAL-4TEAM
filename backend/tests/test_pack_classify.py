"""② 실제 분류 코드와 DB 완료 흐름. 외부 모델 호출만 대체합니다."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from test_eng_pipeline import analyze_jobs, finished, prepare
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common.llm import FakeModel, Reply
from slotagent.grading.eng_pipeline import ConditionResult, GradeItem, grade
from slotagent.grading.pack_classify import classify
from slotagent.grading.pack_judge import judge, parse, vote


def response(result="correct", fail=None):
    return json.dumps(
        dict(answer=result, result_class=result, first_fail_type=fail, judge_status="ok", quote="final answer")
    )


def test_rules_and_unknown():
    item = GradeItem(1, 1, "test", {"spans": []}, "completed", (), False, False, None, {})
    assert classify(None, item).result_class == "correct"
    item = replace(item, conditions=(ConditionResult(1, 1, "info", None),))
    assert classify(None, item).judge_status == "undecidable"
    assert classify(None, replace(item, out_of_scope=True)).result_class == "ask_or_giveup"


@pytest.mark.parametrize("text", ["{}", response("correct", "intent"), response("wrong_assertion")])
def test_invalid_response(text):
    with pytest.raises((ValueError, KeyError)):
        parse(text, "result_class")


def test_disagreement_uses_fourth_vote(monkeypatch):
    item = GradeItem(
        1,
        1,
        "test",
        {"spans": []},
        "completed",
        (),
        False,
        False,
        "mini",
        {"schema_version": 1, "temperature": 0, "votes": 3, "questions": ["result_class"], "tiebreak_model": "large"},
    )
    calls = []

    def fake_vote(conn, item, question, number, model, adapter):
        calls.append((number, model))
        return parse(response("wrong_assertion", "argument") if number in (2, 4) else response(), question)

    monkeypatch.setattr("slotagent.grading.pack_judge.vote", fake_vote)
    conn = SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
    verdict = judge(conn, item, adapter=object())
    assert (verdict.result_class, verdict.first_fail_type) == ("wrong_assertion", "argument")
    assert calls == [(1, "mini"), (2, "mini"), (3, "mini"), (4, "large")]


def test_llm_cannot_override_rule_failure(monkeypatch):
    from slotagent.grading.eng_pipeline import Verdict

    monkeypatch.setattr("slotagent.grading.pack_classify.judge", lambda *_: Verdict("correct"))
    item = GradeItem(
        1,
        1,
        "test",
        {"spans": []},
        "completed",
        (ConditionResult(1, 1, "info", False),),
        False,
        False,
        "mini",
        {"votes": 3},
    )
    assert classify(None, item).judge_status == "undecidable"
    assert classify(None, item).result_class != "correct"


def test_real_classifier_pipeline_and_resume(experiment, monkeypatch):
    conn, data, run_id = prepare(experiment)
    settings = {
        "schema_version": 1,
        "temperature": 0,
        "votes": 3,
        "questions": ["result_class"],
        "tiebreak_model": "gpt-4.1",
    }
    # 준비된 실행의 불변 설정만 테스트용으로 교체합니다.
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role = replica")
        conn.execute(
            "UPDATE sa_grading_runs SET judge_model='gpt-4.1-mini',judge_settings=%s WHERE grading_run_id=%s",
            (Jsonb(settings), run_id),
        )
    for model in ("gpt-4.1-mini", "gpt-4.1"):
        conn.execute(
            "INSERT INTO sa_settings(scope,scope_ref,key,value) VALUES ('global','',%s,%s)",
            ("price." + model, Jsonb({"in_per_1k_krw": 1, "out_per_1k_krw": 2})),
        )
    fake = FakeModel([Reply(text=response(), in_tokens=10, out_tokens=10) for _ in range(6)])
    monkeypatch.setattr("slotagent.grading.pack_judge.ProviderModel", lambda: fake)
    seen = []

    def capture(c, item):
        seen.append(item)
        return classify(c, item)

    grade(conn, run_id, classify=capture)
    assert finished(conn, run_id)
    assert analyze_jobs(conn, run_id) == 1
    assert len(fake.requests) == 6
    assert conn.execute("SELECT count(*) FROM sa_llm_votes WHERE grading_run_id=%s", (run_id,)).fetchone()[0] == 6
    assert (
        conn.execute(
            "SELECT count(*) FROM sa_cost_ledger WHERE source='judge' AND experiment_id=%s", (data["experiment"],)
        ).fetchone()[0]
        == 6
    )
    assert vote(conn, seen[0], "result_class", 1, "gpt-4.1-mini", fake)["answer"] == "correct"
    assert len(fake.requests) == 6
