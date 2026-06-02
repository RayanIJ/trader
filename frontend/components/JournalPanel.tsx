"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DailySummary, JournalEntry } from "@/lib/types";

const KIND_STYLE: Record<string, string> = {
  ENTRY: "text-ok",
  EXIT: "text-gray-200",
  ORDER: "text-gray-300",
  SCAN: "text-gray-400",
  SIGNAL: "text-ok",
  REJECT: "text-degraded",
  LOCKOUT: "text-down",
  MODE: "text-gray-400",
  BACKTEST: "text-gray-300",
};

function formatTs(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}

export function JournalPanel({ liveEntry }: { liveEntry?: JournalEntry | null }) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [j, s] = await Promise.all([api.journal(), api.journalSummary()]);
      setEntries(j.entries);
      setSummary(s.summary);
    } catch {
      /* backend may be starting */
    } finally {
      setLoading(false);
    }
  }, []);

  const buildSummary = useCallback(async () => {
    try {
      const res = await api.buildJournalSummary();
      setSummary(res.summary);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 60000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!liveEntry) return;
    setEntries((prev) => {
      if (prev.some((e) => e.id === liveEntry.id)) return prev;
      return [liveEntry, ...prev].slice(0, 50);
    });
  }, [liveEntry]);

  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4 md:col-span-2">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
          Journal
        </h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={refresh}
            className="rounded border border-panelborder px-2 py-0.5 text-[11px] text-gray-400 hover:text-gray-200"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={buildSummary}
            className="rounded border border-panelborder px-2 py-0.5 text-[11px] text-gray-400 hover:text-gray-200"
          >
            EOD summary
          </button>
        </div>
      </div>

      {summary && (
        <div className="mb-3 grid grid-cols-2 gap-2 rounded border border-panelborder/60 bg-black/20 p-2 text-xs md:grid-cols-4">
          <div>
            <div className="text-[10px] uppercase text-gray-500">Date</div>
            <div className="text-gray-200">{summary.trade_date}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-gray-500">Realized P/L</div>
            <div className={summary.realized_pnl >= 0 ? "text-ok" : "text-down"}>
              ${summary.realized_pnl.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-gray-500">Trades</div>
            <div className="text-gray-200">{summary.trades}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase text-gray-500">Rejected</div>
            <div className="text-gray-200">{summary.rejected}</div>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-sm text-gray-500">No journal entries yet.</p>
      ) : (
        <ul className="max-h-48 space-y-1 overflow-y-auto text-xs">
          {entries.slice(0, 20).map((e) => (
            <li
              key={e.id}
              className="flex items-start gap-2 border-b border-panelborder/40 pb-1"
            >
              <span className="shrink-0 font-mono text-[10px] text-gray-500">
                {formatTs(e.ts)}
              </span>
              <span
                className={`shrink-0 font-semibold uppercase ${
                  KIND_STYLE[e.kind] ?? "text-gray-400"
                }`}
              >
                {e.kind}
              </span>
              {e.symbol && (
                <span className="shrink-0 text-gray-400">{e.symbol}</span>
              )}
              <span className="truncate text-gray-500">
                {e.kind === "EXIT" && e.payload.realized_pnl != null
                  ? `pnl $${Number(e.payload.realized_pnl).toFixed(2)}`
                  : e.kind === "REJECT"
                    ? (e.payload.reject_codes as string[] | undefined)?.join(", ")
                    : e.kind === "SCAN"
                      ? `${e.payload.approved}/${e.payload.candidates} approved`
                      : e.payload.reason
                        ? String(e.payload.reason)
                        : e.mode}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
