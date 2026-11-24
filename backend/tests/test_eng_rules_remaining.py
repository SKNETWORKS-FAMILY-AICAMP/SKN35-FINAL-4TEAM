"""① 이름 조건과 완전한 도구 문맥의 경계."""

import pytest
from test_eng_rules import tool, trace

from slotagent.grading import eng_rules


def forbidden(selector, span, **kwargs):
    return eng_rules.check("forbidden", {"schema_version": 1, "call": selector}, trace(spans=[span]), **kwargs)


def test_name_selector_without_access():
    assert forbidden({"tool": "read_item"}, tool(1), tool_access={})[0] is False


def test_result_without_access():
    spec = {"schema_version": 1, "key": "proof", "seen": {"result_contains": ["145"]}, "supports": ["value"]}
    assert eng_rules.check("link", spec, trace(spans=[tool(1)]), tool_access={})[0] is True


def test_incomplete_invalid():
    with pytest.raises(eng_rules.RulePolicyRequired, match="tool_access_missing"):
        forbidden({"access": "write"}, tool(1, error="agent_invalid_tool_call"), tool_access={})


@pytest.mark.parametrize("access", ["read", "write"])
def test_complete_invalid(access):
    assert (
        forbidden(
            {"access": access}, tool(1, error="agent_invalid_tool_call"), tool_access={}, tool_access_complete=True
        )[0]
        is True
    )


def test_name_invalid():
    with pytest.raises(eng_rules.RulePolicyRequired, match="error_call_policy_missing"):
        forbidden(
            {"tool": "read_item"},
            tool(1, error="agent_invalid_tool_call"),
            tool_access={},
            tool_access_complete=True,
        )


@pytest.mark.parametrize("error", ["agent_invalid_tool_call", "tool_error"])
def test_registered_error(error):
    with pytest.raises(eng_rules.RulePolicyRequired, match="error_call_policy_missing"):
        forbidden(
            {"access": "read"},
            tool(1, error=error),
            tool_access={"read_item": "read"},
            tool_access_complete=True,
        )


@pytest.mark.parametrize("fields", [{}, {"error": "tool_error"}])
def test_unknown_executed(fields):
    with pytest.raises(eng_rules.RulePolicyRequired, match="tool_access_missing"):
        forbidden({"access": "write"}, tool(1, **fields), tool_access={}, tool_access_complete=True)


@pytest.mark.parametrize("context,complete", [(None, True), ({}, 1), ({}, "true"), ({}, None)])
def test_invalid_completeness(context, complete):
    with pytest.raises(ValueError):
        forbidden({"access": "write"}, tool(1), tool_access=context, tool_access_complete=complete)


def test_complete_invalid_link_filter():
    spec = {
        "schema_version": 1,
        "key": "proof",
        "seen": {"result_contains": ["145"], "tool_access": "read"},
        "supports": ["value"],
    }
    assert (
        eng_rules.check(
            "link",
            spec,
            trace(spans=[tool(1, error="agent_invalid_tool_call")]),
            tool_access={},
            tool_access_complete=True,
        )[0]
        is False
    )
