import type { CandidateId } from "./demo";

// Values transcribed from the shared HTML's CAND, TPLS and PAIR fixtures.
// Counts describe the existing 46-task / 92-trial example, never a new run.
export const detailMetrics: Record<CandidateId, { p90: number; passAll: number; regressions: number; outOfScope: number; failures: [string, number][] }> = {
  B: { p90: 2.7, passAll: 37, regressions: 0, outOfScope: 0, failures: [["도구 실행 오류", 8], ["도구에 전달한 값 오류", 7], ["마지막 답변 작성 오류", 1]] },
  C: { p90: 2.8, passAll: 45, regressions: 1, outOfScope: 0, failures: [["마지막 답변 작성 오류", 1]] },
  A: { p90: 2.0, passAll: 36, regressions: 5, outOfScope: 18, failures: [["필요한 도구가 없음", 18], ["도구에 전달한 값 오류", 2]] },
};
export const taskTypes: { name: string; total: number; A: number; B: number; C: number }[] = [
  { name: "날짜별 실패한 실행 찾기", total: 12, A: 4, B: 8, C: 12 },
  { name: "최근 실행 결과", total: 8, A: 2, B: 7, C: 8 },
  { name: "실행 번호로 실패 단계 찾기", total: 8, A: 2, B: 0, C: 8 },
  { name: "담당자로 이슈 찾기", total: 8, A: 8, B: 8, C: 8 },
  { name: "작성자로 PR 찾기", total: 8, A: 8, B: 8, C: 7 },
  { name: "봇이 만든 PR", total: 8, A: 8, B: 5, C: 8 },
  { name: "담당자 없는 이슈", total: 6, A: 6, B: 6, C: 6 },
  { name: "라벨로 PR 찾기", total: 10, A: 10, B: 10, C: 10 },
  { name: "릴리스 시각", total: 8, A: 8, B: 8, C: 8 },
  { name: "릴리스 커밋", total: 8, A: 8, B: 8, C: 8 },
  { name: "PR 제목", total: 8, A: 8, B: 8, C: 8 },
];
