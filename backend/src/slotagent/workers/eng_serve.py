"""① 배포용 반복 워커. run_once·grade_once 를 계속 부르고, 할 일이 없으면 쉬고, 멈춤 신호에 끝냅니다.

실행 (backend 에서, DATABASE_URL·모델 API 키는 환경 변수):
  $env:PYTHONPATH = "src"; uv run python -m slotagent.workers.eng_serve --stdio servers.json [--worker-id w1] [--drain]

servers.json — 운영자가 신뢰한 MCP 서버 설정 (후보·모델에서 추정하지 않음):
  {"kind": "local", "servers": {"github": ["python", "-u", "server.py"]}, "timeout_sec": 20}
  {"kind": "docker", "scope": "demo", "servers": {"github": {"image": "...@sha256:...",
     "arguments": [], "mounts": [{"source": "D:/data", "target": "/data"}]}}}

채점은 ② 판정 함수가 있어야 해서 serve(classify=...) 로만 켭니다. CLI 는 풀이만 돌립니다.
작업 하나가 실패해도 run_once 가 이미 작업을 돌려준 뒤라, 기록만 하고 다음 작업으로 갑니다.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
from functools import partial
from pathlib import Path
from threading import Event

from slotagent.common import db
from slotagent.common.llm import ProviderModel
from slotagent.engine.eng_docker import DockerServer, DockerStdioConfig, ReadOnlyMount
from slotagent.engine.eng_stdio import LocalStdioConfig
from slotagent.engine.loop import Dependencies
from slotagent.workers.eng_main import grade_once, run_once

log = logging.getLogger(__name__)


def load_stdio(path: str | Path):
    """servers.json → LocalStdioConfig 또는 DockerStdioConfig. 값 검사는 각 클래스가 합니다."""
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("servers"), dict):
        raise ValueError("servers 칸이 있는 JSON 객체가 필요합니다.")
    timeouts = {k: spec[k] for k in ("timeout_sec", "startup_timeout_sec") if k in spec}
    if spec.get("kind") == "local":
        return LocalStdioConfig(spec["servers"], **timeouts)
    if spec.get("kind") == "docker":
        servers = {
            name: DockerServer(**{**s, "mounts": tuple(ReadOnlyMount(**m) for m in s.get("mounts", ()))})
            for name, s in spec["servers"].items()
        }
        return DockerStdioConfig(servers, scope=spec.get("scope"), **timeouts)
    raise ValueError("kind 는 local 또는 docker 여야 합니다.")


def _no_fixed_tool(name, args, timeout_sec):
    # 읽기 도구는 stdio 로만 연결합니다. 여기로 오면 설정이 빠진 것입니다.
    raise RuntimeError(f"stdio 설정에 없는 도구입니다: {name}")


def _step(label, fn) -> bool | None:
    """True = 처리함, False = 할 일 없음, None = 실패 (작업은 run_once·grade_once 가 이미 돌려줌)."""
    try:
        return fn()
    except Exception as exc:  # 원문에는 값이 섞일 수 있어 종류만 남깁니다.
        log.error("%s 작업 실패: %s", label, type(exc).__name__)
        return None


def serve(connect, worker_id, *, deps, stdio, classify=None, idle_sec=2.0, stop: Event | None = None, drain=False):
    """stop 이 켜질 때까지 반복합니다. drain 이면 할 일이 없어지는 순간 끝냅니다. 처리한 작업 수를 돌려줍니다."""
    stop = stop or Event()
    done = 0
    while not stop.is_set():
        steps = [_step("풀이", lambda: run_once(connect, worker_id, deps=deps, stdio=stdio))]
        if classify is not None and not stop.is_set():
            steps.append(_step("채점", lambda: grade_once(connect, f"{worker_id}-grade", classify=classify)))
        done += steps.count(True)
        if True in steps:
            continue
        if drain and None not in steps:
            break
        stop.wait(idle_sec)  # 할 일이 없거나 실패(DB 끊김 등)면 쉬었다가 다시 봅니다.
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="slotagent.workers.eng_serve")
    parser.add_argument("--stdio", required=True, help="MCP 서버 설정 JSON 경로")
    parser.add_argument("--worker-id", default=socket.gethostname())
    parser.add_argument("--idle-sec", type=float, default=2.0)
    parser.add_argument("--drain", action="store_true", help="할 일이 없으면 끝냄")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # 진행 중 풀이는 끝까지 돌고 다음 작업부터 멈춥니다.
    done = serve(
        partial(db.connect, autocommit=True),
        args.worker_id,
        deps=Dependencies(ProviderModel(), _no_fixed_tool),
        stdio=load_stdio(args.stdio),
        idle_sec=args.idle_sec,
        stop=stop,
        drain=args.drain,
    )
    log.info("워커 종료: 작업 %d건", done)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
