"""단일 평가팩 안의 업무 그룹 뷰. 그룹은 pack_code나 독립 DB 버전이 아니다."""

import copy
import json
from pathlib import Path


def load_groups(pack_dir):
    root = Path(pack_dir)
    pack = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    groups = json.loads((root / "groups.json").read_text(encoding="utf-8"))["groups"]
    codes = [code for group in groups.values() for code in group["template_codes"]]
    if len(codes) != len(set(codes)) or set(codes) != {t["code"] for t in pack["templates"]}:
        raise ValueError("Every template must belong to exactly one group")
    snapshots = {s["location"] for s in pack["data_snapshots"]}
    if any(not set(group["snapshot_paths"]) <= snapshots for group in groups.values()):
        raise ValueError("Group references an unknown snapshot")
    return groups


def filter_group(pack, groups, group):
    selected = groups[group]
    codes = set(selected["template_codes"])
    result = copy.deepcopy(pack)
    result["templates"] = [t for t in result["templates"] if t["code"] in codes]
    result["tasks"] = [t for t in result["tasks"] if t["template"] in codes]
    result["golden"] = [g for g in result["golden"] if g["template"] in codes]
    result["data_snapshots"] = [s for s in result["data_snapshots"] if s["location"] in selected["snapshot_paths"]]
    return result


def load_group(pack_dir, group):
    root = Path(pack_dir)
    pack = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    return filter_group(pack, load_groups(root), group)


def read_group(pack_dir, group):
    """통합 팩 전체를 검증하고 테스트/임시 어댑터에 그룹 뷰만 제공한다."""
    from slotagent.packs.loader import read_pack

    pack, snapshots, golden = read_pack(pack_dir)
    groups = load_groups(pack_dir)
    selected = filter_group(pack, groups, group)
    codes = set(groups[group]["template_codes"])
    paths = set(groups[group]["snapshot_paths"])
    return (selected, [(s, h) for s, h in snapshots if s["location"] in paths],
            [(g, trace) for g, trace in golden if g["template"] in codes])
