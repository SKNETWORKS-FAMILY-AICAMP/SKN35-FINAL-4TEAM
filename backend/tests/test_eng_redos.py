"""① call_capabilities 정규식 ReDoS 막기: 등록 때 위험한 모양 거절, 채점 때 값 길이 상한."""

import time

import pytest

from slotagent.common.checks import MAX_PATTERN_CHOICES, MAX_PATTERN_REPEATS, pattern_risk
from slotagent.grading import eng_rules
from slotagent.grading.eng_rules import MAX_PATTERN_VALUE_CHARS, RulePolicyRequired


@pytest.mark.parametrize("pattern", [
    "/issues",
    r"/repos/[^/]+/[^/]+/actions/runs(\?.*)?",  # 한 번 반복(?) 안의 .* 는 괜찮음
    r"(GET|POST) /deployments",  # 반복 밖 갈래
    r"[a-z]{3}-\d+",
    r"(?>a+)b",
])
def test_safe_patterns(pattern):
    assert pattern_risk(pattern) is None


@pytest.mark.parametrize("pattern, reason", [
    ("(", "읽을 수 없"),
    (r"(a+)+b", "반복 안에 반복"),
    (r"(\d{2})*x", "반복 안에 반복"),
    (r"(a|ab)*c", "갈래"),
    (r"(a)\1", "역참조"),
    (r"(?=a)a", "전후방"),
    (r"(?<!x)a", "전후방"),
    (r"(a)?(?(1)b|c)", "역참조"),
    ("a*" * (MAX_PATTERN_REPEATS + 1) + "b", "개까지"),
    # Codex 우회 3건 (11/27): ? 를 셈에서 빼면 2^n 으로 터짐
    (r"(a?a?)+b", "반복 안에 반복"),
    ("a?" * 60 + "a" * 30, "경우의 수"),
    (r"(?:a?){60}a{30}", "반복 안에 반복"),
    ("(a|a)" * 4 + "c", "경우의 수"),  # (a|b) 는 파서가 [ab] 로 바꿔 갈래가 아님
    ("a{0,5}" * 2 + "b", "경우의 수"),
])
def test_risky_patterns(pattern, reason):
    assert reason in pattern_risk(pattern)


@pytest.mark.parametrize("pattern", [
    "(a|a)" * (MAX_PATTERN_CHOICES.bit_length() - 1) + "a*" * MAX_PATTERN_REPEATS + "b",
    r"(?i)A*a*(?:a|b)*a?a?a?b",  # 허용 패턴 5만여 개 측정(D:\final_test\redos_audit)에서 가장 느렸던 모양
])
def test_worst_allowed_pattern_is_fast(pattern):
    """허용되는 가장 나쁜 모양(갈래 경우의 수 상한 × 겹치는 긴 반복 3개) × 길이 상한 값도 빨리 끝남."""
    assert pattern_risk(pattern) is None
    start = time.perf_counter()
    assert eng_rules.re.fullmatch(pattern, "a" * MAX_PATTERN_VALUE_CHARS) is None
    assert time.perf_counter() - start < 0.5


def rules(pattern):
    return [{"arg": "path", "pattern": pattern, "capability": "issue.read"}]


def test_grading_refuses_risky_pattern_and_long_value():
    span = {"tool_args": {"path": "a" * 30}}
    with pytest.raises(RulePolicyRequired, match="pattern_invalid"):
        eng_rules._rule_capabilities(span, rules(r"(a+)+b"))
    long_span = {"tool_args": {"path": "/issues" + "x" * MAX_PATTERN_VALUE_CHARS}}
    with pytest.raises(RulePolicyRequired, match="value_too_long"):
        eng_rules._rule_capabilities(long_span, rules(r"/issues.*"))
    assert eng_rules._rule_capabilities({"tool_args": {"path": "/issues"}}, rules("/issues")) == {"issue.read"}
