"use client";

import { useState } from "react";
import { ArrowLeft, Braces, Cable, CheckCircle2, FileJson, Laptop, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { sampleAgent, type DemoAgent, type ToolAccess } from "@/features/slotagent/mocks/demo";

import { AgentSettings, ToolSafety, providers } from "./agent-settings";

type Method = "api" | "file" | "runner";
const methods = { api: { title: "API로 연결", description: "API 주소로 에이전트 정보를 등록해요.", icon: Cable }, file: { title: "파일 업로드로 연결", description: "JSON 설정 파일에서 정보를 읽어와요.", icon: FileJson }, runner: { title: "Runner로 연결", description: "내 PC·CI에서 실행할 정보를 등록해요.", icon: Laptop } };

export function Registration({ onSave, onCancel }: { onSave: (agent: DemoAgent) => void; onCancel: () => void }) {
  const [method, setMethod] = useState<Method | null>(null);
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [job, setJob] = useState("");
  const [model, setModel] = useState("GPT-4.1 mini");
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState("GPT");
  const [temperature, setTemperature] = useState(0);
  const [access, setAccess] = useState<ToolAccess[]>([]);
  const [writeMode, setWriteMode] = useState<NonNullable<DemoAgent["writeMode"]>>("mock");
  const [confirmed, setConfirmed] = useState(false);
  const [dryRun, setDryRun] = useState(false);
  const [url, setUrl] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [file, setFile] = useState("");
  const [discovery, setDiscovery] = useState<DemoAgent["discovery"]>("pending");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function readFile(upload?: File) {
    if (!upload) return;
    setError(""); setFile(""); setTools([]); setAccess([]); setConfirmed(false); setDiscovery("pending"); setLoading(true);
    try {
      if (upload.size > 1024 * 1024) throw new Error("1MB 이하의 JSON 파일을 선택해 주세요.");
      const value: unknown = JSON.parse(await upload.text());
      if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("JSON 객체 형식의 설정 파일이 필요해요.");
      const data = value as Record<string, unknown>;
      for (const key of ["name", "job", "model", "prompt"]) if (data[key] !== undefined && typeof data[key] !== "string") throw new Error(`${key} 항목은 문자열이어야 해요.`);
      if (data.tools !== undefined && (!Array.isArray(data.tools) || data.tools.some((t: unknown) => !t || typeof t !== "object" || !["github", "slack", "db", "jira", "notion", "search", "custom"].includes((t as { s: string }).s) || !["mcp", "own"].includes((t as { how: string }).how)))) throw new Error("tools에는 지원 서비스(s)와 연결 방식(how: mcp 또는 own)이 필요해요.");
      if (data.provider !== undefined && !providers.includes(String(data.provider))) throw new Error("모델 종류는 Claude·GPT·Gemini·DeepSeek 중에서 선택해 주세요.");
      if (data.temperature !== undefined && (typeof data.temperature !== "number" || !Number.isFinite(data.temperature) || data.temperature < 0 || data.temperature > 2)) throw new Error("답변의 다양성은 0~2 사이 숫자로 입력해 주세요.");
      if (Array.isArray(data.tools) && data.tools.some((t) => t.access !== undefined && !["read", "write"].includes(t.access))) throw new Error("도구의 access는 read(읽기) 또는 write(쓰기)여야 해요.");
      setPrompt((data.prompt as string) || ""); setTemperature((data.temperature as number) ?? 0);
      setProvider((data.provider as string) || (/claude/i.test(String(data.model)) ? "Claude" : /gemini/i.test(String(data.model)) ? "Gemini" : /deepseek/i.test(String(data.model)) ? "DeepSeek" : "GPT"));
      setName((data.name as string) || ""); setJob((data.job as string) || ""); setModel((data.model as string) || "GPT-4.1 mini");
      const labels: Record<string, string> = { github: "GitHub", slack: "Slack", db: "DB (Postgres)", jira: "Jira", notion: "Notion", search: "웹 검색", custom: "직접 만든 도구" };
      setAccess((data.tools as { s: string; access?: "read" | "write" }[] || []).map((t) => ({ name: labels[t.s], access: t.access || "unknown" })));
      setTools((data.tools as { s: string }[] || []).map((t) => labels[t.s])); setDiscovery(data.tools === undefined ? "pending" : "configured"); setFile(upload.name);
    } catch (e) { setError(e instanceof Error ? e.message : "파일을 읽지 못했어요."); }
    finally { setLoading(false); }
  }
  function next() {
    setError("");
    if (step === 0) {
      if (method === "api") {
        try { const parsed = new URL(url); if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error(); }
        catch { setError("인증 정보·쿼리·해시가 없는 올바른 HTTP(S) 주소를 입력해 주세요."); return; }
      }
      if (method === "file" && !file) { setError("먼저 올바른 JSON 설정 파일을 선택해 주세요."); return; }
      if (!name.trim() || !job.trim()) { setError("에이전트 이름과 맡은 일을 입력해 주세요."); return; }
    }
    if (step === 0 && (!prompt.trim() || !model.trim() || !Number.isFinite(temperature) || temperature < 0 || temperature > 2)) { setError("기본 지시와 모델 버전을 입력하고, 답변 다양성 값을 0~2로 확인해 주세요."); return; }
    if (step === 1 && tools.length && (access.some((t) => t.access === "unknown") || !confirmed)) { setError("도구별 읽기·쓰기와 시험 방식을 확인하고 확인란에 체크해 주세요."); return; }
    if (step < 2) setStep(step + 1);
    else if (method) onSave({ id: crypto.randomUUID(), name: name.trim(), job: job.trim(), model: model.trim() || "미지정", method, tools, discovery, prompt: prompt.trim(), provider, temperature, toolAccess: access, writeMode, ...(method === "api" ? { connectionUrl: url.trim(), dryRun } : {}) });
  }

  if (!method) return <><div className="screen-title"><h1>에이전트를 어떻게 연결할까요?</h1><p className="muted">편한 방식으로 시작해요. 원래 설정은 바뀌지 않아요.</p></div><div className="banner">현재는 등록 화면을 체험하는 단계예요. 실제 API 연결이나 Runner 실행은 수행하지 않아요.</div><div className="connect-options">{Object.entries(methods).map(([id, item]) => <button className="select-card" key={id} onClick={() => { setMethod(id as Method); setError(""); setTools([]); setAccess([]); setFile(""); setDiscovery("pending"); setConfirmed(false); setWriteMode("mock"); }}><span className="service-icon"><item.icon size={22} /></span><h3>{item.title}</h3><p>{item.description}</p></button>)}</div><div className="card" style={{ marginTop: 24 }}><div className="row"><Braces size={22} /><div><h3>연결 없이 먼저 둘러볼래요</h3><p className="small muted">GitHub 도우미 예시로 비교 과정을 체험해요.</p></div><Button variant="outline" className="ml-auto" onClick={() => onSave({ ...sampleAgent })}>예시 에이전트 사용하기</Button></div></div><Button variant="ghost" onClick={onCancel}><ArrowLeft size={16} /> 돌아가기</Button></>;

  return <div className="registration"><Button variant="ghost" size="sm" onClick={() => { if (step) setStep(step - 1); else { setMethod(null); setError(""); } }}><ArrowLeft size={16} /> {step ? "이전 단계" : "연결 방식 선택"}</Button><div className="screen-title mt-6"><p className="small muted mb-2">{step + 1} / 3 · {methods[method].title}</p><h1>{["에이전트를 소개해 주세요", "도구 정보를 확인해 주세요", "이 정보로 등록할까요?"][step]}</h1></div><div className="card">
    {step === 0 && <>{method === "api" && <div className="field"><label htmlFor="api-url">API 주소</label><input id="api-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/agent" /><small>키·비밀번호가 없는 주소를 입력해 주세요. 실제 요청은 보내지 않아요.</small></div>}{method === "file" && <div className="field"><label htmlFor="config-file">설정 파일 (JSON)</label><input id="config-file" type="file" accept=".json,application/json" onChange={(e) => void readFile(e.target.files?.[0])} /><small>{loading ? "파일을 읽고 있어요…" : file ? `${file} 내용을 불러왔어요.` : "name, job, model, tools 항목을 읽어요. (1MB 이하)"}</small></div>}{method === "runner" && <p className="banner">Runner 설치·연결은 준비 중이에요. 등록 정보를 먼저 저장해요.</p>}<div className="field"><label htmlFor="agent-name">에이전트 이름 <span className="muted">*</span></label><input id="agent-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 우리 팀 GitHub 도우미" /></div><div className="field"><label htmlFor="agent-job">어떤 일을 맡고 있나요? <span className="muted">*</span></label><textarea id="agent-job" maxLength={1000} value={job} onChange={(e) => setJob(e.target.value)} placeholder="예: 배포 상태와 이슈, PR을 찾아 팀에 알려줘요." /></div><AgentSettings prompt={prompt} provider={provider} model={model} temperature={temperature} onChange={(value) => { if (value.prompt !== undefined) setPrompt(value.prompt); if (value.provider !== undefined) setProvider(value.provider); if (value.model !== undefined) setModel(value.model); if (value.temperature !== undefined) setTemperature(value.temperature); }} /></>}
    {step === 1 && <>{method === "api" && <div className="banner"><b>API 연결은 현재 상태를 진단하는 방식이에요.</b><p>설정을 바꿔 실행할 수 없어 ‘채택·기각’ 같은 교체 판정은 제공하지 않아요. 실제 연결은 아직 준비 중이에요.</p><label className="confirmation-check"><input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />외부에 쓰지 않는 시험 모드(드라이런)로 설정했어요.</label><p className="small">이 확인만으로 실제 연결을 검증하지는 않아요. 실제 실행은 연결 기능이 준비된 뒤 가능해요.</p></div>}<h2>연결 정보에서 찾은 도구</h2><p className="muted small mb-6">도구는 연결 정보에서 가져와요. 직접 선택하지 않아도 돼요.</p>{discovery === "pending" ? <div className="howto"><b>도구 탐색 대기</b><p>실제 연결이 완료되면 도구 목록을 가져올 예정이에요. 지금은 기본 등록 정보만 저장할 수 있어요.</p></div> : <><p className="small muted">설정 파일의 연결 구성 · 실제 호출 여부 미확인</p><div className="service-tags">{tools.map((tool, i) => <span className="pill b" key={`${tool}-${i}`}>{tool}</span>)}</div>{!tools.length && <p className="small muted">설정 파일에 등록된 도구가 없어요.</p>}</>}<ToolSafety tools={access} writeMode={writeMode} method={method} confirmed={confirmed} onTools={setAccess} onMode={setWriteMode} onConfirm={setConfirmed} /><p className="note mt-6">GitHub 도구 정보가 있어야 GitHub 교체 후보를 비교할 수 있어요. 예시 에이전트로도 체험할 수 있어요.</p></>}
    {step === 2 && <><CheckCircle2 size={32} className="text-[var(--green)] mb-6" /><dl className="grid gap-4"><dt>에이전트 이름</dt><dd>{name}</dd><dt>맡은 일</dt><dd>{job}</dd><dt>모델</dt><dd>{provider} · {model} · 답변 다양성 {temperature}</dd><dt>기본 지시</dt><dd className="text-prewrap">{prompt}</dd><dt>쓰기 동작</dt><dd>{access.some((t) => t.access === "write") ? writeMode === "mock" ? "보내지 않고 기록만 남기기" : writeMode === "exclude" ? "쓰기 문제 제외" : "내 테스트 공간에서 실행" : "확인된 쓰기 도구 없음"}</dd><dt>연결 방식</dt><dd>{methods[method].title}</dd><dt>도구 정보</dt><dd>{discovery === "pending" ? "탐색 대기 · 미확인" : tools.join(", ") || "등록된 도구 없음"}</dd></dl><p className="note mt-6">이 브라우저에 등록 정보를 저장해요. 실제 서비스 연결은 수행하지 않아요.</p></>}
    {error && <p role="alert" className="err mt-4">{error}</p>}<div className="page-actions"><Button variant="outline" onClick={onCancel}>취소</Button><Button onClick={next} disabled={loading}>{step === 2 ? <><Plus size={16} /> 등록 정보 저장</> : "다음"}</Button></div></div></div>;
}

