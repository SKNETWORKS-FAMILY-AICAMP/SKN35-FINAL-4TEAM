import type { DemoAgent, ToolAccess } from "../mocks/demo";

export const providers = ["Claude", "GPT", "Gemini", "DeepSeek"];
export function AgentSettings({ prompt, provider, model, temperature, onChange }: {
  prompt: string; provider: string; model: string; temperature: number;
  onChange: (value: { prompt?: string; provider?: string; model?: string; temperature?: number }) => void;
}) {
  return <>
    <div className="field"><label htmlFor="agent-prompt">에이전트에게 주는 기본 지시 <span className="muted">*</span></label><textarea id="agent-prompt" value={prompt} maxLength={10000} onChange={(e) => onChange({ prompt: e.target.value })} placeholder="예: 도구로 확인한 사실만 답하고, 메시지를 보내기 전에 확인받아 주세요." /><small>평소 사용하는 시스템 프롬프트를 입력해 주세요. 비교할 때 이 지시는 그대로 유지해요.</small></div>
    <div className="grid g2"><div className="field"><label htmlFor="agent-provider">모델 종류</label><select id="agent-provider" value={provider} onChange={(e) => onChange({ provider: e.target.value, model: "" })}>{providers.map((p) => <option key={p}>{p}</option>)}</select></div><div className="field"><label htmlFor="agent-model">사용 중인 모델 버전 <span className="muted">*</span></label><input id="agent-model" value={model} maxLength={100} onChange={(e) => onChange({ model: e.target.value })} placeholder="현재 설정의 정확한 버전 이름" /><small>새 모델을 추천하는 칸이 아니에요. 지금 쓰는 버전을 적어 주세요.</small></div></div>
    <details className="friendly-details"><summary>답변의 다양성 설정 <span className="muted">(온도)</span></summary><div className="field"><label htmlFor="agent-temperature">온도 값</label><input id="agent-temperature" type="number" min={0} max={2} step={0.1} value={temperature} onChange={(e) => onChange({ temperature: Number(e.target.value) })} /><small>낮을수록 답변이 일정하고, 높을수록 다양해져요. 현재 에이전트 설정과 같은 값을 입력해 주세요. 모델마다 허용 범위가 달라 실제 연결 때 다시 확인해요.</small></div></details>
  </>;
}

export function ToolSafety({ tools, writeMode, method, confirmed, onTools, onMode, onConfirm }: {
  tools: ToolAccess[]; writeMode: NonNullable<DemoAgent["writeMode"]>; method: string; confirmed: boolean;
  onTools: (tools: ToolAccess[]) => void; onMode: (mode: NonNullable<DemoAgent["writeMode"]>) => void; onConfirm: (checked: boolean) => void;
}) {
  const writes = tools.some((t) => t.access === "write");
  return <><h3 className="mt-6">정보를 읽나요, 실제로 바꾸나요?</h3><p className="small muted mb-4">조회만 하면 ‘읽기’, 메시지 발송·저장·수정이 가능하면 ‘쓰기’예요. 둘 다 가능하면 쓰기로 확인해 주세요. 서비스 전체가 아닌, 등록된 연결이 허용하는 동작을 기준으로 골라요.</p>
    {tools.map((tool, index) => <div className="tool-safety-row" key={`${tool.name}-${index}`}><b>{tool.name}</b><label className="sr-only" htmlFor={`access-${index}`}>{tool.name} 사용 권한</label><select id={`access-${index}`} value={tool.access} onChange={(e) => { onTools(tools.map((t, i) => i === index ? { ...t, access: e.target.value as ToolAccess["access"] } : t)); onConfirm(false); }}><option value="unknown">확인해 주세요</option><option value="read">읽기 · 정보 조회</option><option value="write">쓰기 · 발송·저장·수정</option></select></div>)}
    {writes && <fieldset className="write-policy"><legend>쓰기 동작은 어떻게 시험할까요?</legend><p className="small muted">실제 회사 데이터에 영향을 주지 않는 방식을 골라 주세요.</p>{[
      ["mock", "보내지 않고 기록만 남기기", "가짜 도구로 바꿔 무엇을 보내려 했는지만 확인해요. 권장 방식이에요."],
      ["exclude", "쓰기 동작이 필요한 문제 빼기", "문제 구성이 달라져 다른 결과와 직접 비교하기 어려울 수 있어요."],
      ...(method === "runner" ? [["runner", "내 테스트 공간에서 실행하기", "사용자가 준비한 테스트 공간에서만 실행하도록 설정하는 방식이에요."]] : []),
    ].map(([id, title, copy]) => <label className="opt" key={id}><input type="radio" name="write-mode" checked={writeMode === id} onChange={() => { onMode(id as NonNullable<DemoAgent["writeMode"]>); onConfirm(false); }} /><span><b>{title}</b><small className="block muted">{copy}</small></span></label>)}</fieldset>}
    {!!tools.length && <label className="confirmation-check"><input type="checkbox" checked={confirmed} onChange={(e) => onConfirm(e.target.checked)} /><span>도구의 읽기·쓰기 구분과 시험 방식을 확인했어요.</span></label>}
  </>;
}
