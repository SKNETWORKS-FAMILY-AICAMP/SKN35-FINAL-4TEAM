import { useState } from "react";
import { Button } from "@/components/ui/button";
import { candidates, percent, type CandidateId, type DemoComparison } from "../mocks/demo";
import { detailMetrics, taskTypes } from "../mocks/result-detail";

export function EvaluationContext({ comparison }: { comparison: DemoComparison }) {
  const changed = comparison.design && (comparison.design.tasks !== 46 || comparison.design.repeats !== 2);
  return <div className="howto result-context"><b>기존 기록으로 결과 화면을 보고 있어요</b><p>아래 수치는 11개 유형·46문항·2회 반복의 기존 예시 기록이에요. 선택한 에이전트를 새로 측정한 결과가 아니에요.</p>{changed && <p>저장한 시험 계획은 {comparison.design!.tasks}문제 × {comparison.design!.repeats}번이에요. 실제 측정값은 평가 기능을 연결한 뒤 확인할 수 있어요.</p>}</div>;
}

export function ResultDetails({ comparison }: { comparison: DemoComparison }) {
  const [traceOpen, setTraceOpen] = useState(false);
  const ids: CandidateId[] = ["B", ...comparison.candidates];
  return <div className="result-details">
    <section className="card"><h2>숫자를 조금 더 자세히 볼까요?</h2><p className="small muted">기존 예시의 수치예요. 기록이 없는 항목은 추측하지 않고 ‘측정 전’으로 표시해요.</p><div className="tw"><table className="metrics-table"><caption className="sr-only">후보별 상세 비교</caption><thead><tr><th>무엇을 볼까요?</th>{ids.map((id) => <th key={id}>{candidates[id].name}</th>)}</tr></thead><tbody>
      <tr><th>올바르게 답한 비율</th>{ids.map((id) => <td key={id}>{percent(id)} ({candidates[id].correct}/92회)</td>)}</tr>
      <tr><th>성공 1건당 비용</th>{ids.map((id) => <td key={id}>{(candidates[id].perRun * 92 / candidates[id].correct).toFixed(2)}원</td>)}</tr>
      <tr><th>느린 편에 속하는 답변 시간 <small>p90</small></th>{ids.map((id) => <td key={id}>{detailMetrics[id].p90}초</td>)}</tr>
      <tr><th>2번 모두 성공한 문제 <small>pass²</small></th>{ids.map((id) => <td key={id}>{detailMetrics[id].passAll}/46문제</td>)}</tr>
      <tr><th>이전에는 맞혔는데 틀린 문제</th>{ids.map((id) => <td key={id}>{id === "B" ? "비교 기준" : `${detailMetrics[id].regressions}/37문제`}</td>)}</tr>
      <tr><th>필요한 도구가 없어 못 푸는 비율</th>{ids.map((id) => <td key={id}>{(detailMetrics[id].outOfScope / 92 * 100).toFixed(1)}%</td>)}</tr>
      <tr><th>중단 없이 끝까지 실행한 비율</th>{ids.map((id) => <td key={id}>기록 연결 전</td>)}</tr>
    </tbody></table></div><p className="note">p90은 10번 중 9번이 이 시간 안에 답한다는 뜻이에요. 이전에는 맞혔는데 틀린 문제는 기준 구성이 2번 모두 성공한 37문제 중 새 후보가 한 번 이상 틀린 문제예요.</p><p className="note">도구가 없어 못 푸는 문제도 전체 성공률에서는 실패로 포함해요. 두 후보가 공통으로 풀 수 있는 문제만의 성공률은 문항별 원본 기록을 연결한 뒤 계산해요.</p></section>

    <section className="card"><h2>어떤 종류의 문제에서 차이가 났나요?</h2><p className="small muted">문제 유형별 성공 횟수예요. 괄호는 지금 쓰는 구성보다 몇 번 더 맞혔거나 틀렸는지 보여줘요.</p><div className="tw"><table className="metrics-table"><thead><tr><th>문제 유형</th>{ids.map((id) => <th key={id}>{candidates[id].name}</th>)}</tr></thead><tbody>{taskTypes.map((task) => <tr key={task.name}><th>{task.name}</th>{ids.map((id) => <td key={id}>{task[id]}/{task.total}회 {id !== "B" && <small className={task[id] >= task.B ? "metric-positive" : "metric-negative"}>({task[id] - task.B > 0 ? "+" : ""}{task[id] - task.B})</small>}</td>)}</tr>)}</tbody></table></div><p className="note">아직 문항·회차별 원본 기록은 연결되지 않았어요. 이 표만으로 특정 문항에서 승패가 뒤집혔다고 단정할 수는 없어요.</p></section>

    <section className="card"><h2>처음 어디에서 막혔나요?</h2><div className="grid g3 mt-4">{ids.map((id) => <article className="breakdown-card" key={id}><h3>{candidates[id].name}</h3>{detailMetrics[id].failures.map(([name, count]) => <div className="breakdown-row" key={name}><span>{name}</span><b>{count}회</b></div>)}</article>)}</div></section>

    <section className="card"><h2>어떤 도구에 시간과 비용이 들었나요?</h2><p className="muted small">현재 예시에는 도구별 측정 기록이 없어요. 실제 기록이 연결되면 모델·도구·기다린 시간을 나누어 보여드려요.</p><div className="tw"><table className="metrics-table"><thead><tr><th>측정 항목</th><th>시간</th><th>비용</th></tr></thead><tbody>{["모델의 답변 생성", "GitHub 도구", "대기 시간"].map((name) => <tr key={name}><td>{name}</td><td>측정 전</td><td>측정 전</td></tr>)}</tbody></table></div></section>

    <section className="card"><h2>무슨 일이 있었는지 순서대로 보기</h2><p className="small muted">이해를 돕는 설명용 실패 예시예요. 위 집계 수치를 뒷받침하는 실제 실행 기록은 아니에요.</p><Button variant="outline" className="mt-4" aria-expanded={traceOpen} onClick={() => setTraceOpen(!traceOpen)}>{traceOpen ? "기록 닫기" : "실패 설명 예시 열기"}</Button>{traceOpen && <div className="trace-preview"><h3>이슈 #142를 고친 PR이 처음 포함된 배포 버전은?</h3><ol><li><b>1. 배포 목록을 확인해요</b><p>list_releases → v1.8.3에 PR #214가 들어간 것을 확인했어요.</p></li><li><b>2. 이슈와 PR의 관계를 확인하지 않았어요</b><p>PR #214가 이슈 #142를 고친 것인지는 도구 결과에서 확인하지 못했어요.</p></li><li><b>3. 관계를 확인하지 않고 답했어요</b><p>숫자가 같아도 필요한 관계의 근거가 없으면 성공으로 인정하지 않아요.</p></li></ol></div>}</section>

    <section className="card"><h2>이 결과는 어디까지 믿고 볼 수 있나요?</h2><dl className="friendly-facts"><dt>결과 종류</dt><dd>화면 확인용 기존 예시</dd><dt>실행 환경·관측 정보</dt><dd>실제 연결을 검증하지 않았어요</dd><dt>기록 출처</dt><dd>공유 데모의 집계값 · 실제 측정 검증 전</dd><dt>판정 유의사항</dt><dd>예시 판정이에요. 선택한 에이전트에 대한 실제 변경 권고가 아니에요</dd></dl></section>
  </div>;
}

export function SummaryEvidence({ comparison }: { comparison: DemoComparison }) {
  const includesC = comparison.candidates.includes("C");
  return <><h3>판정의 근거와 평가 조건</h3><dl className="friendly-facts"><dt>예시 성공률 차이</dt><dd>{includesC ? "+16.3%p" : "−4.3%p"}</dd><dt>차이가 흔들리는 범위</dt><dd>{includesC ? comparison.candidates.length > 1 ? "−1.2 ~ +40.2%p" : "0.0 ~ +37.0%p" : "−23.3 ~ +12.5%p"}</dd><dt>평가 데이터</dt><dd>IT 운영 기존 예시 · 11개 유형, 46문항, 2회 반복</dd><dt>사용한 구성</dt><dd>원본 데모의 GPT 계열 모델·GitHub 후보. 정확한 모델·데이터 버전은 연결 전</dd></dl><p className="note">표시된 에이전트를 새로 측정한 결과가 아니에요. 범위는 공유 데모에 있는 값이며, 이번에 다시 계산한 신뢰구간은 아니에요.</p>{comparison.design && <p className="note">저장한 계획: {comparison.design.tasks}문제 × {comparison.design.repeats}번 · 최대 {comparison.design.budget.toLocaleString("ko-KR")}원</p>}</>;
}
