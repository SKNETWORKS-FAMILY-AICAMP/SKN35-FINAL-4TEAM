"""① 오케스트레이터 실제 연결 시험 (설계 6절 표 "실제 연결"): run·status 만 실제 HTTP, 실험은 fixture 가 임시 DB 에 만든 draft."""

import httpx
import pytest
from eng_orch_fakes import MemBackend
from test_eng_api import client as client
from test_eng_api import draft as draft
from test_eng_orchestrator import kinds, resume, to_plan
from test_eng_orchestrator import saver as saver
from test_eng_orchestrator import url as url
from test_eng_worker import engine_db as engine_db
from test_eng_worker import experiment as experiment

from slotagent.common import contracts
from slotagent.orchestrator import graph, runtime
from slotagent.orchestrator.http import HttpBackend


def code_of(fn, *args):
    with pytest.raises(graph.BackendError) as e:
        fn(*args)
    return e.value.code


def test_run_and_status_shapes(client, draft):
    _, exp = draft
    b = HttpBackend(client)
    assert contracts.validate("api", b.status(exp), part="status_response")["status"] == "draft"
    first = contracts.validate("api", b.run(exp), part="run_response")
    assert first["status"] == "running" and b.run(exp) == first  # 재요청은 멱등
    assert b.status(exp)["status"] == "running"


def test_errors_become_backend_errors(client, draft):
    _, exp = draft
    b = HttpBackend(client)
    assert code_of(b.status, 2**62) == "not_found"
    b.run(exp)
    client.post(f"/api/experiments/{exp}/stop")
    assert code_of(b.run, exp) == "experiment_locked"  # 끝난 실험 재요청 → 그래프가 status 로 복구하는 그 코드


def test_transport_failure_is_unavailable():
    def boom(request):
        raise httpx.ConnectError("끊김", request=request)

    b = HttpBackend(httpx.Client(base_url="http://x", transport=httpx.MockTransport(boom)))
    assert code_of(b.status, 1) == "unavailable"


def test_not_ready_parts_stop_instead_of_guessing(client):
    b = HttpBackend(client)
    assert {code_of(b.list_candidates, 1), code_of(b.create_experiment, {}, "k"), code_of(b.final_result, 1)} == {"not_ready"}


class Hybrid(MemBackend):
    """후보·제안·저장은 가짜(저장은 fixture draft 번호를 돌려줌), run·status 는 실제 HTTP."""

    def __init__(self, http, exp):
        super().__init__()
        self.http, self.exp = http, exp

    def create_experiment(self, req, key):
        self.create_calls.append(key)
        return self.exp

    def run(self, eid):
        return self.http.run(eid)

    def status(self, eid):
        return self.http.status(eid)


def test_graph_on_real_run_status(client, draft, saver):
    _, exp = draft
    b, tid = Hybrid(HttpBackend(client), exp), "t-http"
    plan = to_plan(b, saver, tid)
    resume(b, saver, tid, {"action": "approve", "by": 1, "hash": plan["hash"]})
    g = graph.build(b, None).compile(checkpointer=saver)
    (run,) = runtime.waiting(g, tid)
    assert run["summary"]["experiment_id"] == exp and run["summary"]["trials_total"] > 0  # 실제 status 값
    g = resume(b, saver, tid, {"action": "approve", "by": 1, "hash": run["hash"]})
    assert kinds(g, tid) == ["wait"] and client.get(f"/api/experiments/{exp}/status").json()["status"] == "running"
    client.post(f"/api/experiments/{exp}/stop")
    runtime.tick(g, saver)
    exp_out = g.get_state(runtime.config(tid)).values["explanation"]
    assert kinds(g, tid) == [] and exp_out["facts"]["status"] == "stopped" and exp_out["facts"]["experiment_id"] == exp
