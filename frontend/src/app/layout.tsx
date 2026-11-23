import type { Metadata } from "next";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "SlotAgent · 도구를 바꾸기 전, 먼저 시험해 봐요",
  description: "같은 문제로 에이전트 도구를 비교하고, 팀에 더 나은 선택을 확인하세요.",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ko" data-theme="light"><body>{children}</body></html>;
}
