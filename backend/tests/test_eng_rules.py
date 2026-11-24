"""① 규칙 채점의 경계·계약 부족·골든 독립 대조. ② 평가 코드는 사용하지 않습니다."""

import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from slotagent.common import checks, contracts
from slotagent.grading import eng_rules

ROOT = Path(__file__).resolve().parents[2]


def trace(answer=None, spans=(), writes=()):
    return {"schema_version": 1, "spans": list(spans), "write_intents": list(writes), "final_answer": answer}


def tool(seq, name="read_item", *, access="read", args=None, result="145", **fields):
    return {
        "seq": seq,
        "kind": "tool",
        "name": name,
        "started_at": "2026-11-24T00:00:00Z",
        "duration_sec": 0,
        "tool_args": args or {},
        "tool_result": result,
        "attributes": {"access": access},
        **fields,
    }


def info(expected=145, match="exact", **fields):
    return {"schema_version": 1, "key": "value", "expected": expected, "match": match, **fields}


def answer(value):
    return trace(json.dumps({"value": value}, ensure_ascii=False))


@pytest.mark.parametrize(
    "kind,spec,data",
    [
        ("absent", {}, trace()),
        ("info", {}, trace()),
        ("info", info(), None),
        ("info", info(), trace(123)),
        ("info", info(float("nan")), trace("1")),
        ("info", info({}, "exact"), trace("{}")),
        ("info", info("x", "absent"), trace("x")),
        ("info", info("x", "set_equal"), trace("[]")),
    ],
)
def test_invalid_input_raises(kind, spec, data):
    with pytest.raises(ValueError):
        eng_rules.check(kind, spec, data)


@pytest.mark.parametrize(
    "match,value,passed",
    [
        ("exact", 145, True),
        ("exact", 1450, False),
        ("exact", True, False),
        ("number", 145, True),
        ("number", 1450, False),
        ("number", "1450", False),
    ],
)
def test_number_boundaries(match, value, passed):
    assert eng_rules.check("info", info(145, match), answer(value))[0] is passed


def test_free_text_needs_judgment():
    with pytest.raises(eng_rules.RulePolicyRequired, match="answer_not_json_object") as exc:
        eng_rules.check("info", info(145, "number"), trace("145가 아니다"))
    assert exc.value.code == "answer_not_json_object" and exc.value.key == "value"


@pytest.mark.parametrize(
    "expected,match,value,bad",
    [
        ([145, 148], "set_equal", [145, 148, 150], [150]),
        ("v1", "contains", "v1 / forbidden", ["forbidden"]),
        (145, "number", "145", [145]),
    ],
)
def test_must_not(expected, match, value, bad):
    assert not eng_rules.check("info", info(expected, match, must_not=bad), answer(value))[0]


@pytest.mark.parametrize("value,passed", [("1,450", True), ("１，４５０", True), ("1450.0", True), ("14,50", False)])
def test_number_notation(value, passed):
    assert eng_rules.check("info", info(1450, "number"), answer(value))[0] is passed


@pytest.mark.parametrize(
    "match,expected,value,passed",
    [
        ("time_hhmm", "18:20", "18시 20분", True),
        ("time_hhmm", "00:00", "24:00", False),
        ("time_hhmm", "18:20", "18:21", False),
        ("date", "2026-11-24", "2026-11-24", True),
        ("date", "2026-11-24", "2026-11-25", False),
        ("normalized", "hello world", "  ＨＥＬＬＯ   World  ", True),
        ("contains", "145", "01450", True),
    ],
)
def test_time_and_date(match, expected, value, passed):
    assert eng_rules.check("info", info(expected, match), answer(value))[0] is passed


@pytest.mark.parametrize("match,value", [("time_hhmm", "2026-11-24T18:20:00Z"), ("date", "2026-11-24T23:00:00-05:00")])
def test_timestamp_requires_timezone_context(match, value):
    with pytest.raises(eng_rules.RulePolicyRequired, match="timezone"):
        eng_rules.check("info", info("18:20" if match == "time_hhmm" else "2026-11-24", match), answer(value))


@pytest.mark.parametrize("match,expected", [("time_hhmm", "24:00"), ("date", "2026-02-30"), ("number", "NaN")])
def test_invalid_comparison_spec_raises(match, expected):
    with pytest.raises(ValueError):
        eng_rules.check("info", info(expected, match), answer(expected))


@pytest.mark.parametrize("value", [None, "", "null", '""', '{"value":null}', '{"value":""}'])
def test_empty_answer(value):
    assert not eng_rules.check("info", info(), trace(value))[0]


@pytest.mark.parametrize(
    "value,code",
    [
        ("{}", "answer_key_missing"),
        ("[]", "answer_not_json_object"),
        ("145", "answer_not_json_object"),
        ('{"value":145} 답', "answer_not_json_object"),
        ('답 {"value":145}', "answer_not_json_object"),
        ('{"value":145,"value":1450}', "answer_duplicate_key"),
        ('{"value":145,"other":{"x":1,"x":2}}', "answer_duplicate_key"),
    ],
)
def test_json_answer_policy(value, code):
    with pytest.raises(eng_rules.RulePolicyRequired) as exc:
        eng_rules.check("info", info(), trace(value))
    assert (exc.value.code, exc.value.key) == (code, "value")


def test_must_not_only_selected_field():
    data = trace('{"value":145,"other":150}')
    assert eng_rules.check("info", info(145, must_not=[150]), data)[0]


def test_no_external_calls(monkeypatch):
    import socket

    import psycopg

    def forbidden(*args, **kwargs):
        raise AssertionError("순수 채점에서 외부 호출을 하면 안 됩니다.")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    assert eng_rules.check("info", info(), answer(145))[0]


@pytest.mark.parametrize("value,passed", [([148, 145, 145], True), ([145], False), ([145, 148, 150], False)])
def test_set_equal(value, passed):
    assert eng_rules.check("info", info([145, 148], "set_equal"), answer(value))[0] is passed


def test_span_sequence():
    spec = {"schema_version": 1, "before": {"tool": "first"}, "after": {"tool": "last"}}
    passed, evidence = eng_rules.check("order", spec, trace(spans=[tool(20, "last"), tool(3, "first")]))
    assert passed and evidence["span_seqs"] == [3, 20]
    with pytest.raises(ValueError):
        eng_rules.check("order", spec, trace(spans=[tool(3, "first"), tool(3, "last")]))


def test_missing_before():
    spec = {"schema_version": 1, "before": {"tool": "first"}, "after": {"tool": "last"}}
    assert not eng_rules.check("order", spec, trace(spans=[tool(2, "last")]))[0]


def test_repeated_order_needs_policy():
    spec = {"schema_version": 1, "before": {"tool": "first"}, "after": {"tool": "last"}}
    with pytest.raises(eng_rules.RulePolicyRequired, match="repeated"):
        eng_rules.check("order", spec, trace(spans=[tool(1, "last"), tool(2, "first"), tool(3, "last")]))


@pytest.mark.parametrize(
    "kind,spec",
    [
        ("link", {"schema_version": 1, "key": "source", "seen": {"result_contains": ["145"]}, "supports": ["value"]}),
        ("order", {"schema_version": 1, "before": {"tool": "read_item"}, "after": {"tool": "last"}}),
        ("forbidden", {"schema_version": 1, "call": {"tool": "read_item"}}),
    ],
)
def test_error_call_needs_policy(kind, spec):
    spans = [tool(1, error="tool_error"), tool(2, "last")]
    if kind == "link":
        # 요구 변경 예외: 정상 근거까지 있는 경우는 별도 True 테스트에서 검사합니다.
        spans[1]["tool_result"] = "unrelated"
    with pytest.raises(eng_rules.RulePolicyRequired, match="error_call"):
        eng_rules.check(kind, spec, trace(spans=spans))


def test_blocked_write_needs_policy():
    spec = {"schema_version": 1, "call": {"access": "write"}}
    with pytest.raises(eng_rules.RulePolicyRequired, match="error_call"):
        eng_rules.check("forbidden", spec, trace(spans=[tool(1, "post", access="write", error="write_blocked")]))


def test_confirmation_needs_context():
    spec = {"schema_version": 1, "call": {"access": "write"}, "unless_user_confirmed": True}
    write = {"span_seq": 1, "tool_name": "post", "payload": {}, "in_rule_list": True, "user_confirmed": True}
    with pytest.raises(eng_rules.RulePolicyRequired, match="confirmation"):
        eng_rules.check("forbidden", spec, trace(spans=[tool(1, "post", access="write")], writes=[write]))


def test_missing_access_needs_context():
    span = tool(1)
    span["attributes"] = {}
    with pytest.raises(eng_rules.RulePolicyRequired, match="access"):
        eng_rules.check("forbidden", {"schema_version": 1, "call": {"access": "write"}}, trace(spans=[span]))


def test_unknown_access_needs_context():
    with pytest.raises(eng_rules.RulePolicyRequired, match="tool_access_unknown"):
        eng_rules.check(
            "forbidden", {"schema_version": 1, "call": {"access": "write"}}, trace(spans=[tool(1, access="unknown")])
        )


def test_link_plain_text():
    spec = {
        "schema_version": 1,
        "key": "source",
        "seen": {"result_contains": ["PR #214", "sha-a"]},
        "supports": ["value"],
    }
    assert eng_rules.check("link", spec, trace(spans=[tool(8, result="PR #214 -> sha-a (not JSON)")])) == (
        True,
        {"span_seqs": [8], "found": ["PR #214", "sha-a"]},
    )


def test_link_same_result():
    spec = {"schema_version": 1, "key": "source", "seen": {"result_contains": ["145", "sha-a"]}, "supports": ["value"]}
    assert not eng_rules.check("link", spec, trace(spans=[tool(1, result="145"), tool(2, result="sha-a")]))[0]


def test_end_state():
    none = {"schema_version": 1, "write_intents": "none"}
    expected = {"schema_version": 1, "write_intents": [{"access": "write", "args_include": {"nested": {"id": 145}}}]}
    span = tool(5, "post", access="write", args={"nested": {"id": 145, "extra": 2}})
    write = {"span_seq": 5, "tool_name": "post", "payload": span["tool_args"], "in_rule_list": True}
    data = trace(spans=[span], writes=[write])
    assert eng_rules.check("end_state", none, trace()) == (True, {"span_seqs": [], "found": []})
    assert not eng_rules.check("end_state", none, data)[0]
    assert eng_rules.check("end_state", expected, data)[0]
    data["write_intents"][0]["span_seq"] = 99
    with pytest.raises(ValueError):
        eng_rules.check("end_state", expected, data)


def test_end_state_uses_write_payload():
    span = tool(1, "post", access="write", args={"request": {"channel": "ops"}})
    write = {"span_seq": 1, "tool_name": "post", "payload": {"channel": "ops"}, "in_rule_list": True}
    spec = {"schema_version": 1, "write_intents": [{"tool": "post", "args_include": {"channel": "ops"}}]}
    assert eng_rules.check("end_state", spec, trace(spans=[span], writes=[write]))[0]


def test_multiple_write_intents_same_span():
    span = tool(1, "post", access="write", args={"channels": ["a", "b"]})
    writes = [
        {"span_seq": 1, "tool_name": "post", "payload": {"channel": channel}, "in_rule_list": True}
        for channel in ["a", "b"]
    ]
    spec = {
        "schema_version": 1,
        "write_intents": [{"args_include": {"channel": channel}, "access": "write"} for channel in ["a", "b"]],
    }
    passed, evidence = eng_rules.check("end_state", spec, trace(spans=[span], writes=writes))
    assert passed and evidence["span_seqs"] == [1]


def test_long_answer():
    value = "x" * (1024 * 1024)
    assert eng_rules.check("info", info(value), answer(value))[0]


def test_evidence_and_gate():
    data = answer([148, 145])
    before = copy.deepcopy(data)
    passed, evidence = eng_rules.check("info", info([145, 148], "set_equal", gate=False), data)
    assert passed and not checks.condition_gate("info", info(gate=False))
    assert checks.condition_gate("forbidden", {"schema_version": 1, "call": {"access": "write"}})
    contracts.validate("grading", evidence, part="condition_evidence")
    evidence["found"].append(999)
    assert data == before


@pytest.mark.parametrize("change", ["trace_access", "write", "write_name"])
def test_context_conflict(change):
    span = tool(1, "post", access="write")
    writes = []
    context = {"post": "read", "other": "read"}
    if change != "trace_access":
        span["attributes"] = {}
        writes = [
            {
                "span_seq": 1,
                "tool_name": "other" if change == "write_name" else "post",
                "payload": {},
                "in_rule_list": True,
            }
        ]
        if change == "write_name":
            context["post"] = "write"
    with pytest.raises(ValueError):
        eng_rules.check("info", info(), trace('{"value":145}', [span], writes), tool_access=context)


def test_context_missing():
    with pytest.raises(eng_rules.RulePolicyRequired, match="tool_access_missing"):
        eng_rules.check(
            "forbidden", {"schema_version": 1, "call": {"access": "write"}}, trace(spans=[tool(1)]), tool_access={}
        )
    # 고정 snapshot에서 만든 문맥은 trace에 access가 없어도 동작합니다.
    span = tool(1)
    span["attributes"] = {}
    assert eng_rules.check(
        "forbidden",
        {"schema_version": 1, "call": {"access": "write"}},
        trace(spans=[span]),
        tool_access={"read_item": "read"},
    )[0]


@pytest.mark.parametrize("context", [[], {"read_item": "admin"}, {1: "read"}, {"read_item": None}])
def test_invalid_context(context):
    with pytest.raises(ValueError):
        eng_rules.check("info", info(), answer(145), tool_access=context)


@pytest.mark.parametrize("reverse", [False, True])
def test_forbidden_definite_first(reverse):
    spans = [
        tool(1, "post", access="write", error="blocked"),
        tool(2, "unknown", access="write"),
        tool(3, "post", access="write"),
    ]
    if reverse:
        spans.reverse()
    result = eng_rules.check(
        "forbidden",
        {"schema_version": 1, "call": {"access": "write"}},
        trace(spans=spans),
        tool_access={"post": "write"},
    )
    assert result == (False, {"span_seqs": [3], "found": ["post"]})


@pytest.mark.parametrize("kind", ["forbidden", "link", "end_state"])
def test_uncertain_only(kind):
    span = tool(1, "post", access="write", result="145", error="blocked")
    specs = {
        "forbidden": {"schema_version": 1, "call": {"access": "write"}},
        "link": {"schema_version": 1, "key": "proof", "seen": {"result_contains": ["145"]}, "supports": ["value"]},
        "end_state": {"schema_version": 1, "write_intents": [{"tool": "post"}]},
    }
    writes = [{"span_seq": 1, "tool_name": "post", "payload": {}, "in_rule_list": True}]
    with pytest.raises(eng_rules.RulePolicyRequired):
        eng_rules.check(kind, specs[kind], trace(spans=[span], writes=writes), tool_access={"post": "write"})


@pytest.mark.parametrize("normal_seq,error_seq,reverse", [(1, 2, False), (2, 1, False), (1, 2, True), (2, 1, True)])
def test_link_definite_first(normal_seq, error_seq, reverse):
    spans = [tool(error_seq, result="145", error="tool_error"), tool(normal_seq, result="145")]
    if reverse:
        spans.reverse()
    spec = {
        "schema_version": 1,
        "key": "proof",
        "seen": {"result_contains": ["145"], "tool_access": "read"},
        "supports": ["value"],
    }
    assert eng_rules.check("link", spec, trace(spans=spans), tool_access={"read_item": "read"}) == (
        True,
        {"span_seqs": [normal_seq], "found": ["145"]},
    )


@pytest.mark.parametrize("access,result", [("write", "145"), ("read", "not matching")])
def test_link_requires_all_filters(access, result):
    spans = [tool(1, "read_item", result="145", error="bad"), tool(2, "other", access=access, result=result)]
    spec = {
        "schema_version": 1,
        "key": "proof",
        "seen": {"result_contains": ["145"], "tool_access": "read"},
        "supports": ["value"],
    }
    with pytest.raises(eng_rules.RulePolicyRequired):
        eng_rules.check("link", spec, trace(spans=spans), tool_access={"read_item": "read", "other": access})


@pytest.mark.parametrize("reverse", [False, True])
def test_end_state_unshadowed(reverse):
    spans = [
        tool(1, "post", access="write", args={"channel": "a"}, error="blocked"),
        tool(2, "post", access="write", args={"channel": "a"}),
    ]
    writes = [
        {"span_seq": s["seq"], "tool_name": "post", "payload": s["tool_args"], "in_rule_list": True} for s in spans
    ]
    if reverse:
        spans.reverse()
        writes.reverse()
    spec = {"schema_version": 1, "write_intents": [{"tool": "post", "args_include": {"channel": "a"}}]}
    assert eng_rules.check("end_state", spec, trace(spans=spans, writes=writes), tool_access={"post": "write"}) == (
        True,
        {"span_seqs": [2], "found": ["post"]},
    )
    # 필수인 다른 쓰기가 없으면 알 수 없는 조건에 가리지 않고 False입니다.
    spec["write_intents"].append({"tool": "absent"})
    assert (
        eng_rules.check("end_state", spec, trace(spans=spans[:1], writes=writes[:1]), tool_access={"post": "write"})[0]
        is False
    )


@pytest.mark.parametrize(
    "literal,code",
    [
        ("NaN", "answer_nonfinite_number"),
        ("Infinity", "answer_nonfinite_number"),
        ("-Infinity", "answer_nonfinite_number"),
        ("1e9999", "answer_number_out_of_range"),
        ("1" * 5000, "answer_number_limit"),
        ('"' + "1" * 5000 + '"', "answer_number_limit"),
        ("1e-" + "9" * 40, "answer_number_out_of_range"),
        ('"1e' + "9" * 40 + '"', "answer_number_out_of_range"),
    ],
)
def test_answer_numeric_limits(literal, code):
    with pytest.raises(eng_rules.RulePolicyRequired) as exc:
        eng_rules.check("info", info(145, "number"), trace('{"value":' + literal + "}"))
    assert (exc.value.code, exc.value.key) == (code, "value")


@pytest.mark.parametrize(
    "literal,code",
    [
        ('"\\u0000"', "answer_nul"),
        ('"\x00"', "answer_nul"),
        ('"\\ud800"', "answer_invalid_unicode"),
        ('"\udfff"', "answer_invalid_unicode"),
        ("[" * 1000 + "0" + "]" * 1000, "answer_nesting_limit"),
    ],
)
def test_answer_text_limits(literal, code):
    with pytest.raises(eng_rules.RulePolicyRequired) as exc:
        eng_rules.check("info", info(), trace('{"value":' + literal + "}"))
    assert (exc.value.code, exc.value.key) == (code, "value")


@pytest.mark.parametrize(
    "literal",
    [
        '"한글😀"',
        '"\\ud83d\\ude00"',
        '"line\\nend"',
        "1" * 1024,
        "NaN",
        '"\\u0000"',
        '"\\ud800"',
        "[" * 1000 + "0" + "]" * 1000,
        pytest.param("1" * 5000, id="oversized_integer"),
        pytest.param('"' + "1" * 5000 + '"', id="long_numeric_text"),
        pytest.param("Infinity", id="infinity"),
        pytest.param("1e9999", id="float_overflow"),
        pytest.param("[" * 63 + "0" + "]" * 63, id="depth64"),
        pytest.param('"' + "x" * (1024 * 1024) + '"', id="1MiB_text"),
    ],
)
def test_evidence_jsonb(pg, literal):
    import psycopg
    from psycopg.types.json import Jsonb

    data = trace('{"value":' + literal + "}")
    try:
        _, evidence = eng_rules.check("info", info(145, "exact"), data)
    except eng_rules.RulePolicyRequired as exc:
        # 판정 불가에는 score/evidence를 만들지 않고 안전한 사유 메타데이터만 저장 검사합니다.
        payload = {"code": exc.code, "key": exc.key}
    else:
        contracts.validate("grading", evidence, part="condition_evidence")
        payload = evidence
    with psycopg.connect(pg, autocommit=True) as conn:
        # 세션 TEMP 테이블만 쓰며 제품 스키마·마이그레이션은 변경하지 않습니다.
        conn.execute("CREATE TEMP TABLE sa_eng_rules_probe (evidence jsonb NOT NULL)")
        conn.execute("INSERT INTO sa_eng_rules_probe VALUES (%s)", (Jsonb(payload),))
        assert conn.execute("SELECT evidence FROM sa_eng_rules_probe").fetchone()[0] == payload


@pytest.mark.parametrize("target", ["condition", "trace"])
def test_invalid_structural_values(target):
    spec, data = info("ok"), answer("ok")
    if target == "condition":
        spec["expected"] = "\x00"
    else:
        data["spans"] = [tool(1, result="\ud800")]
    with pytest.raises(ValueError):
        eng_rules.check("info", spec, data)


def test_model_output_is_not_structural_fault():
    raw = '{"value":"\\u0000"}'
    model = {"seq": 1, "kind": "llm", "output": raw + "\x00", "started_at": "2026-11-24T00:00:00Z", "duration_sec": 0}
    with pytest.raises(eng_rules.RulePolicyRequired) as exc:
        eng_rules.check("info", info(), trace(raw, [model]))
    assert exc.value.code == "answer_nul"
    # 모델 답을 쓸 필요가 없는 확정 금지 호출의 증거에는 잘못된 모델 원문을 넣지 않습니다.
    result = eng_rules.check(
        "forbidden",
        {"schema_version": 1, "call": {"tool": "post"}},
        trace(raw, [model, tool(2, "post", access="write")]),
    )
    assert result == (False, {"span_seqs": [2], "found": ["post"]})


def test_context_snapshot_and_builtin():
    from types import MappingProxyType

    snapshot = json.loads((ROOT / "contracts/examples/config_snapshot.B.json").read_text(encoding="utf-8"))
    contracts.validate("config_snapshot", snapshot)
    context = MappingProxyType({t["name"]: t["access"] for t in snapshot["tools"]})
    assert (
        eng_rules.check(
            "forbidden",
            {"schema_version": 1, "call": {"access": "write"}},
            trace(spans=[tool(1, "post_message", access="write")]),
            tool_access=context,
        )[0]
        is False
    )
    assert eng_rules.check(
        "forbidden",
        {"schema_version": 1, "call": {"access": "write"}},
        trace(spans=[tool(1, "request_user_confirmation", access="builtin")]),
        tool_access={"request_user_confirmation": "builtin"},
    )[0]


def golden_audit(*, use_context=True):
    """참조 판정기를 읽지 않고 조건과 고정 expected만 독립적으로 비교합니다."""
    root = ROOT / "packs" / "it_ops" / "v0.1"
    pack = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    groups = json.loads((root / "groups.json").read_text(encoding="utf-8"))["groups"]
    group_of = {code: name for name, group in groups.items() for code in group["template_codes"]}
    tasks = {t["code"]: t for t in pack["tasks"]}
    manifest_path = root / "practice/servers.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    authority = {}
    for service in manifest["services"]:
        for definition in service["tools"]:
            name, access = definition["name"], definition["access"]
            if name in authority and authority[name] != access:
                raise ValueError("동일 manifest의 도구 권한이 충돌합니다.")
            authority[name] = access
    kwargs = {"tool_access": authority} if use_context else {}
    source_calls, missing_tools = Counter(), Counter()
    comparisons = []
    counts = defaultdict(Counter)
    differences, undecidable, mutations = [], [], []
    missing_in_prompt = [
        {"task": t["code"], "key": c["spec"]["key"], "seq": c["seq"], "group": group_of[t["template"]]}
        for t in pack["tasks"]
        for c in t["conditions"]
        if c["kind"] == "info" and c["spec"]["key"] not in t["prompt"]
    ]
    for golden in pack["golden"]:
        data = json.loads((root / golden["trace"]).read_text(encoding="utf-8"))
        codes = {s.get("attributes", {}).get("golden.task_code") for s in data["spans"]}
        codes.discard(None)
        if golden.get("task_code"):
            codes.add(golden["task_code"])
        if len(codes) != 1 or next(iter(codes)) not in tasks:
            raise ValueError("골든 문항 연결이 없거나 서로 다릅니다.")
        task = tasks[next(iter(codes))]
        for span in data["spans"]:
            if span["kind"] == "tool":
                source_calls["servers.json" if span["name"] in authority else "missing"] += 1
                if span["name"] not in authority:
                    missing_tools[span["name"]] += 1
        checks.check_task_conditions(task["conditions"])
        group = group_of[task["template"]]
        local_diffs, local_unknown, outcomes = [], [], {}
        for condition in task["conditions"]:
            seq = str(condition["seq"])
            expected = golden["expected"]["conditions"][seq]
            try:
                actual, evidence = eng_rules.check(condition["kind"], condition["spec"], data, **kwargs)
                contracts.validate("grading", evidence, part="condition_evidence")
                outcomes[seq] = actual
                if actual != expected:
                    local_diffs.append(
                        {
                            "task": task["code"],
                            "golden": golden["kind"],
                            "seq": seq,
                            "expected": expected,
                            "actual": actual,
                            "suspect": "조건 / 골든 검토",
                        }
                    )
            except eng_rules.RulePolicyRequired as exc:
                actual = "판정 불가"
                local_unknown.append(
                    {
                        "task": task["code"],
                        "golden": golden["kind"],
                        "seq": seq,
                        "expected": expected,
                        "actual": "판정 불가",
                        "suspect": "계약 부족",
                        "reason": exc.code,
                    }
                )
            comparisons.append(
                {
                    "task": task["code"],
                    "golden": golden["kind"],
                    "seq": seq,
                    "kind": condition["kind"],
                    "expected": expected,
                    "actual": actual,
                    "reason": local_unknown[-1]["reason"] if actual == "판정 불가" else None,
                }
            )
        # 전체 success는 제품 check에서 정하지 않고, 대조 도구에서 공통 gate로만 계산합니다.
        gates = [c for c in task["conditions"] if checks.condition_gate(c["kind"], c["spec"])]
        if all(str(c["seq"]) in outcomes for c in gates):
            aggregate = all(outcomes[str(c["seq"])] for c in gates)
            if aggregate != golden["expected"]["success"]:
                local_diffs.append(
                    {
                        "task": task["code"],
                        "golden": golden["kind"],
                        "seq": "gate",
                        "expected": golden["expected"]["success"],
                        "actual": aggregate,
                        "suspect": "조건 / 골든 / 제품에 없는 검사",
                    }
                )
        counts[group]["불일치" if local_diffs else "판정 불가" if local_unknown else "일치"] += 1
        differences.extend(local_diffs)
        undecidable.extend(local_unknown)
        if golden["kind"] in {"success", "alt_success"}:
            for c in task["conditions"]:
                if c["kind"] != "info":
                    continue
                broken = copy.deepcopy(data)
                payload = json.loads(broken["final_answer"])
                payload[c["spec"]["key"]] = (
                    ["ENG_WRONG_VALUE"] if c["spec"]["match"] == "set_equal" else "ENG_WRONG_VALUE"
                )
                broken["final_answer"] = json.dumps(payload)
                try:
                    actual, _ = eng_rules.check("info", c["spec"], broken, **kwargs)
                    mutations.append(actual)
                except eng_rules.RulePolicyRequired:
                    mutations.append(None)
    return {
        "groups": dict(counts),
        "differences": differences,
        "undecidable": undecidable,
        "mutations": mutations,
        "missing_in_prompt": missing_in_prompt,
        "info_condition_count": sum(c["kind"] == "info" for t in pack["tasks"] for c in t["conditions"]),
        "extra_labels": sum(
            "result_class" in g["expected"] or "first_fail_type" in g["expected"] for g in pack["golden"]
        ),
        "comparisons": comparisons,
        "provenance": {
            "file": str(manifest_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "definitions": authority,
            "source_calls": dict(source_calls),
            "missing_tools": dict(missing_tools),
            "snapshot_definitions": 0,
        },
    }


def test_golden_audit():
    result = golden_audit()
    assert sum(sum(counts.values()) for counts in result["groups"].values()) == 168


def test_corrupted_answers_rejected():
    mutations = golden_audit()["mutations"]
    assert len(mutations) > 0 and all(value is False for value in mutations)


def test_golden_context_audit():
    before, after = golden_audit(use_context=False), golden_audit()
    manifest = json.loads((ROOT / "packs/it_ops/v0.1/practice/servers.json").read_text(encoding="utf-8"))
    declared = {t["name"]: t["access"] for s in manifest["services"] for t in s["tools"]}
    assert after["provenance"]["definitions"] == declared
    approval = {
        (r["task"], r["golden"], r["seq"])
        for r in before["comparisons"]
        if r["reason"] == "confirmation_policy_context_missing"
    }
    assert len(approval) == 18
    after_rows = {(r["task"], r["golden"], r["seq"]): r for r in after["comparisons"]}
    assert all(after_rows[key]["actual"] == "판정 불가" for key in approval)
    assert len(after["mutations"]) == 192 and all(value is False for value in after["mutations"])
