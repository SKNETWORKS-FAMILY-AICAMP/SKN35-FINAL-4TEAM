"""① 기록·재생: 저장한 trace 만으로 실행 루프를 다시 돌려 trace·규칙 채점이 원래와 같은지, 변조를 잡는지.

test_eng_pilot 의 파일럿 15유형 실험(후보 A·B = 30풀이)을 가짜 모델로 한 번 돌려 DB 에 저장한 뒤,
모델·도구 없이(키 없이) 재생합니다. 저장 기록을 그대로 재채점하는 시험은 test_eng_pilot.regrade 에 있습니다.
"""

import copy
import json

import psycopg
import pytest
from psycopg.rows import dict_row
from test_eng_pilot import PILOT, calls, create_experiment, run_experiment, success
from test_eng_pilot import pack_id as pack_id
from test_eng_worker import engine_db as engine_db

from slotagent.engine.replay import replay_trial
from slotagent.engine.write_proxy import BUILTIN_NAMES
from slotagent.grading.eng_pipeline import load_trace


@pytest.fixture(scope="module")
def pilot(engine_db, pack_id):
    goldens = [success(t) for t in PILOT]
    names = {s["name"] for g in goldens for s in calls(g)} - BUILTIN_NAMES
    with psycopg.connect(engine_db, autocommit=True) as conn:
        exp = create_experiment(conn, pack_id, goldens, names)
        run_id = run_experiment(engine_db, exp, goldens)
        with conn.cursor(row_factory=dict_row) as cur:
            trials = cur.execute("SELECT * FROM sa_trials WHERE experiment_id=%s ORDER BY trial_id", (exp,)).fetchall()
        yield conn, run_id, trials


def test_replay_matches_original(pilot):
    """30풀이 모두: 재생 trace = 저장 trace, 재채점 = 저장된 조건 결과. 모델·도구 호출과 DB 쓰기 없음."""
    conn, run_id, trials = pilot
    assert len(trials) >= 10
    before = conn.execute("SELECT (SELECT count(*) FROM sa_spans),(SELECT count(*) FROM sa_condition_results)").fetchone()
    for trial in trials:
        report = replay_trial(conn, trial["trial_id"], grading_run_id=run_id)
        assert report.same, (trial["trial_id"], report.differences)
        assert any(r.passed is not None for r in report.replayed)
    assert conn.execute("SELECT (SELECT count(*) FROM sa_spans),(SELECT count(*) FROM sa_condition_results)"
                        ).fetchone() == before


def _trial_with(pilot, want):
    conn, run_id, trials = pilot
    for trial in trials:
        trace = load_trace(conn, trial)
        if want(trace):
            return conn, run_id, trial["trial_id"], trace
    raise AssertionError("조건에 맞는 풀이가 없습니다.")


def _replay(pilot, want, tamper):
    conn, run_id, trial_id, trace = _trial_with(pilot, want)
    changed = copy.deepcopy(trace)
    tamper(changed)
    return replay_trial(conn, trial_id, grading_run_id=run_id, trace=changed)


def _read(trace):
    return next((s for s in trace["spans"] if s["kind"] == "tool" and s["name"] not in BUILTIN_NAMES
                 and "write_mode" not in s.get("attributes", {})), None)


def test_times_are_not_compared(pilot):
    def shift(trace):
        for s in trace["spans"]:
            s["duration_sec"] += 5
    assert _replay(pilot, lambda t: True, shift).same


def test_changed_tool_args_is_divergence(pilot):
    """기록의 조회 인자를 바꾸면 모델 응답(원래 인자)과 맞지 않아 재생이 멈춥니다."""
    report = _replay(pilot, _read, lambda t: _read(t)["tool_args"].update(changed=1))
    assert report.replayed is None and "부르려 함" in report.differences[0]


def test_changed_final_answer_is_caught(pilot):
    report = _replay(pilot, lambda t: True, lambda t: t.update(final_answer="바뀐 답"))
    assert "trace.final_answer" in report.differences[0]


def test_flipped_confirmation_is_caught(pilot):
    """write_proxy 가 승인 여부를 다시 계산하므로 기록의 user_confirmed 를 뒤집으면 드러납니다."""
    def flip(trace):
        trace["write_intents"][0]["user_confirmed"] = not trace["write_intents"][0]["user_confirmed"]
    report = _replay(pilot, lambda t: t["write_intents"], flip)
    assert any("write_intents[0].user_confirmed" in d for d in report.differences)


def test_missing_model_reply_is_divergence(pilot):
    def drop_last_llm(trace):
        last = max(i for i, s in enumerate(trace["spans"]) if s["kind"] == "llm")
        del trace["spans"][last]
    report = _replay(pilot, lambda t: True, drop_last_llm)
    assert report.replayed is None and "모델 호출이 많습니다" in report.differences[0]


def test_consistent_forgery_is_caught_by_saved_grades(pilot):
    """최종 답과 그 llm 응답을 함께 바꾸면 trace 는 자기와 맞지만, 저장된 채점 결과와 달라집니다."""
    def forge(trace):
        trace["final_answer"] = json.dumps({"forged": True})
        next(s for s in reversed(trace["spans"]) if s["kind"] == "llm")["output"] = trace["final_answer"]
    report = _replay(pilot, lambda t: True, forge)
    assert report.replayed is not None
    assert report.differences and all(d.startswith("조건 ") for d in report.differences)
