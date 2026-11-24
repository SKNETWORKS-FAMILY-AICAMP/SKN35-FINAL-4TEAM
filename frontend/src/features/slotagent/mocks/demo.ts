// View-only fixtures. These are not API payloads or production measurements.
export type ToolAccess = { name: string; access: "read" | "write" | "unknown" };
export type DemoAgent = { id: string; name: string; job: string; model: string; method: "example" | "api" | "file" | "runner"; tools: string[]; discovery: "example" | "configured" | "pending"; prompt?: string; provider?: string; temperature?: number; toolAccess?: ToolAccess[]; writeMode?: "mock" | "exclude" | "runner"; connectionUrl?: string; dryRun?: boolean };
export type TrialDesign = { tasks: number; repeats: number; budget: number };
export const defaultDesign: TrialDesign = { tasks: 46, repeats: 2, budget: 1000 };
export type CandidateId = "B" | "C" | "A";
export type DemoComparison = { id: string; agent: DemoAgent; candidates: CandidateId[]; preference: string; targets: string[]; date: string; dailyCalls: number; design?: TrialDesign };
export const sampleAgent: DemoAgent = { id: "sample", name: "우리 팀 GitHub 도우미", job: "배포 상태와 이슈, PR을 찾아 팀에 알려줘요.", model: "GPT-4.1 mini", method: "example", tools: ["GitHub", "Slack"], discovery: "example", prompt: "도구로 확인한 사실만 답해 주세요. 메시지를 보내기 전에는 사용자에게 확인해 주세요.", provider: "GPT", temperature: 0, toolAccess: [{ name: "GitHub", access: "read" }, { name: "Slack", access: "write" }], writeMode: "mock" };
export const candidates = {
  B: { name: "지금 쓰는 도구", size: 26, description: "현재 설정 그대로, 비교의 기준이 돼요.", correct: 76, total: 92, perRun: 2.15, seconds: 1.9, assertions: 16, label: "비교 기준" },
  C: { name: "필요한 것만", size: 8, description: "자주 쓰는 도구만 남겨 헷갈림을 줄여요.", correct: 91, total: 92, perRun: 1.46, seconds: 1.8, assertions: 1, label: "조건부 채택" },
  A: { name: "직접 만든 도구", size: 1, description: "팀 업무에 맞게 하나로 묶었어요.", correct: 72, total: 92, perRun: 0.69, seconds: 1.7, assertions: 20, label: "판단 보류" },
} satisfies Record<CandidateId, { name: string; size: number; description: string; correct: number; total: number; perRun: number; seconds: number; assertions: number; label: string }>;
export const steps = ["에이전트", "바꿔 볼 자리", "시험 정하기", "시험", "결과", "한 장 요약"];
export const percent = (id: CandidateId) => `${(candidates[id].correct / candidates[id].total * 100).toFixed(1)}%`;
export const won = (n: number) => `${Math.round(n).toLocaleString("ko-KR")}원`;
export function bestCandidate(ids: CandidateId[]): CandidateId { return ids.includes("C") ? "C" : "A"; }
