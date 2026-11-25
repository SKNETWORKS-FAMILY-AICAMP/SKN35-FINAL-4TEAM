"""Review exports must not leak registered verdicts or become authority metadata."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prepare_pack_review", ROOT / "scripts/prepare_pack_review.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def test_inventory_covers_every_observed_tool_without_granting_authority():
    result = review.inventory()
    tools = result["tools"]
    assert len(tools) == 30
    assert len({tool["name"] for tool in tools}) == len(tools)
    assert sum(tool["definition"] is not None for tool in tools) == 5
    assert all(tool["candidate_authority_source"] is False for tool in tools)
    assert all(tool["capabilities"] == [] for tool in tools if tool["definition"] is None)
    assert next(tool for tool in tools if tool["name"] == "request_user_confirmation")["access"] is None


def test_reviewer_export_excludes_answer_keys_and_annotations_are_blank():
    public, private = review.review_material()
    assert len(public["cases"]) == len(private["cases"]) == 28
    assert {case["case_id"] for case in public["cases"]} == {case["case_id"] for case in private["cases"]}
    for case in public["cases"]:
        assert set(case) == {"case_id", "prompt", "trace", "annotation"}
        assert all(value is None for value in case["annotation"].values())
        assert all(not key.startswith("golden.") and key not in {"fixture", "expected"}
                   for span in case["trace"]["spans"] for key in span["attributes"])
    assert {case["kind"] for case in private["cases"]} == {"success", "alt_success", "near_miss", "forbidden"}
    assert review.review_material() == (public, private)


def test_full_review_preserves_source_and_covers_all_registered_goldens():
    before = (review.PACK / "pack.json").read_bytes()
    public, private = review.review_material(all_templates=True)
    assert len(public["cases"]) == len(private["cases"]) == 188
    assert len({case["template"] for case in private["cases"]}) == 47
    assert (review.PACK / "pack.json").read_bytes() == before


def test_pilot_covers_seven_groups_and_does_not_claim_product_readiness():
    pilot = review.pilot_selection()
    items = pilot["templates"]
    assert len(items) == len({item["template"] for item in items}) == 15
    assert len({item["group"] for item in items}) == 7
    assert all(item["task_codes"] and item["required_capabilities"] and item["snapshot_paths"] for item in items)
    assert all(item["product_ready"] is False for item in items)
    public, private = review.review_material()
    assert {case["template"] for case in private["cases"]} <= {item["template"] for item in items}
    assert len(public["cases"]) == 28
