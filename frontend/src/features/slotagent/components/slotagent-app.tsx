"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Bot, Check, ChevronRight, CircleHelp, FileText, FlaskConical, Github, History, Home, Moon, Plus, ShieldCheck, Sun, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Registration } from "@/features/slotagent/components/registration";
import { TrialSettings } from "./trial-settings";
import { ResultDetails, EvaluationContext, SummaryEvidence } from "./result-details";
import { DemoChat } from "@/features/slotagent/components/demo-chat";
import { LiveRun } from "./live-run";
import { bestCandidate, candidates, percent, sampleAgent, steps, won, defaultDesign, type TrialDesign, type CandidateId, type DemoAgent, type DemoComparison } from "@/features/slotagent/mocks/demo";
import { readDemo, saveDemo } from "@/features/slotagent/storage";

type View = "home" | "test" | "agents" | "history" | "account";
const navigation = [{ id: "home", label: "홈", icon: Home }, { id: "test", label: "새 비교", icon: Plus }, { id: "agents", label: "내 에이전트", icon: Bot }, { id: "history", label: "비교 기록", icon: History }, { id: "account", label: "마이페이지", icon: UserRound }] as const;
const titleFor = (result: DemoComparison) => {
  const best = bestCandidate(result.candidates);
  return best === "C" ? result.preference === "none" ? "더 좋아 보이지만, 아직 확신하기는 어려워요" : "필요한 도구만 남기면, 더 가볍게 일할 수 있어요" : "지금은 바꾸기보다, 조금 더 확인해 봐요";
};
const verdictFor = (result: DemoComparison) => bestCandidate(result.candidates) === "C" && result.preference !== "none" ? "조건부 채택" : "판단 보류";
function ScreenTitle({ title, children }: { title: string; children?: React.ReactNode }) { return <div className="screen-title"><h1 tabIndex={-1}>{title}</h1>{children && <p className="muted">{children}</p>}</div>; }

export function SlotAgentApp() {
  const [view, setView] = useState<View>("home");
  const [step, setStep] = useState(0);
  const [reached, setReached] = useState(0);
  const [agents, setAgents] = useState<DemoAgent[]>([]);
  const [history, setHistory] = useState<DemoComparison[]>([]);
  const [selected, setSelected] = useState("sample");
  const [selectedCandidates, setSelectedCandidates] = useState<CandidateId[]>(["C", "A"]);
  const [preference, setPreference] = useState("cost");
  const [targets, setTargets] = useState<string[]>(["run"]);
  const [design, setDesign] = useState<TrialDesign>({ ...defaultDesign });
  const [dailyCalls, setDailyCalls] = useState(300);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [detail, setDetail] = useState(false);
  const [ready, setReady] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [comparison, setComparison] = useState<DemoComparison | null>(null);
  const [modal, setModal] = useState<{ title: string; body: string } | null>(null);
  const [toast, setToast] = useState("");
  const [storageWarning, setStorageWarning] = useState(false);
  const [liveId, setLiveId] = useState<number | null>(null); // ?experiment=번호 면 3단계를 실제 API 로 돌림
  const current = agents.find((a) => a.id === selected) || sampleAgent;
  const capable = current.method !== "api" && current.tools.includes("GitHub");
  const main = useRef<HTMLElement>(null);
  const pendingRun = useRef<DemoComparison | null>(null);

  useEffect(() => {
    const saved = readDemo();
    if (saved) { setAgents(saved.agents); setHistory(saved.history); setDailyCalls(saved.dailyCalls); setTheme(saved.theme); }
    const id = Number(new URLSearchParams(window.location.search).get("experiment"));
    if (Number.isSafeInteger(id) && id > 0) setLiveId(id);
    setReady(true);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    if (ready) setStorageWarning(!saveDemo({ agents, history, dailyCalls, theme }));
  }, [agents, history, dailyCalls, theme, ready]);
  useEffect(() => { if (toast) { const timer = setTimeout(() => setToast(""), 4000); return () => clearTimeout(timer); } }, [toast]);
  useEffect(() => {
    main.current?.querySelector<HTMLElement>("h1")?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [view, step, registering]);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setProgress((p) => Math.min(100, p + 4)), 220);
    return () => window.clearInterval(timer);
  }, [running]);
  useEffect(() => {
    if (!running || progress < 100 || !pendingRun.current) return;
    const completed = pendingRun.current;
    pendingRun.current = null;
    setRunning(false); setComparison(completed); setHistory((prev) => [completed, ...prev].slice(0, 50)); setStep(4); setReached(5); setToast("비교가 끝났어요. 예시 결과를 확인해 주세요.");
  }, [progress, running]);

  function navigate(next: View) {
    if (running) { setToast("실행 중인 비교를 완료하거나 중단한 뒤 이동해 주세요."); return; }
    setRegistering(false); setView(next);
    if (next === "test") { setStep(0); setReached(0); setComparison(null); }
  }
  function go(next: number) { if (running) return; setStep(next); setReached((prev) => Math.max(prev, next)); }
  function ensureSample() { setAgents((prev) => prev.some((a) => a.id === "sample") ? prev : [sampleAgent, ...prev]); setSelected("sample"); }
  function makeComparison(agent = current): DemoComparison { return { id: crypto.randomUUID(), agent: { ...agent }, candidates: [...selectedCandidates], preference, targets: [...targets], date: new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }), dailyCalls, design: { ...design } }; }
  function startComparison() {
    if (liveId) { setStep(3); setReached(3); return; }
    if (!selectedCandidates.length || !capable) return;
    pendingRun.current = makeComparison(); setComparison(null); setProgress(0); setRunning(true); setStep(3); setReached(3);
  }
  function preview() {
    ensureSample(); setSelectedCandidates(["C", "A"]); setPreference("cost"); setComparison({ ...makeComparison(sampleAgent), candidates: ["C", "A"], preference: "cost" }); setView("test"); setRegistering(false); setStep(4); setReached(5);
  }
  function stopRun() { pendingRun.current = null; setRunning(false); setProgress(0); setStep(2); setReached(2); setToast("예시 시험을 중단했어요. 설정을 확인하고 다시 시작할 수 있어요."); }
  function toggleCandidate(id: CandidateId) { setSelectedCandidates((prev) => prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]); setReached(1); }
  function chooseAgent(id: string) { setSelected(id); setReached(0); setComparison(null); }
  const allCandidates: CandidateId[] = ["B", ...selectedCandidates];
  const showSteps = view === "test" && !registering;
  const modalRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!modal) return;
    previousFocus.current = document.activeElement as HTMLElement;
    modalRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const previousOverflow = document.body.style.overflow; document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; previousFocus.current?.focus(); };
  }, [modal]);

  return <>
    <nav className="menu" aria-label="주 메뉴">
      <a className="side-brand" href="#" onClick={(e) => { e.preventDefault(); navigate("home"); }}><span className="slot-logo" />SlotAgent</a>
      <span className="side-tagline">바꾸기 전에, 먼저 시험해 봐요</span>
      {navigation.map((item) => <button key={item.id} data-v={item.id} className={view === item.id ? "on" : ""} aria-current={view === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><item.icon size={20} strokeWidth={1.7} />{item.label}</button>)}
      <div className="side-safe"><strong><ShieldCheck size={17} /> 원래 설정은 안전해요</strong><p>도구를 바꾸기 전,<br />복사한 환경에서 먼저 시험해요.</p></div>
      <div className="side-team"><span className="service-icon"><UserRound size={18} /></span><div>우리 팀 작업 공간<small>팀 리더 · 체험 모드</small></div></div>
    </nav>
    <header className="top"><div className="topin"><div className="mobile-brand"><span className="slot-logo" />SlotAgent</div><span className="breadcrumb">우리 팀 작업 공간 <ChevronRight size={12} className="inline mx-2" /> {navigation.find((n) => n.id === view)?.label}</span>{view === "test" && step === 4 && !registering && comparison && (<div className="toggle" aria-label="보기 방식">{[false, true].map((value) => <button key={String(value)} className={detail === value ? "on" : ""} aria-pressed={detail === value} onClick={() => setDetail(value)}>{value ? "자세히 보기" : "쉽게 보기"}</button>)}</div>)}<button className="theme-button" aria-label={theme === "light" ? "어두운 테마로 변경" : "밝은 테마로 변경"} onClick={() => setTheme(theme === "light" ? "dark" : "light")}>{theme === "light" ? <Moon size={21} /> : <Sun size={21} />}</button></div>
      {showSteps && <nav className="steps" aria-label="비교 단계">{steps.map((label, index) => <button key={label} className={`step ${step === index ? "on" : ""} ${index < step ? "done" : ""}`} aria-current={step === index ? "step" : undefined} disabled={running || index > reached || (index >= 4 && !comparison)} onClick={() => go(index)}><span className="n">{index < step ? <Check size={13} /> : index + 1}</span>{label}</button>)}</nav>}
    </header>
    <div className="wrap"><main ref={main} id="main-content">
      {storageWarning && <div className="banner" role="status">브라우저 저장 공간을 사용할 수 없어 새로고침하면 변경 내용이 사라질 수 있어요.</div>}
      {registering ? <Registration onCancel={() => setRegistering(false)} onSave={(agent) => { setAgents((prev) => [...prev.filter((a) => a.id !== agent.id), agent]); setSelected(agent.id); setRegistering(false); setView("test"); setStep(0); setReached(0); setToast("등록 정보를 저장했어요. 비교할 에이전트를 확인해 주세요."); }} /> : <>
        {view === "home" && <section className="page on" id="v-home"><p className="hero-kicker">바꾸기 전에, 먼저 시험해 봐요</p><section className="figma-hero"><div className="hero-copy"><span className="pill b">우리 팀의 첫 비교</span><h1 tabIndex={-1}>에이전트의 도구를 바꾸면<br />더 나아질까요?</h1><p className="lead">같은 시험 문제로 지금 도구와 새 도구를 비교해요.<br />팀에 더 나은 선택인지, 쉬운 말로 알려드려요.</p></div><div className="hero-actions"><Button onClick={() => { if (agents.length) navigate("test"); else { setView("agents"); setRegistering(true); } }}>첫 비교 시작하기 <ArrowRight size={16} /></Button><Button variant="outline" onClick={preview}>결과 예시 먼저 보기</Button></div><p className="hero-note">약 5분이면 시작해요 · 원래 설정은 바뀌지 않아요</p><div className="slot-illustration"><div className="slot-drawing motion-visible" role="img" aria-label="에이전트의 도구 블록을 슬롯에 바꿔 끼우는 모습">{[["MachineBase", "slot-base"], ["ConnectingDashedGuide", "slot-guide"], ["FloatingIndigoBlock", "slot-block"], ["TestIndicators", "slot-indicators"]].map(([asset, className]) => <img key={asset} src={`/demo/${asset}.svg`} alt="" className={className} />)}</div></div><p className="illustration-caption">도구만 바꿔 끼우고, 차이를 확인해요</p></section><h2 className="journey-title">도구 비교부터 결정까지, 세 단계면 충분해요</h2><section className="journey" aria-label="비교 이용 방법">{[["바꿀 자리를 골라요", "도구가 연결된 자리를 확인해요."], ["같은 문제로 시험해요", "비용과 속도, 정답을 나란히 봐요."], ["바꿔도 될지 결정해요", "조심할 점까지 한 장에 정리해요."]].map(([title, copy], i) => <article key={title}><span className="index">0{i + 1}</span><h3>{title}</h3><p>{copy}</p></article>)}</section></section>}

        {view === "agents" && <><div className="heading-row"><ScreenTitle title="내 에이전트">우리 팀 에이전트와 연결 정보를 한곳에서 확인해요.</ScreenTitle><Button onClick={() => setRegistering(true)}><Plus size={16} /> 에이전트 등록</Button></div>{!agents.length ? <div className="card empty"><Bot size={44} /><h2>첫 에이전트를 등록해 볼까요?</h2><p>API, 설정 파일, Runner 중 편한 방식으로 시작해요.</p><Button onClick={() => setRegistering(true)}>에이전트 등록하기</Button><Button variant="outline" className="ml-3" onClick={() => { ensureSample(); setToast("예시 에이전트를 추가했어요."); }}>예시 에이전트 추가</Button></div> : <div className="agent-grid">{agents.map((a) => <article className="select-card" key={a.id}><div className="row"><span className="service-icon"><Bot size={22} /></span><span className="pill b">{a.method === "example" ? "예시" : "등록 정보 저장됨"}</span></div><h3>{a.name}</h3><p>{a.job}</p><p>{a.model} · {a.discovery === "pending" ? "도구 탐색 대기" : `${a.tools.length}개 연결 구성`}</p><div className="service-tags">{a.tools.map((t, i) => <span className="pill" key={`${t}-${i}`}>{t}</span>)}</div><Button className="mt-6" variant="outline" onClick={() => { chooseAgent(a.id); setView("test"); setStep(0); }}>이 에이전트로 비교</Button></article>)}<button className="agent-add" onClick={() => setRegistering(true)}><Plus size={24} /> 새 에이전트 등록</button></div>}</>}

        {view === "test" && <>
          {step === 0 && <><ScreenTitle title="어떤 에이전트를 비교할까요?">연결된 에이전트를 고르거나, 예시로 먼저 시작해요.</ScreenTitle><div className="agent-grid">{[...agents, ...(!agents.some((a) => a.id === "sample") ? [sampleAgent] : [])].map((a) => <button key={a.id} className={`select-card ${selected === a.id ? "selected" : ""}`} aria-pressed={selected === a.id} onClick={() => chooseAgent(a.id)}><div className="row"><span className="service-icon"><Bot size={22} /></span><span className={`pill ${a.method === "example" ? "b" : ""}`}>{a.method === "example" ? "예시 에이전트" : "등록한 에이전트"}</span></div><h3>{a.name}</h3><p>{a.job}</p><div className="service-tags">{a.tools.map((tool, i) => <span className="pill" key={`${tool}-${i}`}>{tool}</span>)}{!a.tools.length && <span className="pill">도구 탐색 대기</span>}</div></button>)}<button className="agent-add" onClick={() => setRegistering(true)}><Plus size={24} /> 새 에이전트 연결</button></div><p className="note mt-6">예시 에이전트는 실제 연결 없이 화면 흐름을 확인할 수 있어요.</p><div className="page-actions"><Button variant="outline" onClick={() => navigate("home")}>홈으로</Button><Button onClick={() => { if (selected === "sample") ensureSample(); go(1); }}>이 에이전트로 계속하기 <ArrowRight size={16} /></Button></div></>}

          {step === 1 && <><ScreenTitle title="어떤 도구를 바꿔 볼까요?">연결된 자리에서 비교할 후보를 골라 주세요.</ScreenTitle><div className="card"><div className="row"><span className="service-icon"><Github size={23} /></span><div><h2>GitHub 조회</h2><p className="small muted">이슈 · PR · 배포 기록을 읽어오는 자리</p></div><span className="pill b ml-auto">{capable ? "비교할 수 있어요" : current.method === "api" ? "진단만 가능" : "도구 정보 미확인"}</span></div></div><p className="small muted mb-5">지금 쓰는 도구는 비교 기준으로 항상 포함돼요.</p><div className="grid g3">{(["B", "C", "A"] as CandidateId[]).map((id) => <label className={`select-card ${id !== "B" && selectedCandidates.includes(id) ? "selected" : ""}`} key={id}><div className="row"><span className={`pill ${id === "C" ? "b" : ""}`}>{id === "B" ? "비교 기준" : id === "C" ? "추천 후보" : "비교 후보"}</span><input aria-label={`${candidates[id].name} 비교에 포함`} type="checkbox" checked={id === "B" || selectedCandidates.includes(id)} disabled={id === "B" || !capable} onChange={() => toggleCandidate(id)} /></div><h3>{candidates[id].name}</h3><strong className="text-3xl">{candidates[id].size}<small className="text-sm font-normal muted ml-1">개 도구</small></strong><p>{candidates[id].description}</p></label>)}</div>{!capable && <div className="banner mt-6">{current.method === "api" ? "API 연결은 현재 상태를 진단하는 방식이에요. 자리 교체 판정은 제공하지 않으며, 실제 진단 연결은 준비 중이에요." : "GitHub 도구 정보가 없어 이 자리를 비교할 수 없어요."} <button className="underline" onClick={() => { ensureSample(); setReached(1); }}>예시 에이전트로 전환하기</button></div>}{!selectedCandidates.length && <p className="err mt-4" role="alert">비교할 후보를 한 개 이상 선택해 주세요.</p>}<div className="page-actions"><Button variant="outline" onClick={() => go(0)}>이전</Button><Button disabled={!capable || !selectedCandidates.length} onClick={() => go(2)}>이 후보들로 시험 정하기 <ArrowRight size={16} /></Button></div></>}

          {step === 2 && <TrialSettings agentName={current.name} ids={allCandidates} preference={preference} targets={targets} design={design} onPreference={(v) => { setPreference(v); setReached(2); }} onTargets={(v) => { setTargets(v); setReached(2); }} onDesign={(v) => { setDesign(v); setReached(2); }} onBack={() => go(1)} onStart={startComparison} />}

          {step === 3 && liveId && <LiveRun experimentId={liveId} onBack={() => go(2)} />}
          {step === 3 && !liveId && <><ScreenTitle title="같은 문제로, 공정하게 비교하고 있어요">예시 기록을 재생하고 있어요. 외부 도구를 호출하지 않아요.</ScreenTitle><div className="run-layout"><section className="card">{allCandidates.map((id) => <div className="run-candidate" key={id}><div className="row"><b>{candidates[id].name} {candidates[id].size}개</b><small>{Math.round(progress * 0.92)} / 92회</small></div><div className="meter" role="progressbar" aria-label={`${candidates[id].name} 진행률`} aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${progress}%` }} /></div><div className="run-dots" aria-hidden="true">{Array.from({ length: 46 }, (_, i) => <i key={i} className={i < progress * 0.46 ? "completed" : ""} />)}</div></div>)}</section><aside className="run-side"><div className="run-stat"><p>실제 청구 비용</p><strong>0원</strong><small>예시 실행 · 실제 과금이 없어요</small></div><div className="run-stat"><p>비교 진행률</p><strong>{progress}%</strong><small>같은 문제를 후보마다 두 번씩 풀어요</small></div></aside></div><section className="card run-records"><h2>실시간 시험 기록 <span className="pill b">예시 재생</span></h2><div className="runlog" aria-label="예시 시험 기록">{Array.from({ length: Math.max(1, Math.floor(progress / 7)) }, (_, i) => <p key={i}><span className="muted">[예시 {(i + 1).toString().padStart(2, "0")}]</span> {candidates[allCandidates[i % allCandidates.length]].name} · {["배포 버전 확인", "이슈에 연결된 PR 찾기", "실패한 실행 확인", "담당자 조회"][i % 4]} <span style={{ color: i % 4 === 2 ? "var(--amber)" : "var(--green)" }}>— {i % 4 === 2 ? "검토 필요" : "채점 완료"}</span></p>)}</div></section><div className="page-actions"><Button variant="outline" onClick={stopRun}>시험 중단</Button><span className="small muted">현재 설정은 안전해요.</span><Button variant="outline" onClick={() => setProgress(100)}>완료 예시 보기</Button></div></>}

          {step === 4 && comparison && <Results comparison={comparison} detail={detail} onSummary={() => go(5)} onRange={() => setModal({ title: "차이가 흔들리는 범위", body: bestCandidate(comparison.candidates) === "C" ? "필요한 것만 8개 − 지금 구성 26개\n정답률 차이 +16.3%p · 예시 범위는 비교 후보 수에 따라 달라져요. 정확한 범위는 한 장 요약에서 확인해 주세요.\n\n범위에 0이 포함돼 성능이 확실히 좋아졌다고 단정하기는 어려워요. 미리 정한 비용·속도 기준이 좋아졌을 때 조건부 채택으로 표시해요. 성능을 최우선으로 고르면 판단을 보류해요.\n\n채점 검증 전의 예시 기록이며 실제 서비스 성능을 보장하지 않아요." : "직접 만든 도구 1개는 예시에서 92번 중 72번 정답이었어요. 지금 구성(76번 정답)보다 낮고, 아직 확실한 개선 근거가 없어 판단을 보류해요." })} />}
          {step === 5 && comparison && <Summary comparison={comparison} onBack={() => go(4)} onNew={() => navigate("test")} onShare={() => setModal({ title: "공유 링크는 준비 중이에요", body: "현재는 브라우저에 저장되는 UI 체험 화면이에요. 다른 사람이 열 수 있는 공유 링크는 생성하지 않아요.\n\n‘PDF로 저장하기’를 누르면 브라우저 인쇄 창에서 한 장 요약을 저장할 수 있어요." })} />}
        </>}

        {view === "history" && <><ScreenTitle title="비교 기록">어떤 선택을 했는지, 그 이유까지 남겨요.</ScreenTitle><section className="card"><h2>최근 비교 <span className="pill">{history.length}건</span></h2>{!history.length ? <div className="empty"><History size={40} /><h3>아직 비교 기록이 없어요</h3><p>첫 비교를 끝내면 이 브라우저에 기록이 남아요.</p><Button onClick={() => navigate("test")}>새 비교 시작하기</Button></div> : <div className="tw"><table className="history-table"><thead><tr><th>에이전트</th><th>바꿔 본 도구</th><th>판정</th><th>완료일</th><th><span className="sr-only">결과</span></th></tr></thead><tbody>{history.map((h) => <tr key={h.id}><td>{h.agent.name}</td><td>GitHub · {candidates[bestCandidate(h.candidates)].size}개</td><td><span className="pill b">{verdictFor(h)}</span></td><td>{h.date}</td><td><Button size="sm" variant="outline" onClick={() => { setComparison(h); setSelected(h.agent.id); setSelectedCandidates(h.candidates); setPreference(h.preference); setTargets(h.targets); setDesign(h.design || { ...defaultDesign }); setView("test"); setStep(4); setReached(5); }}>결과 다시 보기</Button></td></tr>)}</tbody></table></div>}<p className="note mt-5">이 브라우저에 최근 50건을 보관해요. 홈의 결과 미리보기는 기록에 추가되지 않아요.</p></section></>}

        {view === "account" && <><ScreenTitle title="편하게 쓰도록 맞춰요">우리 팀 작업 공간 · 팀 리더</ScreenTitle><section className="card account-settings"><h2>화면 설정</h2><div className="setting-row"><b>테마</b><div className="row"><span>{theme === "light" ? "밝은 화면" : "어두운 화면"}</span><Button size="sm" variant="outline" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>테마 바꾸기</Button></div></div><div className="setting-row"><b>보기 방식</b><div className="row"><span>{detail ? "자세히 보기" : "쉽게 보기"}</span><Button size="sm" variant="outline" onClick={() => setDetail(!detail)}>보기 바꾸기</Button></div></div></section><section className="card"><h2>비용 계산 기준</h2><div className="field mt-5"><label htmlFor="daily-calls">하루에 에이전트를 몇 번 쓰나요?</label><input id="daily-calls" type="number" min={1} max={100000} value={dailyCalls} onChange={(e) => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 1 && n <= 100000) setDailyCalls(n); }} /><small>1~100,000회 · 새 비교 결과의 한 달 예상 비용을 이 값으로 계산해요. 기존 기록은 당시 기준을 유지해요.</small></div></section><section className="card"><h2>체험 모드 안내</h2><p className="small muted">등록 정보와 비교 기록은 이 브라우저에 저장돼요. 실제 API 연결·도구 실행·결제·공유 링크 발급은 아직 연결되지 않았어요.</p></section></>}
      </>}
    </main></div>
    <DemoChat comparison={comparison} />
    {toast && <div className="toast" role="status">{toast}</div>}
    {modal && <div className="dialog-backdrop" onClick={(e) => { if (e.target === e.currentTarget) setModal(null); }}><div ref={modalRef} className="dialog-panel" role="dialog" aria-modal="true" aria-labelledby="dialog-title" onKeyDown={(e) => { if (e.key === "Escape") setModal(null); if (e.key === "Tab") { e.preventDefault(); modalRef.current?.querySelector<HTMLButtonElement>("button")?.focus(); } }}><h2 id="dialog-title">{modal.title}</h2><p>{modal.body}</p><Button onClick={() => setModal(null)}>알겠어요</Button></div></div>}
  </>;
}

function Results({ comparison, detail, onSummary, onRange }: { comparison: DemoComparison; detail: boolean; onSummary: () => void; onRange: () => void }) {
  const best = bestCandidate(comparison.candidates);
  const after = candidates[best];
  const monthly = (id: CandidateId) => candidates[id].perRun * comparison.dailyCalls * 30;
  const delta = (after.correct - candidates.B.correct) / 92 * 100;
  return <><EvaluationContext comparison={comparison} /><section className="result-verdict"><span className="pill b">{verdictFor(comparison)}</span><h1 tabIndex={-1}>{titleFor(comparison)}</h1><p>{best === "C" ? "다만, 실패한 실행을 설명할 때는 사람이 한 번 확인해 주세요." : "차이와 남아 있는 위험 요인을 확인한 뒤 결정해 주세요."}</p></section><div className="grid g3 result-kpis">{[["정답률", `${percent("B")} → ${percent(best)}`, `${Math.abs(delta).toFixed(1)}%p ${delta >= 0 ? "더 정확해졌어요" : "낮아졌어요"}`], ["한 달 예상 비용", `${won(monthly("B"))} → ${won(monthly(best))}`, `매달 아낄 수 있는 비용 ${won(monthly("B") - monthly(best))}`], ["답변까지 걸리는 시간", `${candidates.B.seconds}초 → ${after.seconds}초`, "예시 기록의 중앙값 기준"]].map(([title, value, hint], i) => <article className={`card result-kpi ${i === 1 ? "money" : ""}`} key={title}><p>{title}</p><strong>{value}</strong><small>{hint}</small></article>)}</div><div className="section-row"><h2>후보를 나란히 보면</h2><small>같은 46문항 · 2회 반복 · 후보당 92회</small></div><div className="grid g3">{(["B", ...comparison.candidates] as CandidateId[]).map((id) => <article key={id} className={`result-candidate ${id === best ? "best" : ""}`}><h3>{candidates[id].name} {candidates[id].size}개</h3><span className="result-label">{id === best ? verdictFor(comparison) : candidates[id].label}</span><p>정답률 {percent(id)}　월 {won(monthly(id))}</p><small>{id === "B" ? "기준을 그대로 유지해요" : id === best ? "조건과 위험 요인을 함께 확인해요" : "비교 후보의 장단점을 살펴봐요"}</small></article>)}</div><section className="result-warning"><strong>조심할 점 · 실패한 실행을 놓칠 수 있어요</strong><p>“실패한 실행은 없습니다”라고 답했지만, 실제로는 실패한 실행이 있었어요. {after.name} 후보의 틀린 단정은 {after.assertions}번입니다.</p></section>{detail && <ResultDetails comparison={comparison} />}<div className="page-actions"><Button variant="outline" onClick={onRange}>흔들리는 범위 보기 <CircleHelp size={15} /></Button><Button onClick={onSummary}>한 장 요약 만들기 <ArrowRight size={16} /></Button></div><p className="prototype-note">예시 비교 데이터 · 하루 {comparison.dailyCalls.toLocaleString("ko-KR")}회 사용 가정 · 실제 연결이나 결제는 발생하지 않아요.</p></>;
}

function Summary({ comparison, onBack, onNew, onShare }: { comparison: DemoComparison; onBack: () => void; onNew: () => void; onShare: () => void }) {
  const best = bestCandidate(comparison.candidates), after = candidates[best];
  return <div className="summary-layout"><article className="summary-paper"><p className="small">SlotAgent / 교체 판단 요약</p><h1 tabIndex={-1}>{comparison.agent.name}</h1><p className="lead">GitHub 연결 · 26개에서 {after.size}개로</p><section className="summary-callout"><small>{verdictFor(comparison)}</small><h2>{titleFor(comparison)}</h2></section><h3>성능과 비용을 함께 살펴봐요</h3><dl>{[["정답률", `${percent("B")} → ${percent(best)}`], ["한 달 예상 비용", `${won(candidates.B.perRun * comparison.dailyCalls * 30)} → ${won(after.perRun * comparison.dailyCalls * 30)}`], ["답변 시간", `${candidates.B.seconds}초 → ${after.seconds}초`]].map(([k, v]) => <div key={k} className="contents"><dt>{k}</dt><dd>{v}</dd></div>)}</dl><SummaryEvidence comparison={comparison} /><hr /><h3>바꾸기 전에 확인해 주세요</h3><p>틀린 단정이 {after.assertions}번 남았어요.<br />실패 상태를 알리는 답변은 사람이 확인해 주세요.</p><p className="prototype-note">46문항 × 2회 · 후보당 92회 · 하루 {comparison.dailyCalls.toLocaleString("ko-KR")}회 사용 가정</p><p className="prototype-note">채점 검증 전 · 예시 데이터 · 실제 설정을 변경하지 않았어요</p><p className="prototype-note">{comparison.date}</p></article><aside className="summary-side"><section className="card share-card"><h2>판단의 이유까지, 한 장으로</h2><p className="lead">회의에서 바로 이야기할 수 있게 정리했어요.<br />조심할 점을 함께 전달해 주세요.</p><p className="small muted">공유 범위</p><div className="scope">현재 브라우저에서만 볼 수 있어요</div><div className="share-actions"><Button onClick={onShare}>공유 링크 만들기</Button><Button variant="outline" onClick={() => window.print()}><FileText size={16} /> PDF로 저장하기</Button></div><p className="note mt-6">공유 링크 발급은 준비 중이에요. PDF는 브라우저 인쇄로 저장해요.</p></section><div className="share-actions"><Button variant="outline" onClick={onBack}>결과로 돌아가기</Button><Button variant="outline" onClick={onNew}>새 비교 시작하기</Button></div></aside></div>;
}

