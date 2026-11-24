"""① 실제 워커 저장·원문 피드백·순수 채점기 경계."""

import json

import pytest
from test_eng_rules import info
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common.llm import FakeModel, Reply, ToolCall
from slotagent.engine.loop import Dependencies, ToolExecutionError
from slotagent.engine.worker import run_trial
from slotagent.grading import eng_rules


@pytest.mark.parametrize("recover", [True, False], ids=["recovery_trace", "permission_trace"])
def test_tool_error_worker_and_grader(experiment, recover):
    conn, ids = experiment
    raw = "一時失敗: retry later" if recover else "permission denied: private repository"
    calls = [
        Reply(tool_calls=(ToolCall("first", "list_issues", '{"owner":"acme","repo":"ops-service","state":"open"}'),))
    ]
    if recover:
        calls.append(
            Reply(
                tool_calls=(ToolCall("second", "list_issues", '{"owner":"acme","repo":"ops-service","state":"open"}'),)
            )
        )
    calls.append(Reply(text=json.dumps({"value": "recovered" if recover else "permission denied"})))
    model, attempts = FakeModel(calls), []

    def call(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise ToolExecutionError(raw)
        return "145"

    trial = ids["trials"][0]
    result = run_trial(conn, trial, deps=Dependencies(model, call))
    assert result.outcome == "completed"
    spans = [s for s in result.trace["spans"] if s["kind"] == "tool"]
    assert spans[0]["error"] == "tool_error"
    assert spans[0]["tool_result"] == raw
    assert model.requests[1]["messages"][-1]["content"] == raw
    assert conn.execute(
        "SELECT error,tool_result FROM sa_spans WHERE trial_id=%s AND kind='tool' ORDER BY seq", (trial,)
    ).fetchone() == ("tool_error", raw)
    assert conn.execute("SELECT attempt FROM sa_trials WHERE trial_id=%s", (trial,)).fetchone() == (1,)
    assert eng_rules.check("info", info("recovered" if recover else "permission denied"), result.trace)[0]
    context = {"list_issues": "read"}
    with pytest.raises(eng_rules.RulePolicyRequired, match="error_call_policy_missing"):
        eng_rules.check(
            "order",
            {"schema_version": 1, "before": {"tool": "list_issues"}, "after": {"tool": "other"}},
            result.trace,
            tool_access=context,
            tool_access_complete=True,
        )
    if recover:
        assert "error" not in spans[1]
        assert eng_rules.check(
            "link",
            {"schema_version": 1, "key": "proof", "seen": {"result_contains": ["145"]}, "supports": ["value"]},
            result.trace,
            tool_access=context,
            tool_access_complete=True,
        )[0]
