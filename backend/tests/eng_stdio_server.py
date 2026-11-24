"""① 외부 접근 없는 stdio 검증 서버. 제품 평가팩 서버가 아닙니다."""

import errno
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

config = json.loads(sys.argv[1])
if config.pop("grandchild", False):
    child = subprocess.Popen(
        [sys.executable, "-u", __file__, json.dumps(config)],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if config.get("launcher_exit"):
        sys.exit(0)
    sys.exit(child.wait(timeout=60))
if config.get("pid_file"):
    Path(config["pid_file"]).write_text(str(os.getpid()), encoding="utf-8")
mode = config.get("mode", "ok")
tools = config["tools"]
time.sleep(config.get("eng_start_delay", 0))
initialized = False
calls = 0
for _ in range(100):
    line = sys.stdin.readline()
    if not line:
        break
    request = json.loads(line)
    method = request["method"]
    if method == "notifications/initialized":
        initialized = True
        continue
    if method == "initialize":
        if mode == "init_timeout":
            time.sleep(30)
        result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "eng-test", "version": "1"},
        }
    elif method == "tools/list":
        assert initialized
        result = {"tools": tools}
    else:
        assert method == "tools/call" and initialized
        calls += 1
        if mode == "call_timeout":
            time.sleep(30)
        if mode == "exit":
            os._exit(12)
        if mode == "bad_json":
            print("invalid-json", flush=True)
            continue
        if mode == "empty":
            print("", flush=True)
            continue
        if mode == "stderr":
            sys.stderr.write("x" * 100000)
            sys.stderr.flush()
        result = {"content": [{"type": "text", "text": '[{"number":145},{"number":148}]'}]}
        if mode == "isolation_probe":
            network_errno, write_errno = 0, 0
            try:
                with socket.create_connection(("198.51.100.1", 80), timeout=0.2):
                    network_errno = 0
            except OSError as error:
                network_errno = error.errno
            try:
                with Path("/data/check.txt").open("a") as target:
                    target.write("unexpected")
            except OSError as error:
                write_errno = error.errno
            probe = {
                "network_errno": network_errno,
                "network_error": errno.errorcode.get(network_errno),
                "write_errno": write_errno,
                "write_error": errno.errorcode.get(write_errno),
                "data": Path("/data/check.txt").read_text(),
                "has_parent_secrets": any(key in os.environ for key in ("OPENAI_API_KEY", "DATABASE_URL")),
            }
            result = {"content": [{"type": "text", "text": json.dumps(probe)}]}
        if mode == "bad_content":
            result = {"content": []}
        if mode == "tool_error" or (mode == "tool_error_once" and calls == 1):
            result = {"content": [{"type": "text", "text": "failed"}], "isError": True}
    response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
    if method == "tools/call" and mode == "wrong_id":
        response["id"] += 1
    print(json.dumps(response), flush=True)
