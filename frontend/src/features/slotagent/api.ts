// ① 실제 API 호출. 주소는 next.config 의 /api 프록시가 FastAPI(기본 127.0.0.1:8000)로 넘깁니다.
import type { RunResponse, StatusResponse } from "@/types/contracts";

async function call<T>(path: string, method = "GET"): Promise<T> {
  const res = await fetch(path, { method });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(body?.message ?? `요청 실패 (${res.status})`);
  return body as T;
}

const base = (id: number) => `/api/experiments/${id}`;
export const runExperiment = (id: number) => call<RunResponse>(`${base(id)}/run`, "POST");
export const getStatus = (id: number) => call<StatusResponse>(`${base(id)}/status`);
export const stopExperiment = (id: number) => call<StatusResponse>(`${base(id)}/stop`, "POST");
