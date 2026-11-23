import type { DemoAgent, DemoComparison } from "@/features/slotagent/mocks/demo";
export type SavedDemo = { agents: DemoAgent[]; history: DemoComparison[]; dailyCalls: number; theme: "light" | "dark" };
const key = "slotagent-ui-v1";
export function readDemo(): SavedDemo | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    if (!value || !Array.isArray(value.agents) || !Array.isArray(value.history)) return null;
    const validOptions = (a: DemoAgent) => (a.prompt === undefined || typeof a.prompt === "string") && (a.provider === undefined || typeof a.provider === "string") && (a.temperature === undefined || (typeof a.temperature === "number" && Number.isFinite(a.temperature) && a.temperature >= 0 && a.temperature <= 2)) && (a.toolAccess === undefined || (Array.isArray(a.toolAccess) && a.toolAccess.every((t) => t && typeof t.name === "string" && ["read", "write", "unknown"].includes(t.access)))) && (a.writeMode === undefined || ["mock", "exclude", "runner"].includes(a.writeMode));
    const validAgent = (a: DemoAgent) => a && typeof a.id === "string" && typeof a.name === "string" && typeof a.job === "string" && typeof a.model === "string" && Array.isArray(a.tools) && a.tools.every((t) => typeof t === "string") && ["example", "api", "file", "runner"].includes(a.method) && ["example", "configured", "pending"].includes(a.discovery) && validOptions(a);
    if (!value.agents.every(validAgent) || !value.history.every((h: DemoComparison) => h && typeof h.id === "string" && validAgent(h.agent) && Array.isArray(h.candidates) && h.candidates.length > 0 && h.candidates.every((c) => c === "C" || c === "A") && Array.isArray(h.targets) && typeof h.preference === "string" && typeof h.date === "string" && Number.isInteger(h.dailyCalls) && h.dailyCalls > 0 && (h.design === undefined || (h.design && Number.isInteger(h.design.tasks) && h.design.tasks >= 1 && h.design.tasks <= 200 && Number.isInteger(h.design.repeats) && h.design.repeats >= 1 && h.design.repeats <= 5 && Number.isFinite(h.design.budget) && h.design.budget >= 1 && h.design.budget <= 1000000)))) return null;
    return { agents: value.agents, history: value.history, dailyCalls: Number.isInteger(value.dailyCalls) && value.dailyCalls > 0 && value.dailyCalls <= 100000 ? value.dailyCalls : 300, theme: value.theme === "dark" ? "dark" : "light" };
  } catch { return null; }
}
export function saveDemo(value: SavedDemo): boolean {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}
