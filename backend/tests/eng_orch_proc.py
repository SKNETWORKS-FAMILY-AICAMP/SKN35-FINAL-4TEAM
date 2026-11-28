"""프로세스 종료 시험용 하위 프로세스. 한 번 진행하고 지금 대기 값·상태를 JSON 으로 찍고 끝납니다.

uv run python tests/eng_orch_proc.py <DATABASE_URL> <thread_id> start|resume|continue [resume JSON]
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from eng_orch_fakes import DbBackend, FakeBrain  # noqa: E402

from slotagent.orchestrator import graph, runtime  # noqa: E402

START = {"user_id": 1, "text": "비용을 줄이고 싶어. 정확도 차이 비교", "agent_version_id": 1, "slot_id": 1,
         "pack_version_id": 1}

url, tid, cmd = sys.argv[1:4]
with runtime.checkpointer(url) as saver:
    g = graph.build(DbBackend(url), FakeBrain()).compile(checkpointer=saver)
    if cmd == "resume":
        runtime.resume(g, tid, json.loads(sys.argv[4]))
    else:
        runtime.step(g, START if cmd == "start" else None, tid)
    state = g.get_state(runtime.config(tid))
    print(json.dumps({"waiting": runtime.waiting(g, tid), "values": state.values}, ensure_ascii=False, default=str))
