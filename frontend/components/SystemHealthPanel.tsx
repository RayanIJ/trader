"use client";

import type { HealthReport, BrokerSnapshot } from "@/lib/types";
import { StatusDot } from "./StatusDot";

const LABELS: Record<string, string> = {
  BACKEND: "Backend",
  IB_GATEWAY: "IB Gateway",
  IB_SESSION: "IB Session (auth)",
  MARKET_DATA: "Market Data",
  ACCOUNT: "Account",
  POSITION_SYNC: "Position Sync",
  DATABASE: "Database",
  CLOCK: "System Clock",
  MACRO_CALENDAR: "Macro Calendar",
};

export function SystemHealthPanel({
  health,
  broker,
}: {
  health: HealthReport | null;
  broker: BrokerSnapshot | null;
}) {
  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-300">
          System Health
        </h2>
        {health && (
          <span className="flex items-center gap-2 text-xs text-gray-400">
            <StatusDot status={health.overall} />
            {health.overall}
          </span>
        )}
      </div>

      {!health ? (
        <p className="text-sm text-gray-500">Connecting…</p>
      ) : (
        <>
          <ul className="space-y-1.5">
            {health.components.map((c) => (
              <li
                key={c.component}
                className="flex items-center justify-between text-sm"
              >
                <span className="flex items-center gap-2 text-gray-300">
                  <StatusDot status={c.status} />
                  {LABELS[c.component] ?? c.component}
                </span>
                <span className="text-xs text-gray-500">
                  {c.detail ?? c.status}
                </span>
              </li>
            ))}
          </ul>

          <div
            className={`mt-4 rounded-md px-3 py-2 text-sm font-medium ${
              health.can_trade
                ? "bg-ok/10 text-ok"
                : "bg-down/10 text-down"
            }`}
          >
            {health.can_trade
              ? "Pre-trade gate: PASS — trading permitted"
              : "Pre-trade gate: BLOCKED — new trades disabled"}
          </div>

          {broker?.last_error && (
            <p className="mt-2 text-xs text-degraded">{broker.last_error}</p>
          )}
        </>
      )}
    </section>
  );
}
