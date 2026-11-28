"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { PlanProposalRequest, PlanProposalResponse, RegisterAgentResponse } from "@/types/contracts";
import { createExperiment, proposePlan, registerAgent, registerCandidate } from "../api";

// 실제 API 로 등록 → 후보 → 계획 제안 → 초안. 입력은 계약 모양 JSON 그대로 (검사는 백엔드가 함).
function parse(text: string): unknown {
  try { return JSON.parse(text); } catch { throw new Error("JSON 형식이 올바르지 않아요."); }
}

export function LiveSetup() {
  const [agentJson, setAgentJson] = useState("");
  const [agent, setAgent] = useState<RegisterAgentResponse | null>(null);
  const [slotId, setSlotId] = useState<number | null>(null);
  const [candidateJson, setCandidateJson] = useState("");
  const [extra, setExtra] = useState<number[]>([]);
  const [packId, setPackId] = useState("");
  const [request, setRequest] = useState<PlanProposalRequest | null>(null);
  const [proposal, setProposal] = useState<PlanProposalResponse | null>(null);
  const [experimentId, setExperimentId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const slot = agent?.slots.find((s) => s.slot_id === slotId);

  async function act(work: () => Promise<void>) {
    setError(""); setBusy(true);
    try { await work(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const register = () => act(async () => {
    const saved = await registerAgent(parse(agentJson) as never);
    setAgent(saved); setSlotId(saved.slots.find((s) => s.comparable)?.slot_id ?? null);
    setExtra([]); setProposal(null); setExperimentId(null);
  });
  const addCandidate = () => act(async () => {
    if (!slot) throw new Error("비교할 자리를 먼저 골라 주세요.");
    const { candidate_id } = await registerCandidate(slot.slot_id, parse(candidateJson) as never);
    setExtra((prev) => [...prev, candidate_id]); setCandidateJson(""); setProposal(null);
  });
  const propose = () => act(async () => {
    if (!agent || !slot) throw new Error("에이전트와 자리를 먼저 정해 주세요.");
    const pack = Number(packId);
    if (!Number.isSafeInteger(pack) || pack < 1) throw new Error("평가팩 버전 번호를 입력해 주세요.");
    const req = { agent_version_id: agent.agent_version_id, slot_id: slot.slot_id, pack_version_id: pack,
      candidate_ids: [slot.baseline_candidate_id, ...extra] } as PlanProposalRequest;
    setProposal(await proposePlan(req)); setRequest(req); setExperimentId(null);
  });
  const create = () => act(async () => {
    if (!proposal || !request) return;
    const { experiment_id } = await createExperiment({
      agent_version_id: request.agent_version_id, slot_id: request.slot_id, pack_version_id: request.pack_version_id,
      candidates: request.candidate_ids, reps: proposal.reps, prereg: proposal.prereg, plan: proposal.plan,
      proposal: { request, as_of: proposal.as_of },
    } as never);
    setExperimentId(experiment_id);
  });

  return <>
    <div className="screen-title"><h1 tabIndex={-1}>실제 API 로 실험 만들기</h1><p className="muted">계약 모양 JSON 으로 등록부터 실험 초안까지 서버에 저장해요. 실행은 다음 화면에서 시작해요.</p></div>
    {error && <p role="alert" className="err">{error}</p>}
    <section className="card">
      <h2>1. 에이전트 등록</h2>
      <div className="field"><label htmlFor="agent-json">등록 요청 (register_agent_request)</label><textarea id="agent-json" rows={8} value={agentJson} onChange={(e) => setAgentJson(e.target.value)} placeholder='{"name": "...", "version": {...}}' /></div>
      <Button onClick={register} disabled={busy || !agentJson.trim()}>등록</Button>
      {agent && <div className="field mt-4"><label htmlFor="slot">비교할 자리</label><select id="slot" value={slotId ?? ""} onChange={(e) => { setSlotId(Number(e.target.value)); setExtra([]); setProposal(null); }}>
        {agent.slots.map((s) => <option key={s.slot_id} value={s.slot_id} disabled={!s.comparable}>{s.name} · {s.service}/{s.access}{s.comparable ? "" : ` (비교 불가: ${s.not_comparable_reason ?? ""})`}</option>)}
      </select><small>에이전트 #{agent.agent_id} · 버전 #{agent.agent_version_id} · 기준 후보 #{slot?.baseline_candidate_id ?? "-"}</small></div>}
    </section>
    {slot && <section className="card mt-4">
      <h2>2. 비교 후보 (기준 말고 최대 2개)</h2>
      <div className="field"><label htmlFor="candidate-json">후보 요청 (register_candidate_request)</label><textarea id="candidate-json" rows={6} value={candidateJson} onChange={(e) => setCandidateJson(e.target.value)} placeholder='{"label": "B", "name": "...", "component_spec": {...}}' /></div>
      <Button onClick={addCandidate} disabled={busy || !candidateJson.trim() || extra.length >= 2}>후보 추가</Button>
      <p className="small muted mt-2">후보: 기준 #{slot.baseline_candidate_id}{extra.map((id) => `, #${id}`).join("")}</p>
    </section>}
    {slot && extra.length > 0 && <section className="card mt-4">
      <h2>3. 계획 제안</h2>
      <div className="field"><label htmlFor="pack">평가팩 버전 번호 (잠긴 팩)</label><input id="pack" type="number" min={1} value={packId} onChange={(e) => setPackId(e.target.value)} /></div>
      <Button onClick={propose} disabled={busy}>계획 받기</Button>
      {proposal && <><dl className="friendly-facts mt-4"><dt>문항 유형</dt><dd>{proposal.n_templates}개</dd><dt>문항</dt><dd>{proposal.n_tasks}개</dd><dt>반복</dt><dd>{proposal.reps}번</dd><dt>전체 풀이</dt><dd>{proposal.trials}회</dd></dl>
        {proposal.warnings?.map((w) => <p key={w} className="banner">{w}</p>)}</>}
    </section>}
    {proposal && <div className="page-actions">
      {experimentId
        ? <Button onClick={() => { window.location.href = `/?experiment=${experimentId}`; }}>실험 #{experimentId} 실행 화면으로</Button>
        : <Button onClick={create} disabled={busy}>이 계획으로 초안 저장</Button>}
    </div>}
  </>;
}
