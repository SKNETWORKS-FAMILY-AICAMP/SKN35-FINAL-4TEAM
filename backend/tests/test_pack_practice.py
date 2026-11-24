"""P-03 명세의 데이터 변경 탐지와 실행 가능 여부를 분리한다."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PACK_DIR = Path(__file__).resolve().parents[2] / "packs/it_ops/v0.1"
sys.path.insert(0, str(PACK_DIR / "reference"))
spec = importlib.util.spec_from_file_location("practice_spec", PACK_DIR / "reference/verify_practice.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_spec_and_not_launchable():
    result = module.verify_practice()
    assert result["snapshots"] == 3
    assert result["tools"] == 5
    assert result["templates_covered_by_capability"] == 15
    assert result["launchable"]
    assert not result["actual_mcp_verified"]
    assert module.verify_practice(require_launchable=True)["launchable"]


@pytest.mark.parametrize("change", ["data", "mount", "capability"])
def test_spec_drift_rejected(tmp_path, change):
    shutil.copytree(PACK_DIR / "data", tmp_path / "data")
    shutil.copytree(PACK_DIR / "practice", tmp_path / "practice")
    shutil.copyfile(PACK_DIR / "pack.json", tmp_path / "pack.json")
    path = tmp_path / "practice/servers.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if change == "data":
        data_path = tmp_path / "data/deployments.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["deployments"][0]["version"] = "wrong"
        data_path.write_text(json.dumps(data), encoding="utf-8")
    elif change == "mount":
        manifest["snapshots"][0]["path"] = "pack.json"
    else:
        for tool in manifest["services"][0]["tools"]:
            tool["capabilities"] = []
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        module.verify_practice(tmp_path)
