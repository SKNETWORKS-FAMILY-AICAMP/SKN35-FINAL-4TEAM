"""오케스트레이터 시험용 가짜 연결부 (설계 6절). 실제 저장 API 의 중복 방지를 검증하지 않습니다 — 그래프가 키를 같게 보내는지만."""

from __future__ import annotations

import os

import psycopg

from slotagent.orchestrator.graph import BackendError

CANDIDATES = [
    {"candidate_id": 1, "is_baseline": True, "component_kind": "tool_bundle", "name": "지금 구성"},
    {"candidate_id": 2, "is_baseline": False, "component_kind": "tool_search", "name": "도구 검색"},
    {"candidate_id": 3, "is_baseline": False, "component_kind": "custom_tool", "name": "작은 묶음"},
    {"candidate_id": 4, "is_baseline": False, "component_kind": "prompt", "name": "1단계 밖"},
]
FINAL = {"analysis_id": 7, "report_ids": [70, 71], "verdict": "noninferior"}


class FakeBrain:
    def goal(self, text):
        return {"focus": ["cost", "accuracy"], "text": text}

    def pick(self, goal, candidates):
        return {"candidate_ids": [99] + [c["candidate_id"] for c in candidates], "reason": "비용이 낮은 순"}

    def explain(self, goal, result):
        return "기준 후보보다 나쁘지 않습니다"


class MemBackend:
    def __init__(self, candidates=CANDIDATES):
        self.candidates = list(candidates)
        self.not_ready = False
        self.exps: dict[int, dict] = {}
        self.keys: dict[str, int] = {}
        self.create_calls: list[str] = []

    def list_candidates(self, slot_id):
        return self.candidates

    def plan_proposal(self, req):
        if self.not_ready:
            raise BackendError("not_ready", "sample_size")
        reps = req.get("reps", 3)
        return {"prereg": {"schema_version": 1, "test": "ni_then_sup"}, "plan": {"schema_version": 1, "tasks": [1, 2]},
                "as_of": "2026-11-27T00:00:00+00:00", "reps": reps, "n_templates": 1, "n_tasks": 2,
                "trials": 2 * reps * len(req["candidate_ids"])}

    # 실험 기록 (MemBackend 는 메모리, DbBackend 는 임시 DB)
    def _get(self, eid):
        return self.exps[eid]

    def _set_status(self, eid, status, started=False):
        self.exps[eid]["status"] = status
        self.exps[eid]["starts"] += started

    def create_experiment(self, req, key):
        self.create_calls.append(key)
        if key not in self.keys:
            eid = len(self.exps) + 1
            self.exps[eid] = {"status": "draft", "starts": 0, "req": req}
            self.keys[key] = eid
        return self.keys[key]

    def run(self, eid):
        st = self._get(eid)["status"]
        if st == "draft":
            self._set_status(eid, "running", started=True)
        elif st not in ("locked", "running"):
            raise BackendError("experiment_locked")
        return {"experiment_id": eid, "status": "running"}

    def status(self, eid):
        return {"experiment_id": eid, "status": self._get(eid)["status"], "trials_total": 12, "budget_krw": None}

    def final_result(self, eid):
        return FINAL if self._get(eid)["status"] == "done" else None


class DbBackend(MemBackend):
    """가짜 상태를 임시 DB 표(orch_fake.experiments)에 둠 — 프로세스가 죽어도 남음. ORCH_CRASH=create|run 이면 쓴 직후 종료."""

    def __init__(self, url):
        super().__init__()
        self.url = url
        with psycopg.connect(url, autocommit=True) as c:
            c.execute("CREATE SCHEMA IF NOT EXISTS orch_fake")
            c.execute("""CREATE TABLE IF NOT EXISTS orch_fake.experiments (
                           experiment_id serial PRIMARY KEY, create_key text UNIQUE NOT NULL,
                           status text NOT NULL DEFAULT 'draft', starts int NOT NULL DEFAULT 0)""")

    def _crash(self, where):
        if os.environ.get("ORCH_CRASH") == where:
            os._exit(3)  # 쓰기는 끝났고 응답·체크포인트 전

    def _get(self, eid):
        with psycopg.connect(self.url) as c:
            st, starts = c.execute("SELECT status, starts FROM orch_fake.experiments WHERE experiment_id=%s",
                                   (eid,)).fetchone()
        return {"status": st, "starts": starts}

    def _set_status(self, eid, status, started=False):
        with psycopg.connect(self.url, autocommit=True) as c:
            c.execute("UPDATE orch_fake.experiments SET status=%s, starts=starts+%s WHERE experiment_id=%s",
                      (status, int(started), eid))

    def create_experiment(self, req, key):
        with psycopg.connect(self.url, autocommit=True) as c:
            c.execute("INSERT INTO orch_fake.experiments(create_key) VALUES (%s) ON CONFLICT DO NOTHING", (key,))
            eid = c.execute("SELECT experiment_id FROM orch_fake.experiments WHERE create_key=%s", (key,)).fetchone()[0]
        self._crash("create")
        return eid

    def run(self, eid):
        out = super().run(eid)
        self._crash("run")
        return out
