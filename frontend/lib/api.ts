import type {
  ChartContextStatus,
  DailySummary,
  ExecutionSnapshot,
  HealthResponse,
  JournalEntry,
  LLMGuidanceSnapshot,
  MacroCalendarDay,
  MacroReleaseUpdate,
  ModeState,
  RiskStatusResponse,
  ScanResult,
  TradingMode,
} from "./types";

// Empty NEXT_PUBLIC_BACKEND_URL => same-origin /api (Docker proxy via next.config rewrites).
const configured = process.env.NEXT_PUBLIC_BACKEND_URL;
const BASE =
  configured === undefined ? "http://127.0.0.1:8000" : configured;
export const apiBase =
  BASE || (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8000");

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${path}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  base: apiBase,
  health: () => req<HealthResponse>("/api/health"),
  ibkrConnect: () => req("/api/ibkr/connect", { method: "POST" }),
  ibkrDisconnect: () => req("/api/ibkr/disconnect", { method: "POST" }),
  getMode: () => req<ModeState>("/api/mode"),
  switchMode: (mode: TradingMode, confirm_live = false) =>
    req<{ ok: boolean; mode: TradingMode; reason: string | null }>(
      "/api/mode/switch",
      { method: "POST", body: JSON.stringify({ mode, confirm_live }) }
    ),
  emergencyStop: () => req("/api/mode/emergency-stop", { method: "POST" }),
  clearLockout: () => req("/api/mode/clear-lockout", { method: "POST" }),
  scanner: () => req<ScanResult>("/api/scanner"),
  scanNow: () => req<ScanResult>("/api/scanner/scan", { method: "POST" }),
  riskStatus: () => req<RiskStatusResponse>("/api/risk/status"),
  macroStatus: () => req<RiskStatusResponse["macro"]>("/api/macro/status"),
  executionStatus: () => req<ExecutionSnapshot & { automation_enabled: boolean }>("/api/execution/status"),
  setAutomation: (enabled: boolean) =>
    req<{ ok: boolean; enabled: boolean }>("/api/execution/automation", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  journal: (limit = 50) =>
    req<{ entries: JournalEntry[] }>(`/api/journal?limit=${limit}`),
  journalSummary: (tradeDate?: string) =>
    req<{ summary: DailySummary | null; trade_date?: string }>(
      tradeDate ? `/api/journal/summary?trade_date=${tradeDate}` : "/api/journal/summary"
    ),
  buildJournalSummary: (tradeDate?: string) =>
    req<{ summary: DailySummary }>(
      tradeDate
        ? `/api/journal/summary/build?trade_date=${tradeDate}`
        : "/api/journal/summary/build",
      { method: "POST" }
    ),
  runBacktest: (seed = 1337, steps = 12) =>
    req("/api/backtest/run", {
      method: "POST",
      body: JSON.stringify({ seed, steps }),
    }),
  // --- LLM Guidance ---
  llmGuidance: () => req<LLMGuidanceSnapshot>("/api/llm/guidance"),
  chartContextStatus: () => req<ChartContextStatus>("/api/llm/chart-context"),
  forceLLMGuidance: () => req("/api/llm/guidance/force", { method: "POST" }),
  // --- Macro Calendar ---
  macroCalendar: () => req<MacroCalendarDay>("/api/macro/calendar"),
  macroReleases: () => req<{ updates: MacroReleaseUpdate[] }>("/api/macro/releases"),
  macroNextEvent: () => req("/api/macro/next-event"),
  macroRefreshCalendar: () => req("/api/macro/calendar/refresh", { method: "POST" }),
};
