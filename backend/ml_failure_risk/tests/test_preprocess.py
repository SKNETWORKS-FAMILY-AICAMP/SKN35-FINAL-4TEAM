"""전처리의 누출·잘림·빈 결과·중복·분할 경계를 검증한다. 모델 학습은 하지 않는다."""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preprocess as P  # noqa: E402


def tool(result='[{"number":301}]', **overrides):
    return {
        "type": "tool",
        "name": "lookup",
        "args": {"repo": "demo"},
        "result": result,
        "result_chars": len(result),
        **overrides,
    }


def row(**overrides):
    return {
        "cfg": "base",
        "cand": "B",
        "pid": "p1",
        "tpl": "T1",
        "rep": 0,
        "correct": True,
        "scope_a": True,
        "steps": [tool()],
        "final": "이슈 #301입니다.",
        "in_tokens": 10,
        "out_tokens": 5,
        **overrides,
    }


def test_feature_extraction_does_not_read_labels_or_metadata():
    raw = row()
    only_features = {k: raw[k] for k in ("steps", "final", "in_tokens", "out_tokens")}
    assert P.extract_features(only_features) == P.extract_features(raw)
    changed = {
        **raw,
        "correct": False,
        "done": False,
        "violation": True,
        "scope_a": False,
        "target": "SECRET_ANSWER",
        "cfg": "other",
        "cand": "other",
    }
    assert P.extract_features(changed) == P.extract_features(raw)


@pytest.mark.parametrize(
    "text,expected",
    [
        (" [] ", True),
        ('{"total_count":0,"workflow_runs":[]}', True),
        ('{"items": [], "truncated":', True),
        ('{"total_count":0,"items":[],', True),
        ('{"error":"Not Found"}', False),
        ('"[]"', False),
        ('{"items":[{"id":301}]}', False),
        ('{"body":"items: []"}', False),
        ('{"nested":{"items":[]}}', False),
        ('{"total_count":0}', False),
        ('[ {"items": []} ]', False),
    ],
)
def test_empty_results_are_lists_not_errors_or_quoted_text(text, expected):
    assert P.empty_result(text) is expected


def test_repeated_arguments_ignore_key_order_but_not_list_order():
    steps = [
        tool(args={"a": 1, "b": [1, 2]}),
        tool(args={"b": [1, 2], "a": 1}),
        tool(args={"a": 1, "b": [2, 1]}),
        tool(name="other", args={"a": 1, "b": [1, 2]}),
    ]
    features = P.extract_features(row(steps=steps))
    assert features["n_tool_calls"] == 4 and features["n_repeat_calls"] == 1


def test_grounding_compares_whole_typed_values_and_unique_denominator():
    raw = row(final="PR #301, 301번, v2.1.0, 9시 05분", steps=[tool('{"number":301,"version":"2.1.0","at":"09:05"}')])
    assert P.extract_features(raw)["grounded_ratio"] == 1
    raw["steps"] = [tool('{"number":1301,"version":"v2.1.00","at":"19:05"}')]
    assert P.extract_features(raw)["grounded_ratio"] == 0
    assert P.value_tokens("2026-11-18 09:05 / 8ec09ab / v2.1.0") == {("time", "09:05"), ("version", "2.1.0")}


def test_any_truncated_result_makes_ratio_missing_even_when_value_is_present():
    raw = row(steps=[tool(), tool(result='{"body":"cut', result_chars=900)])
    assert math.isnan(P.extract_features(raw)["grounded_ratio"])
    # 길이가 정확히600자인 완전 응답은 잘림으로 단정하지 않는다.
    assert not P.truncated(tool(" " * 600))
    assert math.isnan(P.extract_features(row(final="조회했습니다."))["grounded_ratio"])
    assert P.extract_features(row(steps=[]))["grounded_ratio"] == 0


def test_text_flags_distinguish_absence_from_unassigned_attribute():
    assert P.extract_features(row(final="담당자가 없는 이슈 번호는 301입니다."))["says_none"] == 0
    assert P.extract_features(row(final="해당 이슈가 없습니다."))["says_none"] == 1
    assert P.extract_features(row(final="저장소를 알려 주실 수 있나요?"))["asks_back"] == 1


def test_and_exclusion_and_fixed_template_split():
    rows = [
        row(pid="a", tpl="T1", correct=True),
        row(pid="b", tpl="T2", correct=False),
        row(pid="c", tpl="T3", correct=True),
        row(pid="d", tpl="T7", correct=False),
        row(pid="e", cand="A_own", scope_a=False, correct=False),
        row(pid="f", cand="B", scope_a=False),
        row(pid="g", cand="A_own", scope_a=True),
    ]
    train, final, kept, excluded = P.build_tables(rows)
    assert len(kept) == 6 and [r["pid"] for r in excluded] == ["e"]
    assert set(train.template_id) == {"T1", "T2"} and set(final.template_id) == {"T3", "T7"}
    assert train.loc[train.task_id == "b", "is_wrong"].item() == 1
    assert set(train.columns) == {*P.C.META, P.C.LABEL, *P.C.FEATURES}


@pytest.mark.parametrize(
    "change",
    [
        {"correct": "false"},
        {"in_tokens": True},
        {"out_tokens": -1},
        {"steps": [{"type": "unknown"}]},
        {"steps": [tool(result_chars=0)]},
        {"steps": [tool(args={"bad": float("nan")})]},
    ],
)
def test_invalid_records_fail_instead_of_silent_dropping(change):
    with pytest.raises(ValueError):
        P.validate_row(row(**change), 1)


def test_source_duplicate_and_blank_lines_are_rejected(tmp_path):
    path = tmp_path / P.SOURCE_NAME
    text = json.dumps(row())
    path.write_text(text + "\n" + text + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="중복 run_id"):
        P.read_source(path)
    path.write_text(text + "\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="빈 줄"):
        P.read_source(path)
    path.write_text('{"correct":true,"correct":false}', encoding="utf-8")
    with pytest.raises(ValueError, match="중복 JSON 키"):
        P.read_source(path)


def test_preprocess_refuses_existing_results_without_touching_them(tmp_path):
    source = tmp_path / P.SOURCE_NAME
    source.write_text("do not read", encoding="utf-8")
    output = tmp_path / "data"
    output.mkdir()
    existing = output / "train.csv"
    existing.write_text("keep", encoding="utf-8")
    before = existing.read_bytes()
    with pytest.raises(FileExistsError):
        P.preprocess(source, output, tmp_path / "summary.json")
    assert existing.read_bytes() == before and not (output / "final.csv").exists()


def test_wrong_source_file_cannot_accidentally_use_pilot(tmp_path):
    with pytest.raises(ValueError, match="main"):
        P.preprocess(tmp_path / "trace_pilot.jsonl", tmp_path / "data", tmp_path / "summary.json")
