"""예시가 스키마에 맞는지, 막아야 할 것을 막는지, 해시·스냅숏이 안 바뀌는지."""
import copy
import json
from datetime import UTC

import pytest
from conftest import ROOT, load
from jsonschema import Draft202012Validator

from slotagent.common import checks, contracts, proposal
from slotagent.common.hashing import canonical_hash, canonical_json
from slotagent.common.snapshot import SnapshotError, merge_snapshot, trial_seed


def test_schemas_are_valid_2020_12():
    for p in (ROOT / "contracts" / "schemas").glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(p.read_text(encoding="utf-8")))


def test_front_examples():
    av = load("agent_version.json")
    contracts.validate("agent_spec", av["spec"])
    for c in load("slot_and_candidates.json")["candidates"]:
        contracts.validate("component_spec", c["component_spec"])
    for t in load("pack.json")["tasks"]:
        for cond in t["conditions"]:
            contracts.validate("answer_condition", cond["spec"], part=cond["kind"])
    ex = load("experiment.json")
    contracts.validate("prereg", ex["prereg"])
    contracts.validate("plan", ex["plan"], part="stored")              # 저장된 plan = proposal 칸 있음 (3차 5)
    contracts.validate("trace", load("trace.json"))
    pack = load("pack.json")                                            # 평가팩 jsonb 칸 (3차 2)
    contracts.validate("pack", pack["pack_version"]["premises"], part="premises")
    for d in pack["data_snapshots"]:
        contracts.validate("pack", d["design"], part="data_design")
    for g in pack["golden"]:
        contracts.validate("pack", g["expected"], part="golden_expected")


@pytest.mark.parametrize("bundle", ["grading_analysis_report.json", "api_and_jobs.json"])
def test_keyed_examples(bundle):
    for key, val in load(bundle).items():
        if key.startswith("_"):
            continue
        name, _, part = key.partition(".")
        for v in (val if isinstance(val, list) else [val]):
            contracts.validate(name, v, part=part or None)


def test_rejects_what_must_be_rejected():
    req = load("api_and_jobs.json")["api.create_experiment_request"]
    bad = copy.deepcopy(req)
    bad["candidates"] = [{"candidate_id": 1, "role": "baseline"}]   # 역할·label 은 요청에서 받지 않음 (검토 32)
    assert contracts.errors("api", bad, part="create_experiment_request")
    bad = copy.deepcopy(load("experiment.json")["prereg"])
    del bad["max_env_retries"]                             # DB가 잠금을 막는 것과 같게
    assert contracts.errors("prereg", bad)
    spec = copy.deepcopy(load("agent_version.json")["spec"])
    spec["tools"][0]["secret"] = "x"                       # 모르는 키
    assert contracts.errors("agent_spec", spec)
    tr = copy.deepcopy(load("trace.json"))
    del tr["spans"][1]["name"]                             # 도구 단계는 이름 필수
    assert contracts.errors("trace", tr)
    tr = copy.deepcopy(load("trace.json"))
    tr["run_outcome"] = "env_error"                        # completed 가 아니면 이유 필수
    assert contracts.errors("trace", tr)
    tr["outcome_reason"] = "연습 DB 연결 불가"              # 이유는 정해 둔 값 목록만 (검토 24)
    assert contracts.errors("trace", tr)
    tr["outcome_reason"] = "env_practice_db_unreachable"
    assert not contracts.errors("trace", tr)
    req = copy.deepcopy(load("api_and_jobs.json")["api.create_experiment_request"])
    req["budget_krw"] = 0                                  # DB 는 budget_krw > 0 (검토 14)
    assert contracts.errors("api", req, part="create_experiment_request")
    pr = copy.deepcopy(load("experiment.json")["prereg"])
    pr["secondary_metrics"] = ["cost_per_success"]         # 지표 이름은 한 목록 (검토 13)
    assert contracts.errors("prereg", pr)
    pr = copy.deepcopy(load("experiment.json")["prereg"])
    del pr["outcome_rules"]["env_error_reasons"]           # 환경 탓 기준표 필수 (검토 24)
    assert contracts.errors("prereg", pr)
    pr["outcome_rules"]["env_error_reasons"] = ["agent_crash"]   # 후보 탓 원인은 넣을 수 없음
    assert contracts.errors("prereg", pr)
    spec = copy.deepcopy(load("agent_version.json")["spec"])
    del spec["tools"][5]["fixed_responses"]                # custom 도구는 가짜 응답 필수 (검토 30-f)
    assert contracts.errors("agent_spec", spec)
    spec = copy.deepcopy(load("agent_version.json")["spec"])
    spec["source"] = {"kind": "file"}                      # 받는 방법은 spec 에 두지 않음 (검토 16)
    assert contracts.errors("agent_spec", spec)
    rep = copy.deepcopy(load("grading_analysis_report.json")["report_content"][0])
    rep["evidence"][1]["comparison_id"] = 1                # 근거는 비교 또는 풀이 중 하나만 (검토 26)
    assert contracts.errors("report_content", rep)
    rep = copy.deepcopy(load("grading_analysis_report.json")["report_content"][1])
    del rep["detail"]                                      # detail 리포트는 detail 칸 필수 (검토 28)
    assert contracts.errors("report_content", rep)
    job = {"schema_version": 1, "kind": "analyze", "experiment_id": 1, "grading_run_id": 1, "is_interim": False}
    assert contracts.errors("job_payload", job)            # 실험 번호는 grading_run 으로 앎 (검토 33)


def test_rejects_3rd_review():
    """3차 검토 1~9 에서 막기로 한 것"""
    forb = load("pack.json")["tasks"][2]["conditions"][1]
    assert forb["kind"] == "forbidden"
    assert contracts.errors("answer_condition", dict(forb["spec"], gate=False), part="forbidden")   # 1: 금지 조건은 항상 관문
    assert checks.condition_gate("forbidden", {"gate": False}) is True
    assert contracts.errors("pack", {"timezone": "Asia/Seoul"}, part="premises")                    # 2: 전제 문장 필수
    assert contracts.errors("pack", {"success": True, "forbidden_action": True}, part="golden_expected")
    assert contracts.errors("settings", -1, part="ni_margin_pp")
    assert contracts.errors("chat", {"experiment_id": 1, "extra": 1}, part="start_run")
    js = load("grading_analysis_report.json")["grading.judge_settings"][0]
    assert contracts.errors("grading", dict(js, questions=["is_good"]), part="judge_settings")      # 3: 질문 종류 한 목록
    rep = copy.deepcopy(load("grading_analysis_report.json")["report_content"][1])
    rep["detail"]["fail_types"]["A"] = {"oops": 1}                                                    # 3: 첫 실패 유형 한 목록
    assert contracts.errors("report_content", rep)
    req = copy.deepcopy(load("api_and_jobs.json")["api.create_experiment_request"])
    req["plan"]["proposal"] = {"hash": "sha256:" + "0" * 64, "edited": False}                       # 5: ④는 proposal 을 적지 않음
    assert contracts.errors("api", req, part="create_experiment_request")
    del req["plan"]["proposal"], req["proposal"]
    assert contracts.errors("api", req, part="create_experiment_request")                            # 5: 제안 출처는 필수
    tr = copy.deepcopy(load("trace.json"))
    tr.update(run_outcome="agent_error", outcome_reason="timeout_wall_clock")                        # 6: timeout_ 이유 = timeout
    assert contracts.errors("trace", tr)
    tr.update(run_outcome="env_error", outcome_reason="agent_crash")                                 # 6: 환경 오류에 후보 탓 이유
    assert contracts.errors("trace", tr)
    tr.update(run_outcome="timeout", outcome_reason="timeout_wall_clock")
    assert not contracts.errors("trace", tr)
    pr = copy.deepcopy(load("experiment.json")["prereg"])
    pr["secondary_metrics"] = ["regression_rate"]                                                     # 8: 회귀율은 지표 목록에 없음
    assert contracts.errors("prereg", pr)


def test_run_outcome_rule():
    """3차 6: outcome_reason → run_outcome 규칙 한 곳"""
    pr = load("experiment.json")["prereg"]
    assert checks.run_outcome_for(None, pr) == "completed"
    assert checks.run_outcome_for("env_mcp_server_down", pr) == "env_error"
    assert checks.run_outcome_for("env_write_proxy_error", pr) == "agent_error"   # 이 실험의 env_error_reasons 에 없음
    assert checks.run_outcome_for("llm_api_429", pr) == "agent_error"             # P-02 전까지 기본 목록에 없음
    assert checks.run_outcome_for("timeout_wall_clock", pr) == "timeout"
    assert checks.run_outcome_for("agent_crash", pr) == "agent_error"


def test_empty_objects_mean_not_applicable():
    """DB 기본값 '{}' 가 스키마를 통과해야 함 (검토 15): 규칙만 쓰는 채점, grader_error 행"""
    assert not contracts.errors("grading", {}, part="judge_settings")
    assert not contracts.errors("grading", {}, part="trial_metrics")
    assert contracts.errors("grading", {"schema_version": 1}, part="trial_metrics")   # 반쯤 찬 것은 막음


def test_hash_rules():
    assert canonical_json({"b": 1, "a": "한글", "t": 0.0}) == '{"a":"한글","b":1,"t":0}'
    assert canonical_hash({"x": 1.0}) == canonical_hash({"x": 1})
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def _rows():
    av = load("agent_version.json")
    sc = load("slot_and_candidates.json")
    return av, sc["slot"], sc["candidates"][:2]          # A, B (C 도구 검색은 _tool_search())


def _tool_search():
    av = load("agent_version.json")
    sc = load("slot_and_candidates.json")
    return av, sc["slot"], sc["candidates"][0], sc["candidates"][2]


def test_snapshot_merge():
    av, slot, (a, b) = _rows()
    snap = merge_snapshot(av, slot, b)
    names = [t["name"] for t in snap["tools"]]
    assert names == sorted(names)
    assert set(names) == {"create_issue", "post_message", "list_releases", "list_workflow_runs", "list_workflow_jobs"}
    assert snap["write_tools"] == ["create_issue", "post_message"]
    assert [s["name"] for s in snap["mcp_servers"]] == ["github"]
    # 같은 입력이면 같은 해시
    assert canonical_hash(snap) == canonical_hash(merge_snapshot(av, slot, b))
    # 기준 A 와 B 는 다른 구성
    assert canonical_hash(merge_snapshot(av, slot, a)) != canonical_hash(snap)


def test_tool_search_snapshot():
    """도구 검색 후보 C (11/23): 도구는 A 와 같고, tool_search 칸이 붙고, always_loaded 는 deferred 에서 빠짐"""
    av, slot, a, c = _tool_search()
    snap = merge_snapshot(av, slot, c)
    snap_a = merge_snapshot(av, slot, a)
    assert snap["tools"] == snap_a["tools"] and "tool_search" not in snap_a
    assert snap["tool_search"] == {"method": "bm25", "top_k": 2,
                                   "deferred": ["list_issues", "list_workflow_runs", "search_code"]}
    assert canonical_hash(snap) != canonical_hash(snap_a)


def test_tool_search_rejects():
    av, slot, _, c = _tool_search()
    bad = copy.deepcopy(c)
    bad["component_spec"]["search"]["always_loaded"] = ["no_such_tool"]
    with pytest.raises(SnapshotError, match="no_such_tool"):
        merge_snapshot(av, slot, bad)
    bad = copy.deepcopy(c)
    bad["component_spec"]["search"]["always_loaded"] = [t["name"] for t in c["component_spec"]["tools"]]
    with pytest.raises(SnapshotError, match="검색할 도구"):
        merge_snapshot(av, slot, bad)
    bad = copy.deepcopy(c)
    bad["component_spec"]["search"]["method"] = "embedding"         # 8주 안에는 bm25 만
    assert contracts.errors("component_spec", bad["component_spec"])


def test_p01_out_of_scope_counts_as_fail():
    """P-01 확정 (기획서 1.3 5.4): 범위 밖은 실패로 셈. exclude 는 막힘"""
    prereg = load("experiment.json")["prereg"]
    assert not contracts.errors("prereg", prereg)
    bad = copy.deepcopy(prereg)
    bad["outcome_rules"]["out_of_scope"] = "exclude"
    assert contracts.errors("prereg", bad)
    assert contracts.errors("settings", "exclude", part="out_of_scope_rule")


def test_template_scope():
    """실행 전 범위 판정 (기획서 1.3 5.4·5.8): B 는 list_issues 를 빼서 T2 가 범위 밖"""
    av, slot, (a, b) = _rows()
    templates = load("pack.json")["templates"]
    for t in templates:
        contracts.validate("pack", t["required_capabilities"], part="required_capabilities")
    assert checks.template_scope(merge_snapshot(av, slot, a)["tools"], templates) == {"T1": "in_scope", "T2": "in_scope"}
    assert checks.template_scope(merge_snapshot(av, slot, b)["tools"], templates) == {"T1": "in_scope", "T2": "out_of_scope"}
    no_caps = [dict(t, capabilities=[]) if t["name"] == "list_workflow_jobs" else t for t in merge_snapshot(av, slot, b)["tools"]]
    assert checks.template_scope(no_caps, templates)["T2"] == "needs_review"       # 모르는 도구가 있으면 사람 확인
    tools = [dict(t, write_mode="exclude_tasks") if t["name"] == "post_message" else t for t in av["spec"]["tools"]]
    assert checks.template_scope(tools, [{"code": "T9", "required_capabilities": ["slack.messages.write"]}]) == {"T9": "excluded_write"}


def test_write_modes():
    """쓰기 도구 실행 방식은 연결 방식별 허용 값만, 쓰기 도구 10개까지 (기획서 1.3 5.8·8.2)"""
    spec = load("agent_version.json")["spec"]
    checks.check_write_modes("spec_upload", spec)
    for conn, mode, ok in [("spec_upload", "exclude_tasks", True), ("spec_upload", "test_space", False),
                           ("runner", "test_space", True), ("api", "dry_run", True), ("api", "fake", False)]:
        s = copy.deepcopy(spec)
        for t in s["tools"]:
            if t["access"] == "write":
                t["write_mode"] = mode
        if ok:
            checks.check_write_modes(conn, s)
        else:
            with pytest.raises(checks.CheckError):
                checks.check_write_modes(conn, s)
    s = copy.deepcopy(spec)
    for t in s["tools"]:
        t.pop("write_mode", None)
    with pytest.raises(checks.CheckError, match="드라이런"):
        checks.check_write_modes("api", s)                                   # API 는 dry_run 을 꼭 적어야 함
    s = copy.deepcopy(spec)
    s["tools"][0]["write_mode"] = "fake"
    with pytest.raises(checks.CheckError, match="읽기 도구"):
        checks.check_write_modes("spec_upload", s)
    s = copy.deepcopy(spec)
    w = next(t for t in s["tools"] if t["access"] == "write")
    s["tools"] += [dict(w, name=f"write_{i}") for i in range(10)]
    with pytest.raises(checks.CheckError, match="10개"):
        checks.check_write_modes("spec_upload", s)


def test_model_provider_and_tool_count():
    """모델 회사 4종 (기획서 1.3 8.1), 도구 개수 제한 없음 (8.2)"""
    req = load("api_and_jobs.json")["api.register_agent_request"]
    bad = copy.deepcopy(req)
    bad["version"].pop("model_provider")
    assert contracts.errors("api", bad, part="register_agent_request")
    bad["version"]["model_provider"] = "mistral"
    assert contracts.errors("api", bad, part="register_agent_request")
    av, slot, (_, b) = _rows()
    assert merge_snapshot(av, slot, b)["model"]["provider"] == "openai"
    spec = copy.deepcopy(av["spec"])
    spec["tools"] += [dict(spec["tools"][0], name=f"extra_tool_{i}") for i in range(60)]
    assert not contracts.errors("agent_spec", spec)                          # 50개 한도 없앰


def test_tool_first_gate():
    """기획서 1.3: Tool 자리 먼저 — 프롬프트 후보·새 MCP 서버 후보는 다음 단계"""
    av, slot, (_, b) = _rows()
    p = dict(b, component_kind="prompt", component_spec={"schema_version": 1, "kind": "prompt", "instructions": "x"})
    with pytest.raises(SnapshotError, match="다음 단계"):
        merge_snapshot(av, slot, p)
    nb = copy.deepcopy(b)
    nb["component_spec"]["mcp_server"] = dict(nb["component_spec"]["mcp_server"], name="github-b")
    for t in nb["component_spec"]["tools"]:
        t["origin"] = "mcp:github-b"
    with pytest.raises(SnapshotError, match="다음 단계"):
        merge_snapshot(av, slot, nb)


def test_questions_is_not_a_connection_type():
    """질문은 연결 방식이 아니라 questions_used 칸 (11/23)"""
    req = load("api_and_jobs.json")["api.register_agent_request"]
    assert not contracts.errors("api", req, part="register_agent_request")
    bad = copy.deepcopy(req)
    bad["version"]["connection_type"] = "questions"
    assert contracts.errors("api", bad, part="register_agent_request")


def test_snapshot_example_file_is_in_sync():
    """contracts/examples/config_snapshot.B.json 은 scripts/make_examples.py 로 만든 것과 같아야 함."""
    av, slot, (_, b) = _rows()
    assert load("config_snapshot.B.json") == merge_snapshot(av, slot, b)


def test_snapshot_refuses_wrong_slot():
    av, slot, (_, b) = _rows()
    b = copy.deepcopy(b)
    b["component_spec"]["access"] = "write"
    with pytest.raises(SnapshotError):
        merge_snapshot(av, slot, b)


def test_snapshot_refuses_tool_from_other_slot():
    """조회 자리 묶음에 쓰기 도구를 섞으면 거절 (검토 30-a)"""
    av, slot, (_, b) = _rows()
    b = copy.deepcopy(b)
    b["component_spec"]["tools"].append(dict(av["spec"]["tools"][4], name="create_issue2"))   # github/write
    with pytest.raises(SnapshotError, match="create_issue2"):
        merge_snapshot(av, slot, b)


def test_snapshot_refuses_server_swap_that_leaks():
    """후보가 같은 이름의 서버를 다른 버전으로 바꾸면 자리 밖 create_issue 도 바뀜 → 거절 (검토 37)"""
    av, slot, (_, b) = _rows()
    b = copy.deepcopy(b)
    b["component_spec"]["mcp_server"]["version"] = "0.21.0"
    with pytest.raises(SnapshotError, match="create_issue"):
        merge_snapshot(av, slot, b)


def test_baseline_is_built_from_agent_spec():
    """기준 A 는 agent_spec 에서 자동으로 만들고, 손으로 만든 A 가 다르면 거절 (검토 30-e)"""
    av, slot, (a, _) = _rows()
    auto = checks.baseline_component(av["spec"], slot)
    assert canonical_hash(sorted(auto["tools"], key=lambda t: t["name"])) == \
        canonical_hash(sorted(a["component_spec"]["tools"], key=lambda t: t["name"]))
    a = copy.deepcopy(a)
    a["component_spec"]["tools"].pop()
    with pytest.raises(SnapshotError, match="기준"):
        merge_snapshot(av, slot, a)


def test_snapshot_has_no_run_time_values():
    """엔진 버전·seed 는 실행 때 정해짐 → 스냅숏에 없음 (검토 36)"""
    av, slot, (_, b) = _rows()
    snap = merge_snapshot(av, slot, b)
    assert "harness_version" not in snap and "seed" not in snap["model"]
    assert snap["runtime"]["max_output_tokens"] == 1024
    assert trial_seed(1, 0) == trial_seed(1, 0) != trial_seed(1, 1)


def test_task_condition_checks():
    pack = load("pack.json")
    for t in pack["tasks"]:
        checks.check_task_conditions(t["conditions"])
    bad = copy.deepcopy(pack["tasks"][0]["conditions"])
    bad[2]["spec"]["supports"] = ["no_such_key"]           # 검토 30-d
    with pytest.raises(checks.CheckError, match="no_such_key"):
        checks.check_task_conditions(bad)
    assert checks.condition_gate("link", bad[2]["spec"]) is False      # 검토 23: 근거용
    assert checks.condition_gate("info", bad[0]["spec"]) is True


def test_plan_checks():
    template_of = {1: "T1", 2: "T1", 3: "T2"}
    ok = {"schema_version": 1, "tasks": [{"task_id": 1, "batch_no": 1}, {"task_id": 2, "batch_no": 1}, {"task_id": 3, "batch_no": 2}]}
    checks.check_plan(ok, template_of, {"sequential": {"method": "group_sequential", "looks": 2}})
    with pytest.raises(checks.CheckError, match="두 번"):                      # 검토 30-b
        checks.check_plan({"schema_version": 1, "tasks": [{"task_id": 1, "batch_no": 1}] * 2}, template_of)
    split = {"schema_version": 1, "tasks": [{"task_id": 1, "batch_no": 1}, {"task_id": 2, "batch_no": 2}]}
    with pytest.raises(checks.CheckError, match="흩어져"):                     # 검토 30-c
        checks.check_plan(split, template_of)
    with pytest.raises(checks.CheckError, match="looks"):
        checks.check_plan(ok, template_of, {"sequential": {"method": "group_sequential", "looks": 3}})


def test_proposal_tracking():
    """3차 5: 고쳤는지는 서버가 제안을 다시 만들어 비교해서 채움 (④가 적지 않음)"""
    aj = load("api_and_jobs.json")
    p_req, p_resp, create = aj["api.plan_proposal_request"], aj["api.plan_proposal_response"], aj["api.create_experiment_request"]
    assert create["proposal"] == {"request": p_req, "as_of": p_resp["as_of"]}
    saved = {k: create[k] for k in ("prereg", "plan", "reps", "budget_krw", "candidates")}
    rec = proposal.record(p_req, p_resp["as_of"], proposal.proposed_values(p_req, p_resp), saved)
    assert rec["edited"] and rec["edited_fields"] == ["plan.estimate", "plan.tasks"]                 # 예시: 문항을 1개로 줄여 저장
    assert rec["hash"] == proposal.proposal_hash(p_resp["prereg"], p_resp["plan"])
    contracts.validate("plan", dict(create["plan"], proposal=rec), part="stored")
    same = proposal.record(p_req, p_resp["as_of"], proposal.proposed_values(p_req, p_resp),
                           {"prereg": p_resp["prereg"], "plan": p_resp["plan"], "reps": 2, "budget_krw": 3000, "candidates": [2, 1]})
    assert not same["edited"] and same["edited_fields"] == []                                         # 후보 순서는 안 봄
    ex = load("experiment.json")                                                                        # 저장된 예시는 제안 그대로
    assert ex["plan"]["proposal"]["edited"] is False
    bad = copy.deepcopy(ex["plan"])
    bad["proposal"]["edited_fields"] = ["plan.tasks"]                                                  # edited=false 인데 고친 칸이 있으면 막음
    assert contracts.errors("plan", bad, part="stored")
    from datetime import datetime, timedelta
    now = datetime(2026, 11, 22, 12, tzinfo=UTC)
    proposal.check_as_of(now - timedelta(hours=1), now)
    with pytest.raises(checks.CheckError, match="다시 받으세요"):                                      # 24시간 넘은 제안은 proposal_stale
        proposal.check_as_of(now - timedelta(hours=25), now)


def test_method_copy_must_match_prereg():
    m = load("grading_analysis_report.json")["analysis.method"]
    pr = load("experiment.json")["prereg"]
    checks.check_method(m, pr)
    with pytest.raises(checks.CheckError):
        checks.check_method(m, dict(pr, alpha=0.1))


def test_no_answers_reach_the_run_side():
    """정답 접근 범위 (데이터 약속 v2-5): 실행 쪽이 받는 모양에는 정답 조건·골든 정답 칸이 없다"""
    banned = {"answer", "answers", "answer_conditions", "conditions", "expected", "golden", "golden_trajectories"}

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    yield from v.keys()
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    for name in ("config_snapshot", "job_payload"):
        schema = json.loads((ROOT / "contracts" / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert not banned & set(keys(schema)), name
    run = {"schema_version": 1, "kind": "run_trial", "trial_id": 1, "expected": "18:20"}
    assert contracts.errors("job_payload", run)            # 작업 큐에 정답을 실어 보낼 수 없음
