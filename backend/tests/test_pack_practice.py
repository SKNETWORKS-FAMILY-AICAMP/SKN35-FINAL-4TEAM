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
server_spec = importlib.util.spec_from_file_location("practice_server_test", PACK_DIR / "practice/server.py")
server = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server)


def test_spec_and_not_launchable():
    result = module.verify_practice()
    assert result["snapshots"] == 3
    assert result["tools"] == 5
    assert result["templates_covered_by_capability"] == 8
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


@pytest.mark.parametrize("left,right,key", [
    ("list_deployments", "list_operation_runs", "run_id"),
    ("list_issues", "list_operation_issues", "number"),
])
def test_equivalent_tools_return_same_records(left, right, key):
    data = server.PracticeData(PACK_DIR / "practice/servers.json", PACK_DIR / "data")
    for repo in (None, "acme/ops-service", "acme/other-service", "acme/payment-service",
                 "acme/catalog-service", "acme/auth-service", "acme/missing"):
        args = {} if repo is None else {"repo": repo}
        a = [{**{k: v for k, v in r.items() if k != key}, "id": str(r[key])} for r in data.call(left, args)]
        b = data.call(right, args)
        assert sorted(a, key=lambda r: (r["repo"], r["id"])) == sorted(b, key=lambda r: (r["repo"], r["id"]))
        if repo != "acme/missing":
            assert a


def test_missing_source_fields_are_not_fabricated():
    data = server.PracticeData(PACK_DIR / "practice/servers.json", PACK_DIR / "data")
    for name in ("list_deployments", "list_operation_runs"):
        assert all("sha" not in r and "started_at" not in r
                   for r in data.call(name, {"repo": "acme/ops-service"}))
        assert all("sha" in r and "started_at" in r
                   for r in data.call(name, {"repo": "acme/payment-service"}))
    for name in ("list_issues", "list_operation_issues"):
        assert all("updated_at" not in r and "closed_at" not in r
                   for r in data.call(name, {"repo": "acme/ops-service"}))
        assert all("updated_at" in r and "closed_at" in r
                   for r in data.call(name, {"repo": "acme/payment-service"}))


def test_native_records_are_preserved():
    data = server.PracticeData(PACK_DIR / "practice/servers.json", PACK_DIR / "data")
    for name, tool in data.tools.items():
        original = data.data[tool["source_snapshot"]][tool["source_key"]]
        actual = data.call(name, {})
        assert actual[:len(original)] == original


def test_duplicate_record_identity_is_rejected(tmp_path):
    from slotagent.common.hashing import canonical_hash
    shutil.copytree(PACK_DIR / "data", tmp_path / "data")
    manifest = json.loads((PACK_DIR / "practice/servers.json").read_text(encoding="utf-8"))
    path = tmp_path / "data/operations.json"
    operations = json.loads(path.read_text(encoding="utf-8"))
    operations["runs"][0].update(repo="acme/ops-service", id="307")
    path.write_text(json.dumps(operations), encoding="utf-8")
    next(s for s in manifest["snapshots"] if s["id"] == "operations")["content_hash"] = canonical_hash(operations)
    manifest_path = tmp_path / "servers.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Conflicting practice record identity"):
        server.PracticeData(manifest_path, tmp_path / "data")
