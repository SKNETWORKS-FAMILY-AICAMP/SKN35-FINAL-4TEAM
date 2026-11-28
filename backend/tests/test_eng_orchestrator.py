"""① 오케스트레이터 1차 (docs/eng_orchestrator_design_1127.md 8절 완료 기준). 가짜 Backend·가짜 모델, 체크포인트는 pgserver."""

import json
import os
import pathlib
import subprocess
import sys
import uuid

import psycopg
import pytest
from conftest import database_url
from eng_orch_fakes import CANDIDATES, FINAL, DbBackend, FakeBrain, MemBackend

from slotagent.common.llm import FakeModel, ModelError, Reply
from slotagent.orchestrator import graph, runtime
from slotagent.orchestrator.brain import LLMBrain

PROC = str(pathlib.Path(__file__).with_name("eng_orch_proc.py"))
START = {"user_id": 1, "text": "비용을 줄이고 싶어. 정확도 차이 비교", "agent_version_id": 1, "slot_id": 1,
         "pack_version_id": 1}


@pytest.fixture
def url(pg):
    """시험마다 빈 DB — tick 이 다른 시험의 대기 스레드를 깨우지 않게."""
    name = "orch_" + uuid.uuid4().hex[:12]
    with psycopg.connect(pg, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
    return database_url(pg, name)


@pytest.fixture
def saver(url):
    with runtime.checkpointer(url) as s:
        yield s


def compiled(backend, saver):
    """그래프 객체를 새로 만듦 (재생성 시험: 같은 체크포인트로 이어져야 함)."""
    return graph.build(backend, FakeBrain()).compile(checkpointer=saver)


def kinds(g, tid):
    return [v["kind"] for v in runtime.waiting(g, tid)]


def resume(backend, saver, tid, value):
    g = compiled(backend, saver)
    runtime.resume(g, tid, value)
    return g


def to_plan(backend, saver, tid):
    g = compiled(backend, saver)
    runtime.step(g, START, tid)
    assert kinds(g, tid) == ["goal"]
    g = resume(backend, saver, tid, {"action": "approve", "by": 1})
    (plan,) = runtime.waiting(g, tid)
    assert plan["kind"] == "plan"
    return plan


def approve_plan(backend, saver, tid, plan):
    return resume(backend, saver, tid, {"action": "approve", "by": 1, "hash": plan["hash"]})


def to_running(backend, saver, tid):
    plan = to_plan(backend, saver, tid)
    g = approve_plan(backend, saver, tid, plan)
    (run,) = runtime.waiting(g, tid)
    assert run["kind"] == "run"
    return resume(backend, saver, tid, {"action": "approve", "by": 1, "hash": run["hash"]})


def test_full_flow_rebuilding_graph(saver):
    b, tid = MemBackend(), "t-full"
    plan = to_plan(b, saver, tid)
    # 코드가 거른 목록 안에서만: 없는 99, 1단계 밖 4 는 빠지고 기준 1 + 최대 2개
    assert plan["summary"]["candidates"] == [1, 2, 3]
    assert plan["summary"]["estimated_cost_krw"] == "산정 전"
    g = approve_plan(b, saver, tid, plan)
    assert len(b.exps) == 1 and kinds(g, tid) == ["run"]
    (run,) = runtime.waiting(g, tid)
    g = resume(b, saver, tid, {"action": "approve", "by": 1, "hash": run["hash"]})
    assert kinds(g, tid) == ["wait"] and b.exps[1]["starts"] == 1
    # 재개 25번을 넘어도 반복 한도에 안 걸림
    for _ in range(30):
        assert runtime.tick(compiled(b, saver), saver) == [tid]
    assert kinds(g, tid) == ["wait"]
    b.exps[1]["status"] = "done"
    g = compiled(b, saver)
    runtime.tick(g, saver)
    values = g.get_state(runtime.config(tid)).values
    assert kinds(g, tid) == []
    assert (values["analysis_id"], values["report_ids"]) == (7, [70, 71])
    assert values["explanation"] == {"facts": FINAL, "text": "기준 후보보다 나쁘지 않습니다"}
    assert set(values["approvals"]) == {"goal", "save_draft", "start_run"} and b.exps[1]["starts"] == 1


@pytest.mark.parametrize("edit", [{"reps": 5}, {"budget_krw": 10000}, {"candidate_ids": [1, 2]}])
def test_any_edit_invalidates_old_approval(saver, edit):
    b, tid = MemBackend(), "t-edit"
    old = to_plan(b, saver, tid)
    g = resume(b, saver, tid, {"action": "edit", "edits": edit})
    (new,) = runtime.waiting(g, tid)
    assert new["kind"] == "plan" and new["hash"] != old["hash"]
    g = approve_plan(b, saver, tid, old)  # 옛 계획에 대한 승인
    assert kinds(g, tid) == ["plan"] and b.exps == {}
    g = approve_plan(b, saver, tid, new)
    assert kinds(g, tid) == ["run"] and len(b.exps) == 1
    assert b.create_calls == [f"{tid}:{new['hash']}"]


def test_reject_ends_without_writes(saver):
    b, tid = MemBackend(), "t-reject"
    to_plan(b, saver, tid)
    g = resume(b, saver, tid, {"action": "reject", "by": 1})
    assert kinds(g, tid) == [] and b.exps == {}


def test_tick_wakes_only_wait(saver):
    b = MemBackend()
    to_plan(b, saver, "t-a")
    to_running(b, saver, "t-b")
    g = compiled(b, saver)
    assert runtime.tick(g, saver) == ["t-b"]
    assert kinds(g, "t-a") == ["plan"]
    # wait 가 tick 아닌 값(승인)을 받아도 다시 wait
    g = resume(b, saver, "t-b", {"action": "approve", "by": 1})
    assert kinds(g, "t-b") == ["wait"] and b.exps[1]["starts"] == 1


def test_not_ready_blocks_then_retries_same_node(saver):
    b, tid = MemBackend(), "t-501"
    b.not_ready = True
    g = compiled(b, saver)
    runtime.step(g, START, tid)
    g = resume(b, saver, tid, {"action": "approve", "by": 1})
    (blk,) = runtime.waiting(g, tid)
    assert blk["kind"] == "blocked" and blk["error"]["node"] == "propose" and blk["error"]["code"] == "not_ready"
    b.not_ready = False
    g = resume(b, saver, tid, {"action": "retry"})
    assert kinds(g, tid) == ["plan"]


def test_no_candidates_blocks(saver):
    b, tid = MemBackend([c for c in CANDIDATES if c["is_baseline"] or c["component_kind"] == "prompt"]), "t-none"
    g = compiled(b, saver)
    runtime.step(g, START, tid)
    g = resume(b, saver, tid, {"action": "approve", "by": 1})
    (blk,) = runtime.waiting(g, tid)
    assert blk["error"]["code"] == "no_candidates"


def test_retry_after_save_does_not_restart(saver):
    b, tid = MemBackend(), "t-saved"
    to_running(b, saver, tid)
    g = compiled(b, saver)
    real = b.status
    b.status = lambda eid: (_ for _ in ()).throw(graph.BackendError("not_found"))
    runtime.tick(g, saver)
    (blk,) = runtime.waiting(g, tid)
    assert blk["error"]["node"] == "watch"
    b.status = real
    g = resume(b, saver, tid, {"action": "retry"})
    assert kinds(g, tid) == ["wait"] and len(b.exps) == 1 and b.exps[1]["starts"] == 1


@pytest.mark.parametrize("status,text", [("done", "기준 후보보다 나쁘지 않습니다"), ("stopped", "stopped 상태로 끝나")])
def test_run_after_finished_recovers(saver, status, text):
    """실행 요청 뒤 체크포인트 전에 죽었고 그사이 끝남 → 재요청이 experiment_locked → 상태로 복구."""
    b, tid = MemBackend(), "t-locked-" + status
    plan = to_plan(b, saver, tid)
    g = approve_plan(b, saver, tid, plan)
    (run,) = runtime.waiting(g, tid)
    b.exps[1]["status"] = status  # 이미 실행돼 끝난 실험
    g = resume(b, saver, tid, {"action": "approve", "by": 1, "hash": run["hash"]})
    assert kinds(g, tid) == [] and text in g.get_state(runtime.config(tid)).values["explanation"]["text"]


def test_done_without_final_is_blocked(saver):
    b, tid = MemBackend(), "t-nofinal"
    to_running(b, saver, tid)
    b.exps[1]["status"] = "done"
    b.final_result = lambda eid: None
    g = compiled(b, saver)
    runtime.tick(g, saver)
    (blk,) = runtime.waiting(g, tid)
    assert blk["error"]["code"] == "analysis_missing"


def proc(url, tid, cmd, value=None, crash=None):
    env = {k: v for k, v in os.environ.items() if k != "ORCH_CRASH"} | ({"ORCH_CRASH": crash} if crash else {})
    args = [sys.executable, PROC, url, tid, cmd] + ([json.dumps(value)] if value is not None else [])
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    return out.returncode, (json.loads(out.stdout) if out.returncode == 0 else out.stderr)


def test_process_kill_creates_once_and_runs_once(url):
    tid = "t-proc"
    assert proc(url, tid, "start")[1]["waiting"][0]["kind"] == "goal"
    code, out = proc(url, tid, "resume", {"action": "approve", "by": 1})
    plan = out["waiting"][0]
    # 저장 직후·체크포인트 전에 종료 → 새 프로세스가 이어서 같은 키로 다시 저장
    assert proc(url, tid, "resume", {"action": "approve", "by": 1, "hash": plan["hash"]}, crash="create")[0] == 3
    code, out = proc(url, tid, "continue")
    assert code == 0 and out["waiting"][0]["kind"] == "run"
    run = out["waiting"][0]
    # 실행 직후 종료 → 그사이 실험이 끝남 → 재시작 시 experiment_locked → 설명
    assert proc(url, tid, "resume", {"action": "approve", "by": 1, "hash": run["hash"]}, crash="run")[0] == 3
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("UPDATE orch_fake.experiments SET status='done'")
    code, out = proc(url, tid, "continue")
    assert code == 0 and out["waiting"] == [] and out["values"]["analysis_id"] == 7
    with psycopg.connect(url) as c:
        rows = c.execute("SELECT create_key, starts FROM orch_fake.experiments").fetchall()
    assert rows == [(f"{tid}:{plan['hash']}", 1)]


def test_db_backend_matches_mem_semantics(url):
    b = DbBackend(url)
    eid = b.create_experiment({}, "k")
    assert b.create_experiment({}, "k") == eid
    b.run(eid)
    b.run(eid)
    assert b._get(eid) == {"status": "running", "starts": 1}


def test_llm_brain_filters_model_output():
    model = FakeModel([
        Reply(text='{"focus": ["cost", "speed", "accuracy"]}'),
        Reply(text='{"candidate_ids": [2, "x", 3], "reason": "싸다"}'),
        Reply(text="그냥 글"),
        Reply(text="나쁘지 않습니다"),
    ])
    brain = LLMBrain(model, "openai", "fake")
    assert brain.goal("비용") == {"focus": ["cost", "accuracy"], "text": "비용"}
    assert brain.pick({}, []) == {"candidate_ids": [2, 3], "reason": "싸다"}
    assert brain.pick({}, []) == {"candidate_ids": [], "reason": ""}  # JSON 아님 → 빈 선택 → 그래프가 blocked
    assert brain.explain({}, {"analysis_id": 7}) == "나쁘지 않습니다"
    assert all(r["tools"] == [] and r["temperature"] == 0 for r in model.requests)


@pytest.mark.parametrize("ids", [[2, 3], [1, 4], [1, 99], [1, 2, 3, 2], [1]])
def test_candidate_edit_stays_inside_pool(saver, ids):
    """서버는 자리만 확인 → 기준 빠짐·1단계 밖(4)·없는 후보·중복은 그래프가 막음."""
    b, tid = MemBackend(), "t-pool"
    old = to_plan(b, saver, tid)
    g = resume(b, saver, tid, {"action": "edit", "edits": {"candidate_ids": ids}})
    (plan,) = runtime.waiting(g, tid)
    assert plan["hash"] == old["hash"] and plan["summary"]["edit_error"]


def test_approve_needs_approver(saver):
    b, tid = MemBackend(), "t-by"
    plan = to_plan(b, saver, tid)
    g = resume(b, saver, tid, {"action": "approve", "hash": plan["hash"]})
    assert kinds(g, tid) == ["plan"] and b.exps == {}


def test_model_error_blocks_then_retries(saver):
    b, tid = MemBackend(), "t-model"
    brain = FakeBrain()
    calls = []

    def flaky(text):
        calls.append(text)
        if len(calls) == 1:
            raise ModelError("timeout")
        return FakeBrain().goal(text)

    brain.goal = flaky
    g = graph.build(b, brain).compile(checkpointer=saver)
    runtime.step(g, START, tid)
    (blk,) = runtime.waiting(g, tid)
    assert blk["error"] == {"node": "goal", "code": "model_error", "detail": "timeout"}
    runtime.resume(g, tid, {"action": "retry"})
    assert kinds(g, tid) == ["goal"]


def test_tick_survives_broken_thread_and_resumes_it(saver):
    b = MemBackend()
    to_running(b, saver, "t-x")
    to_running(b, saver, "t-y")
    real = b.status
    b.status = lambda eid: (_ for _ in ()).throw(RuntimeError("연결 끊김")) if eid == 1 else real(eid)
    g = compiled(b, saver)
    assert runtime.tick(g, saver) == ["t-y"]  # t-x 는 watch 에서 예외, t-y 는 계속
    assert kinds(g, "t-x") == [] and g.get_state(runtime.config("t-x")).next == ("watch",)
    b.status = real
    assert runtime.tick(g, saver) == ["t-x", "t-y"]
    assert kinds(g, "t-x") == ["wait"]


# --- Codex 감사(D:\final_test\orch_audit) 반영 ---


def test_candidate_listing_error_blocks(saver):
    b, tid = MemBackend(), "t-list"
    real = b.list_candidates
    b.list_candidates = lambda slot_id: (_ for _ in ()).throw(graph.BackendError("unavailable"))
    g = compiled(b, saver)
    runtime.step(g, START, tid)
    g = resume(b, saver, tid, {"action": "approve", "by": 1})
    (blk,) = runtime.waiting(g, tid)
    assert blk["error"]["node"] == "candidates" and blk["error"]["code"] == "unavailable"
    b.list_candidates = real
    g = resume(b, saver, tid, {"action": "retry"})
    assert kinds(g, tid) == ["plan"]


@pytest.mark.parametrize("reply", [
    "성공률 999%, analysis_id=888", "성공률 １２３", "구십구 퍼센트", "Ⅻ", "비용은 ½입니다", "효과는 ²입니다",
    "후보 ①입니다", "十 배 좋아졌습니다",
])
def test_numbers_in_model_prose_rejected(saver, reply):
    """숫자는 facts(저장값)로만 보여 주고 모델 글에는 없어야 함 — 근거와 맞추는 비교 대신 아예 금지."""
    b, tid = MemBackend(), "t-explain"
    to_running(b, saver, tid)
    b.exps[1]["status"] = "done"
    g = graph.build(b, LLMBrain(FakeModel([Reply(text=reply)]), "openai", "fake")).compile(checkpointer=saver)
    runtime.tick(g, saver)
    (blk,) = runtime.waiting(g, tid)
    assert blk["error"]["code"] == "explanation_rejected"
    assert "explanation" not in g.get_state(runtime.config(tid)).values


@pytest.mark.parametrize("text", ["기준 후보보다 나쁘지 않습니다", "프로젝트 비용 목표에 맞습니다", "이 후보는 비열등입니다",
                                  "프로세스를 확인하세요", "포인트를 짚으면 비용입니다", "LLM 호출 비용을 확인하세요",
                                  "CLI 도구를 확인하세요", "CI 작업을 확인하세요"])
def test_plain_prose_passes(text):
    from slotagent.orchestrator.brain import prose_problems
    assert prose_problems(text) == []


def test_partial_does_not_call_model(saver):
    """정상 완료가 아니면 모델 없이 정해진 글 — 추천 말투가 섞일 길이 없음."""
    b, tid = MemBackend(), "t-partial"
    to_running(b, saver, tid)
    b.exps[1]["status"] = "failed"
    model = FakeModel([])
    g = graph.build(b, LLMBrain(model, "openai", "fake")).compile(checkpointer=saver)
    runtime.tick(g, saver)
    exp = g.get_state(runtime.config(tid)).values["explanation"]
    assert model.requests == [] and exp["facts"]["status"] == "failed" and "추천에 쓰지 않습니다" in exp["text"]


def _deep(n):
    v = {}
    for _ in range(n):
        v = {"x": v}
    return v


def _cycle():
    v = {"action": "edit"}
    v["edits"] = v
    return v


@pytest.mark.parametrize("answer", [None, [], ["x"], "approve", 3, {"action": "edit", "edits": {"candidate_ids": [1, 2**70]}},
                                    {1: "x"}, {"action": object()},
                                    *({"action": "edit", "edits": {"budget_krw": x}} for x in (float("nan"), float("inf"), float("-inf"))),
                                    {"action": "approve", "meta": _deep(400)}, _cycle()])
def test_resume_rejects_bad_answer_before_graph(saver, answer):
    b, tid = MemBackend(), "t-bad-answer"
    plan = to_plan(b, saver, tid)
    with pytest.raises(ValueError, match="invalid_answer"):
        runtime.resume(compiled(b, saver), tid, answer)
    g = approve_plan(b, saver, tid, plan)  # 거절된 응답이 남지 않아 정상 승인이 그대로 됨
    assert kinds(g, tid) == ["run"]


@pytest.mark.parametrize("edits", ["oops", ["oops"], 42, {}, {"reps": 0}, {"reps": 11}, {"reps": "3"},
                                   {"budget_krw": 0}, {"budget_krw": -1}])
def test_bad_edits_keep_plan(saver, edits):
    b, tid = MemBackend(), "t-edits"
    old = to_plan(b, saver, tid)
    g = resume(b, saver, tid, {"action": "edit", "edits": edits})
    (plan,) = runtime.waiting(g, tid)
    assert plan["hash"] == old["hash"] and plan["summary"]["edit_error"]


def test_bool_candidate_id_rejected(saver):
    b = MemBackend([{"candidate_id": 9, "is_baseline": True, "component_kind": "tool_bundle"},
                    {"candidate_id": 1, "is_baseline": False, "component_kind": "custom_tool"}])
    brain = LLMBrain(FakeModel([Reply(text='{"focus":["cost"]}'), Reply(text='{"candidate_ids":[true]}')]),
                     "openai", "fake")
    g = graph.build(b, brain).compile(checkpointer=saver)
    runtime.step(g, START, "t-bool")
    runtime.resume(g, "t-bool", {"action": "approve", "by": 1})
    (blk,) = runtime.waiting(g, "t-bool")
    assert blk["error"]["code"] == "no_pick"


@pytest.mark.parametrize("ids", [[1, {}], [1, True], [1, 2.0], "12"])
def test_malformed_candidate_edit_keeps_plan(saver, ids):
    b, tid = MemBackend(), "t-bad-edit"
    old = to_plan(b, saver, tid)
    g = resume(b, saver, tid, {"action": "edit", "edits": {"candidate_ids": ids}})
    (plan,) = runtime.waiting(g, tid)
    assert plan["hash"] == old["hash"] and plan["summary"]["edit_error"]


@pytest.mark.parametrize("where", ["goal", "plan", "run", "blocked"])
def test_typo_keeps_waiting(saver, where):
    b, tid = MemBackend(), "t-typo-" + where
    if where == "goal":
        runtime.step(compiled(b, saver), START, tid)
    elif where == "blocked":
        b.not_ready = True
        runtime.step(compiled(b, saver), START, tid)
        resume(b, saver, tid, {"action": "approve", "by": 1})
    else:
        plan = to_plan(b, saver, tid)
        if where == "run":
            approve_plan(b, saver, tid, plan)
    g = resume(b, saver, tid, {"action": "aprove", "by": 1})
    assert kinds(g, tid) == [where]
    g = resume(b, saver, tid, {"action": "reject", "by": 1})
    assert kinds(g, tid) == []


def test_goal_approval_needs_approver(saver):
    b, tid = MemBackend(), "t-goal-by"
    runtime.step(compiled(b, saver), START, tid)
    g = resume(b, saver, tid, {"action": "approve"})
    assert kinds(g, tid) == ["goal"]
    g = resume(b, saver, tid, {"action": "approve", "by": 1})
    assert g.get_state(runtime.config(tid)).values["approvals"]["goal"]["by"] == 1


@pytest.mark.parametrize("text", [None, [], 2, {"focus": []}])
def test_non_text_reply_blocks(saver, text):
    g = graph.build(MemBackend(), LLMBrain(FakeModel([Reply(text=text)]), "openai", "fake")).compile(checkpointer=saver)
    runtime.step(g, START, "t-type")
    (blk,) = runtime.waiting(g, "t-type")
    assert blk["error"] == {"node": "goal", "code": "model_error", "detail": "bad_reply"}


def test_step_writes_checkpoint_synchronously():
    """프로세스 종료 시험은 타이밍상 async 로도 통과함(Codex 대조) → sync 를 넘기는지 직접 확인."""
    seen = {}

    class Spy:
        def invoke(self, value, config, **kw):
            seen.update(kw)

    runtime.step(Spy(), None, "t")
    assert seen == {"durability": "sync"}
