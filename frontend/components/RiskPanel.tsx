"use client";

import type { RiskStatusResponse } from "@/lib/types";

const BEHAVIOR_STYLE = {
  CONTROLLED: "text-ok",
  CAUTION: "text-degraded",
  RED: "text-down",
} as const;

export function RiskPanel({ risk }: { risk: RiskStatusResponse | null }) {
  if (!risk) {
    return (
      <section className="rounded-lg border border-panelborder bg-panel p-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-400">
          Risk
        </h2>
        <p className="text-sm text-gray-500">Loading…</p>
      </section>
    );
  }

  const { day, behavior, macro } = risk;
  const behaviorClass = BEHAVIOR_STYLE[behavior.state];

  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">
        Risk &amp; Macro
      </h2>
      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <div className="text-[11px] uppercase text-gray-500">Daily P/L</div>
          <div className={day.total_pnl >= 0 ? "text-ok" : "text-down"}>
            ${day.total_pnl.toFixed(2)}
            <span className="ml-2 text-gray-500">
              (remaining ${day.remaining_loss_allowance.toFixed(0)})
            </span>
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase text-gray-500">Behavior</div>
          <div className={`font-semibold ${behaviorClass}`}>{behavior.state}</div>
          {behavior.reasons.length > 0 && (
            <div className="text-[11px] text-gray-500">{behavior.reasons.join(" · ")}</div>
          )}
        </div>
        <div>
          <div className="text-[11px] uppercase text-gray-500">Exposure</div>
          <div className="text-gray-200">
            ${day.open_premium_exposure.toFixed(0)} open · {day.trades_today} trades
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase text-gray-500">Macro</div>
          {macro.blocked ? (
            <div className="text-down">{macro.reason ?? "Blocked"}</div>
          ) : macro.next_event ? (
            <div className="text-gray-300">
              Next: {macro.next_event}
              {macro.minutes_to_next != null && (
                <span className="text-gray-500"> in {macro.minutes_to_next}m</span>
              )}
            </div>
          ) : (
            <div className="text-gray-500">No events scheduled</div>
          )}
        </div>
      </div>
      {day.lockout && (
        <div className="mt-3 rounded border border-down/40 bg-down/10 px-3 py-2 text-sm text-down">
          Daily lockout: {day.lockout_reason ?? "active"}
        </div>
      )}
    </section>
  );
}
