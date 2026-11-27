"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type { StatusResponse } from "@/types/contracts";
import { getStatus, runExperiment, stopExperiment } from "../api";

const LABELS = { pending: "대기", running: "실행 중", finished: "끝남", error: "오류", cancelled: "취소" } as const;
const ACTIVE = new Set(["locked", "running"]);

// 실제 실험 진행 화면. 시작(run)은 같은 요청을 두 번 보내도 한 번만 잠기므로 화면을 다시 열어도 안전합니다.
export function LiveRun({ experimentId, onBack }: { experimentId: number; onBack: () => void }) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await getStatus(experimentId);
        if (!alive) return;
        setStatus(next); setError("");
        if (ACTIVE.has(next.status)) timer = window.setTimeout(poll, 2000);
      } catch (e) {
        if (alive) { setError((e as Error).message); timer = window.setTimeout(poll, 5000); }
      }
    };
    runExperiment(experimentId).catch((e) => alive && setError((e as Error).message)).finally(poll);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [experimentId]);

  async function stop() {
    try { setStatus(await stopExperiment(experimentId)); } catch (e) { setError((e as Error).message); }
  }

  const done = status ? status.trials.finished + status.trials.error + status.trials.cancelled : 0;
  const percent = status?.trials_total ? Math.round((done / status.trials_total) * 100) : 0;
  return <>
    <div className="screen-title"><h1 tabIndex={-1}>실험 #{experimentId} 진행 상황</h1><p className="muted">실제 API 에서 2초마다 상태를 읽어요.</p></div>
    {error && <p className="result-warning" role="alert">{error}</p>}
    <div className="run-layout">
      <section className="card">
        <div className="run-candidate">
          <div className="row"><b>풀이 {done} / {status?.trials_total ?? "-"}</b><small>상태: {status?.status ?? "불러오는 중"}{status?.stop_reason ? ` (${status.stop_reason})` : ""}</small></div>
          <div className="meter" role="progressbar" aria-label="풀이 진행률" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${percent}%` }} /></div>
        </div>
        {status && <dl className="friendly-facts">{Object.entries(LABELS).map(([key, label]) => <div key={key} style={{ display: "contents" }}><dt>{label}</dt><dd>{status.trials[key as keyof typeof LABELS]}</dd></div>)}</dl>}
      </section>
      <aside className="run-side">
        <div className="run-stat"><p>기록된 비용</p><strong>{status ? `${status.cost_krw.toLocaleString("ko-KR")}원` : "-"}</strong><small>{status?.budget_krw != null ? `예산 ${status.budget_krw.toLocaleString("ko-KR")}원` : "예산 없음"}</small></div>
        <div className="run-stat"><p>채점 · 분석</p><strong>{status?.latest_grading_run_id ? "채점 시작" : "대기"}</strong><small>{status?.latest_analysis_id ? `분석 #${status.latest_analysis_id}` : "분석 결과 없음"}</small></div>
      </aside>
    </div>
    <div className="page-actions"><Button variant="outline" onClick={onBack}>설정으로</Button><Button variant="outline" onClick={stop} disabled={!status || !ACTIVE.has(status.status)}>실험 멈추기</Button></div>
  </>;
}
