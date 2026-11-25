"""① 도구 검색 후보: 숨김·불러오기·순서·채점 문맥을 가짜 모델로 확인합니다."""

import copy
import json

import pytest
from conftest import load
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import contracts
from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.common.snapshot import merge_snapshot
from slotagent.engine.loop import Dependencies, run_agent
from slotagent.engine.tool_search import SEARCH, ToolSearch, tokenize
from slotagent.engine.worker import run_trial
from slotagent.grading.eng_context import from_snapshot
from slotagent.grading.eng_rules import check

REPO = {"owner": "acme", "repo": "ops-service"}


def snapshot(index=2):
    data = load("slot_and_candidates.json")
    return merge_snapshot(load("agent_version.json"), data["slot"], data["candidates"][index])


def call(name, _id="c", **args):
    return ToolCall(_id, name, json.dumps(args, ensure_ascii=False))


def run(snap, *replies):
    fake, outside = FakeModel([*replies]), []

    def tool(name, args, timeout):
        outside.append(name)
        return "[]"

    result = run_agent(snap, "조회", 1, Dependencies(fake, tool), prereg=load("experiment.json")["prereg"])
    contracts.validate("trace", result.trace)
    return result.trace, fake, outside


def shown(fake, n):
    return {t["function"]["name"] for t in fake.requests[n]["tools"]}


def tools(trace):
    return [s for s in trace["spans"] if s["kind"] == "tool"]


def test_deferred_tools_appear_only_after_search():
    snap = snapshot()
    original = copy.deepcopy(snap)
    trace, fake, outside = run(
        snap,
        Reply(tool_calls=(call(SEARCH, query="issues"),)),
        Reply(tool_calls=(call("list_issues", **REPO),)),
        Reply(text="끝"),
    )
    hidden = set(snap["tool_search"]["deferred"])
    assert not shown(fake, 0) & hidden and {SEARCH, "list_releases"} <= shown(fake, 0)
    assert shown(fake, 1) & hidden == {"list_issues"} == shown(fake, 2) & hidden
    assert outside == ["list_issues"]
    assert tools(trace)[0]["attributes"]["tool_search.loaded"] == ["list_issues"]
    assert json.loads(tools(trace)[0]["tool_result"]) == {"tools": ["list_issues"]}
    assert snap == original


@pytest.mark.parametrize("same_reply", [False, True])
def test_unseen_tool_is_rejected_without_execution(same_reply):
    """검색 전이거나 같은 응답에서 검색한 도구는 모델이 설명을 본 적이 없으므로 실행하지 않습니다."""
    calls = (call("list_issues", "b", **REPO),)
    if same_reply:
        calls = (call(SEARCH, "a", query="issues"), *calls)
    trace, _, outside = run(snapshot(), Reply(tool_calls=calls), Reply(text="끝"))
    assert tools(trace)[-1]["error"] == "agent_invalid_tool_call"
    assert not outside


@pytest.mark.parametrize("args", [{}, {"query": ""}, {"query": 1}, {"query": "a", "x": 1}, {"query": "a" * 501}])
def test_invalid_search_call_loads_nothing(args):
    trace, fake, _ = run(snapshot(), Reply(tool_calls=(call(SEARCH, **args),)), Reply(text="끝"))
    assert tools(trace)[0]["error"] == "agent_invalid_tool_call"
    assert shown(fake, 0) == shown(fake, 1)


@pytest.mark.parametrize("query", ["배포", "!!!", "한", "zzz"])
def test_no_match_returns_empty_and_continues(query):
    trace, fake, _ = run(snapshot(), Reply(tool_calls=(call(SEARCH, query=query),)), Reply(text="끝"))
    assert json.loads(tools(trace)[0]["tool_result"])["tools"] == []
    assert shown(fake, 0) == shown(fake, 1) and trace["run_outcome"] == "completed"


def test_search_step_counts_toward_max_steps():
    snap = snapshot()
    snap["runtime"]["max_steps"] = 2
    trace, _, _ = run(snap, Reply(tool_calls=(call(SEARCH, query="issues"),)), Reply(text="끝"))
    assert trace["outcome_reason"] == "agent_max_steps"


def test_loaded_tools_do_not_leak_to_next_trial():
    snap = snapshot()
    run(snap, Reply(tool_calls=(call(SEARCH, query="issues"),)), Reply(text="끝"))
    _, fake, _ = run(snap, Reply(text="끝"))
    assert "list_issues" not in shown(fake, 0)


def test_search_tool_exists_only_for_search_candidates():
    trace, fake, _ = run(snapshot(0), Reply(tool_calls=(call(SEARCH, query="issues"),)), Reply(text="끝"))
    assert SEARCH not in shown(fake, 0)
    assert tools(trace)[0]["error"] == "agent_invalid_tool_call"
    assert SEARCH not in from_snapshot(snapshot(0), None)["tool_access"]


def test_name_clash_rejected_only_for_search_candidates():
    snap, plain = snapshot(), snapshot(0)
    for target in (snap, plain):
        target["tools"].append({**copy.deepcopy(target["tools"][0]), "name": SEARCH})
    with pytest.raises(ValueError, match="겹칩니다"):
        ToolSearch(snap)
    with pytest.raises(ValueError):
        from_snapshot(snap, None)
    assert from_snapshot(plain, None)["tool_access"][SEARCH] == plain["tools"][0]["access"]


def test_deferred_must_exist_in_snapshot():
    snap = snapshot()
    snap["tool_search"]["deferred"] = ["absent"]
    with pytest.raises(ValueError, match="absent"):
        ToolSearch(snap)


def _index(descriptions, top_k=10):
    items = [
        {"name": n, "description": d, "parameters": {"type": "object"}, "capabilities": ["secret.label"]}
        for n, d in descriptions.items()
    ]
    return ToolSearch(
        {"tools": items, "tool_search": {"method": "bm25", "top_k": top_k, "deferred": list(descriptions)}}
    )


@pytest.mark.parametrize("size", [1, 2, 3])
def test_small_corpus_still_matches(size):
    """rank-bm25 의 Okapi 는 도구 1~2개에서 점수가 0·음수가 됩니다."""
    names = dict(list({"alpha": "list issues", "beta": "read logs", "gamma": "deploy"}.items())[:size])
    assert _index(names).search("issue") == ["alpha"]


def test_ranking_prefers_more_matches_and_ties_by_name():
    index = _index({"b": "read workflow logs", "a": "read workflow logs", "c": "read issues", "d": "deploy"})
    assert index.search("read workflow logs") == ["a", "b", "c"]
    assert _index({"b": "same", "a": "same"}, top_k=1).search("same") == ["a"]


def test_capability_labels_are_not_searchable():
    assert _index({"a": "list issues", "b": "logs"}).search("secret label") == []


def test_tokenize_korean_and_identifiers():
    assert tokenize("listWorkflowRuns get_issue") == ["list", "workflow", "run", "get", "issue"]
    assert set(tokenize("이슈를")) & set(tokenize("이슈"))


def test_hidden_write_cannot_be_executed_even_if_approved():
    """쓰기 자리 검색 후보: 불러오지 않은 쓰기는 승인 여부와 관계없이 쓰기 기록이 생기지 않습니다."""
    snap = snapshot()
    snap["tool_search"]["deferred"] = ["create_issue"]
    trace, _, outside = run(
        snap, Reply(tool_calls=(call("create_issue", title="INC-7", **REPO),)), Reply(text="끝")
    )
    assert trace["write_intents"] == [] and not outside
    trace, _, outside = run(
        snap,
        Reply(tool_calls=(call(SEARCH, query="create issue"),)),
        Reply(tool_calls=(call("create_issue", title="INC-7", **REPO),)),
        Reply(text="끝"),
    )
    assert [w["user_confirmed"] for w in trace["write_intents"]] == [False] and not outside


def test_grading_treats_search_as_builtin():
    snap = snapshot()
    trace, _, _ = run(snap, Reply(tool_calls=(call(SEARCH, query="issues"),)), Reply(text="끝"))
    spec = {"schema_version": 1, "call": {"access": "write"}}
    assert check("forbidden", spec, trace, **from_snapshot(snap, None))[0] is True


def test_worker_runs_and_saves_search_candidate(experiment):
    conn, data = experiment
    from psycopg.types.json import Jsonb

    from slotagent.common.hashing import canonical_hash

    trial = data["trials"][0]
    snap = snapshot()
    # 잠긴 스냅숏은 바꿀 수 없으므로 검사용으로 트리거만 잠시 끕니다.
    conn.execute("SET session_replication_role = replica")
    conn.execute(
        """UPDATE sa_experiment_candidates SET config_snapshot=%s, config_hash=%s WHERE experiment_candidate_id=
           (SELECT experiment_candidate_id FROM sa_trials WHERE trial_id=%s)""",
        (Jsonb(snap), canonical_hash(snap), trial),
    )
    conn.execute("SET session_replication_role = DEFAULT")
    fake = FakeModel(
        [
            Reply(tool_calls=(call(SEARCH, query="issues"),)),
            Reply(tool_calls=(call("list_issues", **REPO),)),
            Reply(text="끝"),
        ]
    )
    run_trial(conn, trial, deps=Dependencies(fake, lambda *a: "[]"))
    rows = conn.execute(
        "SELECT name, attributes->'tool_search.loaded' FROM sa_spans WHERE trial_id=%s AND kind='tool' ORDER BY seq",
        (trial,),
    ).fetchall()
    assert rows == [(SEARCH, ["list_issues"]), ("list_issues", None)]
