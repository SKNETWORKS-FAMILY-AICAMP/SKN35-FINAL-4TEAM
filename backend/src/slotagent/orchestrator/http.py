"""오케스트레이터 Backend 의 실제 HTTP 연결부 (설계 6절). 기존 API 를 부르기만 하고 DB 를 직접 쓰지 않습니다.

지금 실제로 잇는 것: plan-proposal·run·status. 나머지는 미정·미구현이라 not_ready 로 멈춥니다 (임의 값으로 넘기지 않음).
"""

from __future__ import annotations

import httpx

from slotagent.orchestrator.graph import BackendError


class HttpBackend:
    def __init__(self, client: httpx.Client):
        self.client = client  # base_url 이 정해진 클라이언트 (시험은 FastAPI TestClient)

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = self.client.request(method, path, json=body)
        except httpx.HTTPError as e:  # 연결 끊김·시간 초과 → 그래프가 blocked 로 받도록
            raise BackendError("unavailable", type(e).__name__) from None
        try:
            data = r.json()
        except ValueError:
            raise BackendError("bad_response", r.status_code) from None
        if r.status_code >= 400:
            code = data.get("code") if isinstance(data, dict) else None
            raise BackendError(code if isinstance(code, str) else f"http_{r.status_code}", data)
        if not isinstance(data, dict):
            raise BackendError("bad_response", r.status_code)
        return data

    def plan_proposal(self, req: dict) -> dict:
        return self._call("POST", "/api/experiments/plan-proposal", req)

    def run(self, experiment_id: int) -> dict:
        return self._call("POST", f"/api/experiments/{experiment_id}/run")

    def status(self, experiment_id: int) -> dict:
        return self._call("GET", f"/api/experiments/{experiment_id}/status")

    def list_candidates(self, slot_id: int) -> list[dict]:
        raise BackendError("not_ready", "후보 목록 API 없음 (설계 7절 3)")

    def create_experiment(self, req: dict, create_key: str) -> int:
        # POST /api/experiments 는 있지만 중복 방지 키가 없어 재시작 때 실험이 둘 생길 수 있음 → 계약 전에는 쓰지 않음
        raise BackendError("not_ready", "실험 초안 저장 중복 방지 키 계약 전 (설계 7절 1)")

    def final_result(self, experiment_id: int) -> dict | None:
        raise BackendError("not_ready", "final_analysis_id 분리 전 (설계 8절 5단계)")
