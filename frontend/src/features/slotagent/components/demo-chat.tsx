"use client";
import { useEffect, useRef, useState } from "react";
import { Bot, Send, X } from "lucide-react";
import { candidates, bestCandidate, percent, won, type DemoComparison } from "@/features/slotagent/mocks/demo";

export function DemoChat({ comparison }: { comparison: DemoComparison | null }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([{ role: "bot", text: "안녕하세요! SlotBot이에요.\n에이전트의 도구를 바꾸면 더 나아지는지 같이 확인해 볼게요. 궁금한 내용을 골라 보세요." }]);
  const log = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) field.current?.focus(); }, [open]);
  useEffect(() => { if (log.current) log.current.scrollTop = log.current.scrollHeight; }, [messages, open]);
  function ask(question: string) {
    if (!question.trim()) return;
    let answer = "SlotBot은 예시 답변으로 이용 방법과 비교 결과를 설명해요. ‘판정’, ‘비용’, ‘안전’, ‘결과 설명’에 대해 물어봐 주세요.";
    if (/판정|채택|보류|기각/.test(question)) answer = "채택: 더 나은 성능을 확인했어요.\n조건부 채택: 성능이 크게 나빠지지 않고, 미리 정한 비용·속도 기준이 좋아졌어요.\n판단 보류: 아직 차이를 확신하기 어려워요.\n기각: 금지 행동이나 성능 저하 등 교체하기 어려운 이유가 있어요.";
    if (/안전|진짜|보내|연결/.test(question)) answer = "현재는 모의 데이터로 화면을 체험해요. 외부 API를 호출하거나 메시지를 보내지 않으며, 에이전트 설정도 바뀌지 않아요.";
    if (/도구|8개|적은/.test(question)) answer = "필요한 도구만 남기면 고를 도구와 도구 설명이 줄어요. 예시에서는 비용과 정확도가 좋아졌지만, 실제 효과는 에이전트에 맞는 문제로 다시 확인해야 해요.";
    if (/비용|얼마/.test(question)) answer = comparison ? `하루 ${comparison.dailyCalls.toLocaleString("ko-KR")}회 기준, 지금 구성은 한 달 ${won(candidates.B.perRun * comparison.dailyCalls * 30)}, 추천 후보는 ${won(candidates[bestCandidate(comparison.candidates)].perRun * comparison.dailyCalls * 30)}이에요. 예시 기록에 따른 추정이며 실제 과금은 없어요.` : "모의 비교는 실제 비용이 0원이에요. 결과의 월 예상 비용은 예시 응답 단가와 하루 사용량을 곱해 계산해요.";
    if (/결과|설명|요약/.test(question)) answer = comparison ? `예시에서 지금 구성의 정답률은 ${percent("B")}, ${candidates[bestCandidate(comparison.candidates)].name} 후보는 ${percent(bestCandidate(comparison.candidates))}예요.\n판정은 ${bestCandidate(comparison.candidates) === "C" && comparison.preference !== "none" ? "조건부 채택" : "판단 보류"}이며, 틀린 단정과 남은 위험 요인을 함께 확인해야 해요. 실제 서비스 성능을 보장하는 결과는 아니에요.` : "비교를 끝내거나 홈에서 ‘결과 예시 먼저 보기’를 누르면 결과를 설명해 드릴게요.";
    if (/흔들|범위|확실/.test(question)) answer = "흔들리는 범위는 시험 문제에 따라 성능 차이가 어느 정도 달라질 수 있는지 보여줘요. 범위가 0을 걸치면 확실히 좋아졌다고 단정하기 어려워요. 더 다양한 새 문제로 확인할 수 있어요.";
    setMessages((prev) => [...prev, { role: "user", text: question.trim() }, { role: "bot", text: answer }]); setInput("");
  }
  return <><button className="chatfab" aria-expanded={open} aria-controls="demo-chat" onClick={() => setOpen(!open)}><Bot size={20} /> SlotBot에게 묻기</button>{open && <aside id="demo-chat" className="chat open" aria-label="SlotBot 채팅" onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}><header><div><b>SlotBot</b><p className="small muted">이용 안내 · 예시 답변</p></div><button aria-label="SlotBot 닫기" onClick={() => setOpen(false)}><X size={20} /></button></header><div ref={log} className="log" role="log" aria-live="polite">{messages.map((m, i) => <div key={i} className={`m ${m.role === "user" ? "u" : "b"}`}>{m.text}</div>)}<div className="qr">{["판정 4가지가 뭐야?", "진짜로 메시지가 가?", "결과 쉽게 설명해 줘"].map((q) => <button key={q} onClick={() => ask(q)}>{q}</button>)}</div></div><form className="cin" onSubmit={(e) => { e.preventDefault(); ask(input); }}><label className="sr-only" htmlFor="chat-question">SlotBot에게 질문</label><input ref={field} id="chat-question" value={input} maxLength={500} onChange={(e) => setInput(e.target.value)} placeholder="궁금한 점을 물어보세요" /><button aria-label="질문 보내기" disabled={!input.trim()}><Send size={17} /></button></form></aside>}</>;
}


