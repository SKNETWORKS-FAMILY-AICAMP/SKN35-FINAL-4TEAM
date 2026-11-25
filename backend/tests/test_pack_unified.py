"""업무 그룹 통합 시 문항 누락·중복·다중 평가팩 회귀를 검사한다."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from slotagent.packs.groups import load_groups
from slotagent.packs.loader import read_pack

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "packs/it_ops/v0.1"


def test_one_pack_contains_all_groups():
    assert list((ROOT / "packs").glob("*/v*/pack.json")) == [PACK / "pack.json"]
    pack, snapshots, golden = read_pack(PACK)
    assert pack["pack_version"]["pack_code"] == "it_ops"
    assert (len(pack["templates"]), len(pack["tasks"]), len(golden), len(snapshots)) == (50, 152, 200, 13)
    groups = load_groups(PACK)
    assert {name: len(g["template_codes"]) for name, g in groups.items()} == {
        "lookup": 8, "writes": 9, "incidents": 9, "reliability": 3,
        "conflicts": 3, "metrics": 6, "workflows": 12}
    assert sum(t.get("confirmation") is not None for t in pack["tasks"]) == 36


@pytest.mark.parametrize("change", ["duplicate", "missing", "snapshot"])
def test_invalid_group_membership_rejected(tmp_path, change):
    shutil.copy(PACK / "pack.json", tmp_path)
    groups = json.loads((PACK / "groups.json").read_text(encoding="utf-8"))
    entries = groups["groups"]
    if change == "duplicate":
        entries["writes"]["template_codes"].append(entries["lookup"]["template_codes"][0])
    elif change == "missing":
        entries["lookup"]["template_codes"].pop()
    else:
        entries["lookup"]["snapshot_paths"].append("data/missing.json")
    (tmp_path / "groups.json").write_text(json.dumps(groups), encoding="utf-8")
    with pytest.raises(ValueError):
        load_groups(tmp_path)


def test_all_groups_run_through_single_entrypoint(tmp_path):
    spec = importlib.util.spec_from_file_location("unified_pack_run", PACK / "reference/run_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run(tmp_path)
    assert report["pack_code"] == "it_ops"
    assert report["runs"] == 882 and report["all_matched"]
    assert len(report["groups"]) == 7
    assert not report["product_grader_verified"]
