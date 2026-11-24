"""① 강제 종료 재점검용 자식. 실제 모델·외부 네트워크는 사용하지 않습니다."""

import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Thread

import psycopg
from test_eng_docker import config
from test_eng_worker import dependencies

from slotagent.common import contracts, queue
from slotagent.engine import eng_docker, eng_stdio
from slotagent.workers.eng_main import run_once

uri, image, scope, cli, target, marker = sys.argv[1:]
clients, connections, marked = [], [], []


def gate(name):
    if name != target or marked:
        return
    marked.append(name)
    Path(marker).write_text(
        json.dumps(
            {
                "backend": connections[0].info.backend_pid,
                "client": clients[0].process.pid if clients and clients[0].process else None,
            }
        ),
        encoding="utf-8",
    )
    while True:
        time.sleep(1)


def connect():
    conn = psycopg.connect(uri, autocommit=True)
    connections.append(conn)
    return conn


original_lease = queue.lease


def lease(*args, **kwargs):
    job = original_lease(*args, **kwargs)
    gate("leased")
    return job


queue.lease = lease

original_start = eng_stdio.StdioTools.start


def start(self):
    clients.append(self)
    return original_start(self)


eng_stdio.StdioTools.start = start

original_rpc = eng_stdio.StdioTools._rpc


def rpc(self, method, *args, **kwargs):
    wanted = "container_start" if method == "initialize" else "tool" if method == "tools/call" else None
    if wanted == target:
        self.request_sent.clear()

        def sent():
            if self.request_sent.wait(15):
                gate(wanted)

        Thread(target=sent, daemon=True).start()
    return original_rpc(self, method, *args, **kwargs)


eng_stdio.StdioTools._rpc = rpc

deps = dependencies()
original_chat = deps.model.chat


def chat(**kwargs):
    reply = original_chat(**kwargs)
    gate("model_pre_cost")
    return reply


deps.model.chat = chat
deps.on_model_span = lambda span: gate("model_post_cost")

original_validate = contracts.validate


def validate(name, value, *args, **kwargs):
    if name == "trace" and "trial_id" in value:
        gate("final_before")
    return original_validate(name, value, *args, **kwargs)


contracts.validate = validate

original_finish = queue.finish


def finish(*args, **kwargs):
    gate("final_after")
    return original_finish(*args, **kwargs)


queue.finish = finish

original_remove = eng_docker.DockerControl.remove


def remove(*args, **kwargs):
    result = original_remove(*args, **kwargs)
    gate("cleanup")
    return result


eng_docker.DockerControl.remove = remove

mode = "init_timeout" if target == "container_start" else "call_timeout" if target == "tool" else "ok"
setting = config({"image": image, "scope": scope, "cli": cli, "volume": "unused"}, mode, timeout_sec=30)
# 이 점검은 읽기 전용 서버만 사용하며 불필요한 volume을 만들지 않습니다.
server = next(iter(setting.servers.values()))
setting = eng_docker.DockerStdioConfig({"github": replace(server, mounts=(), environment=dict(server.environment))}, scope=scope, docker=cli, timeout_sec=30)
run_once(connect, "kill-audit", deps=deps, stdio=setting, heartbeat_sec=0.1)
