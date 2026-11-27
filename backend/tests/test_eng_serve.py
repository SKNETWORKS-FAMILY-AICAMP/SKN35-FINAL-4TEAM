"""① 반복 워커 eng_serve: 반복·쉬기·실패 뒤 계속·멈춤, servers.json 읽기."""

import json
from threading import Event

import pytest

from slotagent.engine.eng_docker import DockerStdioConfig
from slotagent.engine.eng_stdio import LocalStdioConfig
from slotagent.workers import eng_serve


def scripted(monkeypatch, runs, grades=()):
    """run_once·grade_once 가 차례대로 값을 돌려주거나 예외를 냄. 다 쓰면 False."""
    runs, grades = list(runs), list(grades)

    def take(queue):
        value = queue.pop(0) if queue else False
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(eng_serve, "run_once", lambda *a, **k: take(runs))
    monkeypatch.setattr(eng_serve, "grade_once", lambda *a, **k: take(grades))


def test_drain_counts_and_survives_failures(monkeypatch):
    scripted(monkeypatch, [True, RuntimeError("x"), True, False])
    waits = []
    stop = Event()
    stop.wait = lambda sec: waits.append(sec)  # 실제로 쉬지 않음
    assert eng_serve.serve(None, "w", deps=None, stdio=None, idle_sec=0.5, stop=stop, drain=True) == 2
    assert waits == [0.5]  # 실패 뒤 한 번 쉬고, 할 일이 없으면 drain 으로 끝


def test_grading_runs_beside_trials(monkeypatch):
    scripted(monkeypatch, [True], grades=[True, True])
    out = eng_serve.serve(None, "w", deps=None, stdio=None, classify=lambda *_: None, drain=True)
    assert out == 3


def test_stop_ends_idle_loop(monkeypatch):
    stop = Event()
    calls = []

    def run_once(*a, **k):
        calls.append(1)
        if len(calls) == 3:
            stop.set()
        return False

    monkeypatch.setattr(eng_serve, "run_once", run_once)
    assert eng_serve.serve(None, "w", deps=None, stdio=None, idle_sec=0, stop=stop) == 0
    assert len(calls) == 3


def test_load_stdio(tmp_path):
    local = tmp_path / "local.json"
    local.write_text(json.dumps({"kind": "local", "servers": {"github": ["python", "-u", "s.py"]}, "timeout_sec": 20}))
    assert isinstance(eng_serve.load_stdio(local), LocalStdioConfig)
    docker = tmp_path / "docker.json"
    docker.write_text(json.dumps({"kind": "docker", "scope": "demo", "servers": {"github": {
        "image": "practice@sha256:" + "0" * 64, "mounts": [{"source": "/srv/data", "target": "/data"}]}}}))
    config = eng_serve.load_stdio(docker)
    assert isinstance(config, DockerStdioConfig)
    assert config.servers["github"].mounts[0].argument() == "type=bind,source=/srv/data,target=/data,readonly"


@pytest.mark.parametrize("spec", [
    {"servers": {"a": ["x"]}},  # kind 없음
    {"kind": "local"},  # servers 없음
    {"kind": "docker", "scope": "demo", "servers": {"a": {"image": "i", "mounts": [
        {"source": "/var/run/docker.sock", "target": "/data"}]}}},  # 제어 소켓
])
def test_load_stdio_refuses(tmp_path, spec):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(spec))
    with pytest.raises(ValueError):
        eng_serve.load_stdio(path)
