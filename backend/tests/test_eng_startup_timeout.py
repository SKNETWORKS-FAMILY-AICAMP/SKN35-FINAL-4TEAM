"""① 준비 제한과 도구 호출 제한을 독립적으로 검증합니다."""

import subprocess
import sys
import time

import pytest
from test_eng_stdio import ARGS, assert_closed, session
from test_eng_stdio import definitions as definitions
from test_eng_stdio import test_call_failure_is_saved as failure_case
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.engine.loop import ToolEnvironmentError


def test_startup_and_call_limits_separate(definitions):
    # 준비에 0.2초가 필요해도 호출 제한 0.05초로 시작을 실패시키지 않습니다.
    with session(
        definitions, "call_timeout", startup_timeout_sec=5, timeout_sec=0.05, server_options={"eng_start_delay": 0.2}
    ) as client:
        before = time.monotonic()
        with pytest.raises(ToolEnvironmentError):
            client("list_issues", ARGS, 5)
        assert time.monotonic() - before < 4
    assert_closed(client)


@pytest.fixture(scope="module")
def cpu_load(tmp_path_factory):
    root = tmp_path_factory.mktemp("eng_cpu")
    code = """import sys,time
from pathlib import Path
p=Path(sys.argv[1]); n=0; end=time.monotonic()+180
while time.monotonic()<end:
    for _ in range(100000): n=(n*1664525+1013904223)&0xffffffff
    p.write_text(str(n))
"""
    paths = [root / str(i) for i in range(2)]
    processes = [
        subprocess.Popen([sys.executable, "-c", code, str(p)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for p in paths
    ]
    try:
        deadline = time.monotonic() + 10
        while not all(p.exists() for p in paths):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        yield processes
        assert all(p.poll() is None for p in processes)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


@pytest.mark.parametrize("iteration", range(20))
def test_call_failure_under_cpu_load(experiment, engine_db, definitions, cpu_load, iteration):
    assert all(p.poll() is None for p in cpu_load)
    failure_case(experiment, engine_db, definitions, "call_timeout", "env_mcp_server_down")
