"""운영 계산형의 독립 정답·분모·시간 경계·구간 합집합·분위수 검증."""

import copy
import importlib.util
from pathlib import Path

import pytest

from slotagent.packs.groups import load_group, read_group

PACK = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
spec = importlib.util.spec_from_file_location("metric_eval", PACK / "reference/evaluators/metrics.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def task(code, index=1):
    pack = load_group(PACK, "metrics")
    return next(t for t in pack["tasks"] if t["code"] == f"{code}-{index:03d}")


def calculate(code, index=1):
    selected = task(code, index)
    return module.calculate(code, selected["slot_values"],
                            module.load_case(f"metrics-{index}")[module.SOURCES[code]])


def test_eighteen_tasks_twenty_four_goldens_and_fake_runs(tmp_path):
    pack, snapshots, golden = read_group(PACK, "metrics")
    assert len(pack["templates"]) == 6 and len(pack["tasks"]) == 18 and len(golden) == 24
    assert len(snapshots) == 1
    report = module.run(tmp_path)
    assert report["runs"] == 108 and report["all_matched"]
    by_code = {t["code"]: t for t in pack["tasks"]}
    for entry, trace in golden:
        assert module.grade(by_code[entry["task_code"]], trace) == entry["expected"]


@pytest.mark.parametrize("index", [1, 2, 3])
def test_count_dedup_interval_and_p90_independent_answers(index):
    assert calculate("ERROR_COUNTS_BEFORE_AFTER", index) == {
        "before_count": index+1, "after_count": index+2, "delta_count": 1}
    assert calculate("ERROR_EVENTS_DEDUPLICATED", index) == {"unique_count": 2*index+2, "duplicate_count": 1}
    assert calculate("INCIDENT_INTERVAL_UNION", index) == {"downtime_sec": [2700, 600, 0][index-1]}
    assert calculate("LATENCY_P90_NEAREST_RANK", index) == {
        "p90_ms": [90, 30, 7][index-1], "valid_count": [10, 5, 1][index-1]}


def test_weighted_rate_zero_denominator_and_sample_threshold():
    assert calculate("ERROR_RATE_TRAFFIC_NORMALIZED", 1) == {
        "before_rate_bp": 500, "after_rate_bp": 400, "delta_bp": -100}
    assert calculate("ERROR_RATE_TRAFFIC_NORMALIZED", 2) == {
        "before_rate_bp": 250, "after_rate_bp": 800, "delta_bp": 550}
    assert calculate("ERROR_RATE_TRAFFIC_NORMALIZED", 3) == {
        "before_rate_bp": "UNDEFINED", "after_rate_bp": 1000, "delta_bp": "UNDEFINED"}
    for index, status, before, after, missing in [
        (1, "eligible", 100, 200, []),
        (2, "insufficient_sample", 200, 100, ["after"]),
        (3, "insufficient_sample", 0, 100, ["before"]),
    ]:
        assert calculate("METRIC_MINIMUM_SAMPLE", index) == {
            "status": status, "before_n": before, "after_n": after, "missing_windows": missing}


def test_unrounded_rate_difference_and_empty_latency():
    selected = task("ERROR_RATE_TRAFFIC_NORMALIZED")
    rows = [{"service": "payment", "at": "2026-11-24T11:45:00+09:00", "requests": 6, "errors": 1},
            {"service": "payment", "at": "2026-11-24T12:15:00+09:00", "requests": 3, "errors": 1}]
    assert module.calculate(selected["template"], selected["slot_values"], rows) == {
        "before_rate_bp": 1667, "after_rate_bp": 3333, "delta_bp": 1667}
    selected = task("LATENCY_P90_NEAREST_RANK")
    assert module.calculate(selected["template"], selected["slot_values"], []) == {"p90_ms": "UNDEFINED", "valid_count": 0}


def test_input_order_and_timezone_equivalence():
    for code in module.SOURCES:
        selected = task(code)
        rows = module.load_case("metrics-1")[module.SOURCES[code]]
        assert module.calculate(code, selected["slot_values"], list(reversed(rows))) == calculate(code)
    selected = task("ERROR_COUNTS_BEFORE_AFTER")
    rows = module.load_case("metrics-1")["errors"]
    before = module.calculate(selected["template"], selected["slot_values"], rows)
    changed = copy.deepcopy(rows)
    for row in changed:
        if row["at"] == "2026-11-24T12:00:00+09:00":
            row["at"] = "2026-11-24T03:00:00Z"
    assert module.calculate(selected["template"], selected["slot_values"], changed) == before


@pytest.mark.parametrize("change", ["reply", "service", "missing", "invalid_json"])
def test_untrusted_evidence_is_rejected(change):
    selected = task("ERROR_RATE_TRAFFIC_NORMALIZED")
    trace = module.simulate(selected, "success")
    if change == "reply":
        trace["spans"][0]["tool_result"] = "[]"
    elif change == "service":
        trace["spans"][0]["tool_args"]["service"] = "other"
    elif change == "missing":
        trace["spans"] = []
    else:
        trace["final_answer"] = "invalid"
    assert not module.grade(selected, trace)["success"]


def test_invalid_counters_and_reverse_interval():
    selected = task("ERROR_RATE_TRAFFIC_NORMALIZED")
    rows = [{"service": "payment", "at": "2026-11-24T11:45:00+09:00", "requests": 1, "errors": 2}]
    with pytest.raises(ValueError, match="counters"):
        module.calculate(selected["template"], selected["slot_values"], rows)
    selected = task("INCIDENT_INTERVAL_UNION")
    rows = [{"service": "payment", "start": "2026-11-24T12:00:00+09:00", "end": "2026-11-24T11:00:00+09:00"}]
    with pytest.raises(ValueError, match="precedes"):
        module.calculate(selected["template"], selected["slot_values"], rows)
