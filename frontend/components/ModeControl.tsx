"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ModeState, TradingMode } from "@/lib/types";

const MODE_STYLES: Record<TradingMode, string> = {
  SHADOW: "bg-gray-700 text-gray-100",
  PAPER: "bg-blue-600 text-white",
  LIVE: "bg-live text-white animate-pulse",
};

export function ModeControl({
  mode,
  onChanged,
}: {
  mode: ModeState | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const current = mode?.mode ?? "SHADOW";

  async function switchTo(target: TradingMode) {
    setBusy(true);
    setMsg(null);
    try {
      let confirmLive = false;
      if (target === "LIVE") {
        confirmLive = window.confirm(
          "⚠ ENABLE LIVE TRADING?\n\nReal orders will be sent to your LIVE IBKR account. " +
            "This requires a healthy, tradable broker session and passes all pre-trade gates. Proceed?"
        );
        if (!confirmLive) {
          setBusy(false);
          return;
        }
      }
      const res = await api.switchMode(target, confirmLive);
      if (!res.ok) setMsg(res.reason ?? "switch blocked");
      onChanged();
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-300">
        Trading Mode
      </h2>

      <div className="mb-3 flex items-center gap-3">
        <span
          className={`rounded px-3 py-1 text-sm font-bold ${MODE_STYLES[current]}`}
        >
          {current}
        </span>
        {current === "LIVE" && (
          <span className="text-xs font-semibold text-live">
            ● LIVE — REAL MONEY
          </span>
        )}
        {mode?.locked_out && (
          <span className="text-xs font-semibold text-down">
            LOCKED OUT: {mode.lockout_reason}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {(["SHADOW", "PAPER", "LIVE"] as TradingMode[]).map((m) => (
          <button
            key={m}
            disabled={busy || current === m}
            onClick={() => switchTo(m)}
            className={`rounded border px-3 py-1.5 text-sm transition ${
              current === m
                ? "border-panelborder bg-gray-800 text-gray-500"
                : m === "LIVE"
                ? "border-live/60 text-live hover:bg-live/10"
                : "border-panelborder text-gray-200 hover:bg-gray-800"
            }`}
          >
            {m}
          </button>
        ))}
        {mode?.locked_out && (
          <button
            disabled={busy}
            onClick={async () => {
              await api.clearLockout();
              onChanged();
            }}
            className="rounded border border-degraded/60 px-3 py-1.5 text-sm text-degraded hover:bg-degraded/10"
          >
            Clear Lockout
          </button>
        )}
      </div>

      <p className="mt-3 text-xs text-gray-500">
        Default is Shadow (signals only, no orders). Live requires explicit
        confirmation and a passing pre-trade health check.
      </p>
      {msg && <p className="mt-2 text-xs text-degraded">{msg}</p>}
    </section>
  );
}
