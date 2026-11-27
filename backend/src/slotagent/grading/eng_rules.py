"""① 조건 하나의 순수 규칙 판정. 성공·관문·LLM 판정·DB 저장은 담당하지 않습니다."""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from slotagent.common import contracts
from slotagent.common.confirmation import approved_write

KINDS = {"info", "link", "order", "forbidden", "uses", "end_state", "exact_writes"}
MAX_ANSWER_DEPTH = 64
MAX_NUMBER_CHARS = 1024


class RulePolicyRequired(NotImplementedError):
    """계약·문항 정책·의미 판정이 더 필요합니다. 조건 실패로 저장하면 안 됩니다."""

    def __init__(self, code: str, key: str | None = None):
        self.code, self.key = code, key
        super().__init__(f"{code} (key={key})")


class TraceError(ValueError):
    """이 풀이의 실행 기록이 잘못됐습니다. 조건·코드 결함과 달리 다른 풀이의 채점은 계속할 수 있습니다."""


class _NumberRangeError(ValueError):
    """숫자처럼 생겼지만 비교 표현 범위를 넘은 값입니다."""


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("유한한 JSON 값이 필요합니다.") from exc


def _json_quality(value, *, model=False, error=ValueError):
    """jsonb가 거절할 NUL·surrogate·비유한 수를 검사합니다. 원문은 오류에 넣지 않습니다."""

    def fail(code):
        if model:
            raise RulePolicyRequired(code)
        raise error(f"조건 또는 trace 자체의 JSON 값이 올바르지 않습니다: {code}")

    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (dict, list)):
            depth += 1
            if depth > (MAX_ANSWER_DEPTH if model else 256):
                fail("answer_nesting_limit")
            values = [*item.keys(), *item.values()] if isinstance(item, dict) else item
            stack.extend((child, depth) for child in values)
        elif isinstance(item, str):
            if "\x00" in item:
                fail("answer_nul")
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                fail("answer_invalid_unicode")
        elif isinstance(item, float) and not math.isfinite(item):
            fail("answer_nonfinite_number")
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            fail("answer_invalid_json_value")


def _scan_answer(raw):
    _json_quality(raw, model=True)
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_ANSWER_DEPTH:
                raise RulePolicyRequired("answer_nesting_limit")
        elif char in "]}":
            depth -= 1


def _answer_int(text):
    if len(text) > MAX_NUMBER_CHARS:
        raise RulePolicyRequired("answer_number_limit")
    return int(text)


def _answer_float(text):
    if len(text) > MAX_NUMBER_CHARS:
        raise RulePolicyRequired("answer_number_limit")
    try:
        value, original = float(text), Decimal(text)
    except (ValueError, OverflowError, InvalidOperation):
        raise RulePolicyRequired("answer_number_out_of_range") from None
    if not math.isfinite(value) or not original.is_finite() or (value == 0 and original != 0):
        raise RulePolicyRequired("answer_number_out_of_range")
    return value


def _answer_constant(_):
    raise RulePolicyRequired("answer_nonfinite_number")


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("숫자 비교 값이 아닙니다.")
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not re.fullmatch(r"[+-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text):
        raise ValueError("숫자 표기가 아닙니다.")
    try:
        result = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise _NumberRangeError("숫자 표현 범위를 넘었습니다.") from exc
    if not result.is_finite():
        raise _NumberRangeError("유한한 숫자가 필요합니다.")
    return result


def _timezone_needed(value):
    return isinstance(value, str) and bool(
        re.search(r"\d{4}-\d{2}-\d{2}[Tt ]\d|(?:Z|UTC|GMT)$|[+-]\d{2}:\d{2}$", value)
    )


def _time(value):
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    match = re.fullmatch(r"(?:(\d{1,2}):(\d{2})|(\d{1,2})\s*시\s*(\d{1,2})\s*분)", text)
    if not match:
        return None
    hour, minute = map(int, match.groups()[:2] if match[1] is not None else match.groups()[2:])
    return f"{hour:02}:{minute:02}" if hour < 24 and minute < 60 else None


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _expected(spec):
    value, mode = spec["expected"], spec["match"]
    _canonical(value)
    if mode == "number":
        _number(value)
    elif mode == "set_equal":
        if not isinstance(value, list):
            raise ValueError("set_equal expected는 배열이어야 합니다.")
    elif mode in {"normalized", "contains", "time_hhmm", "date"}:
        if not isinstance(value, str):
            raise ValueError("이 비교의 expected는 문자열이어야 합니다.")
        if mode in {"time_hhmm", "date"} and _timezone_needed(value):
            raise RulePolicyRequired("timezone_context_missing")
        if mode == "time_hhmm" and _time(value) is None:
            raise ValueError("expected는 시:분 또는 시/분 표기여야 합니다. 24시는 변환하지 않습니다.")
        if mode == "date" and _date(value) is None:
            raise ValueError("expected는 유효한 ISO 날짜여야 합니다.")
    if mode != "set_equal":
        for bad in spec.get("must_not", []):
            _expected({**spec, "expected": str(bad) if mode in {"normalized", "contains"} else bad, "must_not": []})


def _compare(actual, expected, mode):
    if actual is None:
        return False, None
    if mode == "exact":
        return _canonical(actual) == _canonical(expected), actual
    if mode == "normalized":
        value = _normalized(actual) if isinstance(actual, str) else None
        return value == _normalized(expected), value
    if mode == "contains":
        return isinstance(actual, str) and expected in actual, actual
    if mode == "set_equal":
        if not isinstance(actual, list):
            return False, actual if not isinstance(actual, dict) else None
        return {_canonical(v) for v in actual} == {_canonical(v) for v in expected}, actual
    if mode == "number":
        if isinstance(actual, str):
            text = unicodedata.normalize("NFKC", actual).strip()
            if text.casefold().lstrip("+-") in {"nan", "inf", "infinity"}:
                raise RulePolicyRequired("answer_nonfinite_number")
            if len(text) > MAX_NUMBER_CHARS and re.fullmatch(r"[0-9eE+.,\-\s]+", text):
                raise RulePolicyRequired("answer_number_limit")
        try:
            value = _number(actual)
        except _NumberRangeError:
            raise RulePolicyRequired("answer_number_out_of_range") from None
        except ValueError:
            return False, actual if isinstance(actual, (str, int, float)) else None
        return value == _number(expected), str(value)
    if _timezone_needed(actual):
        # 이 API에는 팩의 기준 시간대가 없습니다. 호스트 시간대를 쓰지 않습니다.
        raise RulePolicyRequired("timezone_context_missing")
    value = _time(actual) if mode == "time_hhmm" else _date(actual)
    expected = _time(expected) if mode == "time_hhmm" else _date(expected)
    return value is not None and value == expected, value if value is not None else actual


def _evidence(seqs, found):
    if isinstance(found, (bool, dict)):
        # evidence 단일 값에는 boolean/object가 없으므로 비교 값 배열에 보존합니다.
        found = [found]
    result = {"span_seqs": sorted(set(seqs)), "found": copy.deepcopy(found)}
    _json_quality(result)
    contracts.validate("grading", result, part="condition_evidence")
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RulePolicyRequired("answer_duplicate_key")
        result[key] = value
    return result


def _info(spec, trace):
    _expected(spec)
    raw = trace["final_answer"]
    if raw is None or not raw.strip():
        return False, _evidence([], None)
    _scan_answer(raw)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_int=_answer_int,
            parse_float=_answer_float,
            parse_constant=_answer_constant,
        )
    except RecursionError:
        raise RulePolicyRequired("answer_nesting_limit") from None
    except ValueError:
        raise RulePolicyRequired("answer_not_json_object") from None
    _json_quality(value, model=True)
    if value is None or value == "":
        return False, _evidence([], None)
    if not isinstance(value, dict):
        raise RulePolicyRequired("answer_not_json_object")
    if spec["key"] not in value:
        raise RulePolicyRequired("answer_key_missing")
    value = value[spec["key"]]
    _canonical(value)
    if value is None or value == "":
        return False, _evidence([], value)
    passed, found = _compare(value, spec["expected"], spec["match"])
    for bad in spec.get("must_not", []):
        if spec["match"] == "set_equal":
            blocked = isinstance(value, list) and any(_canonical(item) == _canonical(bad) for item in value)
        else:
            blocked, _ = _compare(
                value, str(bad) if spec["match"] in {"normalized", "contains"} else bad, spec["match"]
            )
        passed = passed and not blocked
    seqs = [s["seq"] for s in trace["spans"] if s["kind"] == "llm" and s.get("output") == raw]
    return passed, _evidence([max(seqs)] if seqs else [], found)


def _includes(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and _includes(actual[k], v) for k, v in expected.items())
    return _canonical(actual) == _canonical(expected)


def _access(span, writes, tool_access=None, complete=False):
    if tool_access is not None:
        if span["name"] not in tool_access:
            if complete and span.get("error") == "agent_invalid_tool_call":
                # 완전 문맥에 없는 이름은 엔진이 실행 전에 거절한 호출입니다.
                return None
            raise RulePolicyRequired("tool_access_missing")
        return tool_access[span["name"]]
    declared = span.get("attributes", {}).get("access")
    if span["seq"] in writes:
        if declared is not None and declared != "write":
            raise TraceError("쓰기 기록과 span access가 다릅니다.")
        return "write"
    if declared is None:
        raise RulePolicyRequired("tool_access_missing")
    if not isinstance(declared, str) or declared not in {"read", "write", "builtin"}:
        raise RulePolicyRequired("tool_access_unknown")
    return declared


def _rule_capabilities(span, rules):
    """범용 도구의 호출별 기능. 인자 값이 pattern 에 통째로 맞는 줄의 기능들."""
    found = set()
    for rule in rules:
        value = span.get("tool_args", {}).get(rule["arg"])
        if not isinstance(value, str):
            continue
        try:
            hit = re.fullmatch(rule["pattern"], value)
        except (re.error, OverflowError, RecursionError):
            # 등록 검사를 거치지 않은 잘못된 정규식. 채점을 멈추지 않고 이 호출만 판정 불가로 둡니다.
            raise RulePolicyRequired("call_capability_pattern_invalid") from None
        if hit:
            found.add(rule["capability"])
    return found


def is_unexecuted(span, tool_access, complete):
    """엔진 내장 도구이거나, 실행 전에 거절된 호출(없는 이름·인자 오류 = agent_invalid_tool_call).

    둘 다 업무 도구를 쓴 것이 아니라 기능·승인·정책 검사에서 뺍니다. 완전한 문맥에서만 단정합니다.
    """
    if tool_access is None or not complete:
        return False
    if tool_access.get(span["name"]) == "builtin":
        return True
    return span.get("error") == "agent_invalid_tool_call"


def _call_found(span, context):
    """이 호출이 할 수 있는 기능 집합 (비어 있지 않음). 정할 수 없으면 RulePolicyRequired.

    호출별 매핑이 있으면 그 결과만 씁니다. 매핑상 둘 이상이면 찾는 기능이 밖에 있어도 단정하지 않습니다.
    매핑이 없으면 도구의 capabilities 전체이며, 둘 이상인지는 부르는 쪽이 봅니다.
    """
    if context is None or span["name"] not in context.tool_capabilities:
        raise RulePolicyRequired("tool_capabilities_missing")
    rules = context.call_capabilities.get(span["name"])
    if not rules:
        found = set(context.tool_capabilities[span["name"]])
        if not found:
            raise RulePolicyRequired("tool_capabilities_missing")
        return found
    found = _rule_capabilities(span, rules)
    if not found:
        raise RulePolicyRequired("call_capability_unknown")
    if len(found) > 1:
        raise RulePolicyRequired("call_capability_ambiguous")
    return found


def call_capability(span, context, tool_access=None, complete=False):
    """호출 하나의 기능 이름표 하나. 업무 기능이 없는 호출(내장 도구·거절된 호출)은 None.

    config_snapshot 의 도구 정의(ConfirmationContext)에서만 정하고 trace 값은 쓰지 않습니다.
    정할 수 없으면 RulePolicyRequired 입니다.
    """
    if is_unexecuted(span, tool_access, complete):
        return None
    found = _call_found(span, context)
    if len(found) > 1:
        raise RulePolicyRequired("call_capability_ambiguous")
    return found.pop()


def _capability_matches(span, capability, context, tool_access=None, complete=False):
    if is_unexecuted(span, tool_access, complete):
        return False
    found = _call_found(span, context)
    if capability not in found:
        return False
    if len(found) > 1:
        # 여러 일을 하는 도구인데 호출별 매핑이 없으면 이 호출이 그 일인지 모릅니다.
        raise RulePolicyRequired("call_capability_ambiguous")
    return True


def _matches(span, selector, writes, tool_access=None, complete=False, context=None):
    if "tool" in selector and span.get("name") != selector["tool"]:
        return False
    if not _includes(span.get("tool_args", {}), selector.get("args_include", {})):
        return False
    access = _access(span, writes, tool_access, complete) if "access" in selector else None
    if "access" in selector and access != selector["access"]:
        return False
    return "capability" not in selector or _capability_matches(
        span, selector["capability"], context, tool_access, complete
    )


def _calls(spans, selector, writes, tool_access=None, complete=False, context=None):
    matches, unknown = [], []
    for span in spans:
        try:
            if _matches(span, selector, writes, tool_access, complete, context):
                matches.append(span)
        except RulePolicyRequired as exc:
            unknown.append(exc)
    return matches, unknown


def _no_error(spans):
    if any("error" in s for s in spans):
        raise RulePolicyRequired("error_call_policy_missing")


def _pending(matched, unknown):
    pending = list(unknown)
    if any("error" in span for span in matched):
        pending.append(RulePolicyRequired("error_call_policy_missing"))
    return pending


def _raise_pending(pending):
    if pending:
        raise min(pending, key=lambda exc: exc.code)


def _context(value):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("신뢰한 도구 문맥은 이름→access mapping이어야 합니다.")
    result = dict(value)
    for name, access in result.items():
        contracts.validate("common", name, part="tool_name")
        if not isinstance(access, str) or access not in {"read", "write", "builtin"}:
            raise ValueError("문맥 access는 read/write/builtin이어야 합니다.")
    return result


def _validate_access(spans, writes, intents, tool_access):
    for span in spans:
        if span["kind"] != "tool":
            continue
        declared = span.get("attributes", {}).get("access")
        if span["seq"] in writes and declared is not None and declared != "write":
            raise TraceError("쓰기 기록과 trace access가 충돌합니다.")
        if tool_access is not None and span["name"] in tool_access:
            trusted = tool_access[span["name"]]
            if declared is not None and declared != trusted:
                raise TraceError("신뢰 문맥과 trace access가 충돌합니다.")
            if span["seq"] in writes and trusted != "write":
                raise TraceError("신뢰 문맥과 쓰기 기록이 충돌합니다.")
    if tool_access is not None:
        for intent in intents:
            if intent["name"] in tool_access and tool_access[intent["name"]] != "write":
                raise TraceError("쓰기 도구 이름의 신뢰 문맥이 충돌합니다.")


@dataclass(frozen=True)
class ConfirmationContext:
    """승인 재검증용 신뢰 문맥. 문항 정책과 config_snapshot에서만 만들고 trace 값으로 채우지 않습니다.

    policy=None은 "고정 답 없음"입니다. 문맥 자체가 없는 것(판정 불가)과 다릅니다.
    """

    policy: dict | None
    write_tools: frozenset[str]
    tool_capabilities: Mapping[str, list[str]]
    # 범용 도구의 호출별 기능 (tool_def.call_capabilities). 없는 도구는 capabilities 로 정합니다.
    call_capabilities: Mapping[str, list[dict]] = field(default_factory=dict)


def _approved(span, trace, context):
    if context is None:
        raise RulePolicyRequired("confirmation_policy_context_missing")
    if span["name"] not in context.write_tools:
        raise RulePolicyRequired("confirmation_write_tool_missing")
    if not context.tool_capabilities.get(span["name"]):
        # P-13: 이름표 누락은 등록 확인 대상이며 후보 실패로 단정하지 않습니다.
        raise RulePolicyRequired("tool_capabilities_missing")
    # boolean(user_confirmed)은 믿지 않고 현재 시도의 확인·쓰기 기록을 처음부터 다시 봅니다.
    return approved_write(
        context.policy, trace, span["seq"], set(context.write_tools), dict(context.tool_capabilities)
    )


def _check(kind: str, spec: dict, trace: dict, tool_access=None, complete=False, confirmation=None):
    """조건 단위 passed/evidence만 반환합니다. 정책 부족·잘못된 입력은 예외입니다."""
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("지원하지 않는 정답 조건 kind입니다.")
    contracts.validate("answer_condition", spec, part=kind)
    contracts.validate("trace", trace)
    tool_access = _context(tool_access)
    if not isinstance(complete, bool) or (complete and tool_access is None):
        raise ValueError("문맥 완전성은 bool이며 완전한 경우 명시한 도구 문맥이 필요합니다.")
    _json_quality(spec)
    structural = {key: value for key, value in trace.items() if key != "final_answer"}
    structural["spans"] = [
        {key: value for key, value in span.items() if not (span["kind"] == "llm" and key == "output")}
        for span in trace["spans"]
    ]
    # 모델 원문은 info에서 별도 분류합니다. 다른 확정 조건의 채점을 막지 않습니다.
    _json_quality(structural, error=TraceError)
    _canonical(spec)
    _canonical(trace)
    spans = sorted(trace["spans"], key=lambda s: s["seq"])
    by_seq = {s["seq"]: s for s in spans}
    if len(by_seq) != len(spans):
        raise TraceError("span seq가 중복됐습니다.")
    writes, intents = set(), []
    for intent in trace["write_intents"]:
        span = by_seq.get(intent["span_seq"])
        if span is None or span["kind"] != "tool":
            raise TraceError("쓰기 기록의 span 참조가 올바르지 않습니다.")
        writes.add(intent["span_seq"])
        # end_state는 호출 입력이 아니라 기록된 쓰기의 이름·payload를 비교합니다.
        # 하나의 호출이 여러 쓰기 기록을 남길 수 있으며 계약에 없는 1:1 제약은 넣지 않습니다.
        intents.append(
            {
                **span,
                "name": intent["tool_name"],
                "tool_args": intent["payload"],
                "attributes": {**span.get("attributes", {}), "access": "write"},
            }
        )
    _validate_access(spans, writes, intents, tool_access)
    intents.sort(key=lambda span: (span["seq"], span["name"], _canonical(span["tool_args"])))
    if kind == "info":
        return _info(spec, trace)
    tools = [s for s in spans if s["kind"] == "tool"]
    if kind == "link":
        tokens = spec["seen"]["result_contains"]
        normal, pending = [], []
        for span in tools:
            if not all(token in span.get("tool_result", "") for token in tokens):
                continue
            try:
                if "tool_access" in spec["seen"]:
                    access = _access(span, writes, tool_access, complete)
                    if "tool_access" in spec["seen"] and access != spec["seen"]["tool_access"]:
                        continue
            except RulePolicyRequired as exc:
                pending.append(exc)
                continue
            if "error" in span:
                pending.append(RulePolicyRequired("error_call_policy_missing"))
            else:
                normal.append(span)
        if normal:
            return True, _evidence([normal[0]["seq"]], tokens)
        _raise_pending(pending)
        return False, _evidence([], [])
    if kind == "order":
        before, unknown_before = _calls(tools, spec["before"], writes, tool_access, complete, confirmation)
        after, unknown_after = _calls(tools, spec["after"], writes, tool_access, complete, confirmation)
        if unknown_before or unknown_after:
            raise (unknown_before + unknown_after)[0]
        _no_error(before + after)
        if len(before) > 1 or len(after) > 1:
            raise RulePolicyRequired("repeated_order_policy_missing")
        passed = bool(before and after and before[0]["seq"] < after[0]["seq"])
        return passed, _evidence([s["seq"] for s in before + after], [s["seq"] for s in before + after])
    if kind == "uses":
        # 호출했다는 것까지만 증명합니다. 결과를 근거로 답했는지는 link 가 봅니다.
        matched, unknown = _calls(tools, spec["call"], writes, tool_access, complete, confirmation)
        normal = [span for span in matched if "error" not in span]
        if normal:
            return True, _evidence([s["seq"] for s in normal], [s["name"] for s in normal])
        _raise_pending(_pending(matched, unknown))
        return False, _evidence([], [])
    if kind == "forbidden":
        matched, unknown = _calls(tools, spec["call"], writes, tool_access, complete, confirmation)
        normal = [span for span in matched if "error" not in span]
        if normal and spec.get("unless_user_confirmed"):
            normal = [span for span in normal if not _approved(span, trace, confirmation)]
        if normal:
            return False, _evidence([s["seq"] for s in normal], [s["name"] for s in normal])
        _raise_pending(_pending(matched, unknown))
        return True, _evidence([], [])
    if kind == "exact_writes":
        from slotagent.grading.eng_writes import check_exact_writes  # 순환 import 방지

        if confirmation is None:
            raise RulePolicyRequired("tool_capabilities_missing")
        return check_exact_writes(spec, trace, confirmation.tool_capabilities)
    if spec["write_intents"] == "none":
        return not intents, _evidence(list(writes), [s["name"] for s in intents])
    used, pending, missing = [], [], False
    for selector in spec["write_intents"]:
        matched, unknown = _calls(intents, selector, writes, tool_access, complete, confirmation)
        normal = [span for span in matched if "error" not in span]
        if normal:
            used.extend(normal)
        else:
            uncertain = _pending(matched, unknown)
            pending.extend(uncertain)
            missing = missing or not uncertain
    if missing:
        return False, _evidence([], [])
    _raise_pending(pending)
    used.sort(key=lambda span: (span["seq"], span["name"], _canonical(span["tool_args"])))
    return True, _evidence([s["seq"] for s in used], [s["name"] for s in used])


def check(
    kind: str, spec: dict, trace: dict, *, tool_access=None, tool_access_complete=False, confirmation=None
) -> tuple[bool, dict]:
    """완전성은 호출자가 명시합니다(기본 불완전). 판정 불가에는 조건 key를 보존합니다."""
    try:
        return _check(kind, spec, trace, tool_access, tool_access_complete, confirmation)
    except RulePolicyRequired as exc:
        raise RulePolicyRequired(exc.code, spec.get("key") if isinstance(spec, dict) else None) from None
