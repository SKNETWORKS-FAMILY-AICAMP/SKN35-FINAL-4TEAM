// ① 실제 API 호출. 주소는 next.config 의 /api 프록시가 FastAPI(기본 127.0.0.1:8000)로 넘깁니다.
import type {
  CreateExperimentRequest, CreateExperimentResponse, PlanProposalRequest, PlanProposalResponse,
  RegisterAgentRequest, RegisterAgentResponse, RegisterCandidateRequest, RunResponse, StatusResponse,
} from "@/types/contracts";

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(path, body === undefined ? { method } : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.message ?? `요청 실패 (${res.status})`);
  return data as T;
}

const base = (id: number) => `/api/experiments/${id}`;
export const runExperiment = (id: number) => call<RunResponse>(`${base(id)}/run`, "POST");
export const getStatus = (id: number) => call<StatusResponse>(`${base(id)}/status`);
export const stopExperiment = (id: number) => call<StatusResponse>(`${base(id)}/stop`, "POST");

export const registerAgent = (req: RegisterAgentRequest) => call<RegisterAgentResponse>("/api/agents", "POST", req);
// 계약에 응답 모양이 없어 백엔드가 저장한 ID 만 돌려줍니다.
export const registerCandidate = (slotId: number, req: RegisterCandidateRequest) =>
  call<{ candidate_id: number }>(`/api/slots/${slotId}/candidates`, "POST", req);
export const proposePlan = (req: PlanProposalRequest) => call<PlanProposalResponse>("/api/experiments/plan-proposal", "POST", req);
export const createExperiment = (req: CreateExperimentRequest) => call<CreateExperimentResponse>("/api/experiments", "POST", req);
