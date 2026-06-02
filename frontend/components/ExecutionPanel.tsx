"use client";

import type { ExecutionSnapshot } from "@/lib/types";

export function ExecutionPanel({
  execution,
  onToggleAutomation,
}: {
  execution: ExecutionSnapshot | null;
  onToggleAutomation: (enabled: boolean) => void;
}) {
  if (!execution) {
    return (
      <section className="rounded-lg border border-panelborder bg-panel p-4">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-400">
          Execution
        </h2>
        <p className="text-sm text-gray-500">Loading…</p>
      </section>
    );
  }

  const last = execution.last_order;

  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">
          Execution
        </h2>
        <button
          type="button"
          onClick={() => onToggleAutomation(!execution.automation_enabled)}
          className={`rounded px-2 py-1 text-xs font-semibold ${
            execution.automation_enabled
              ? "bg-ok/20 text-ok"
              : "bg-gray-700/50 text-gray-400"
          }`}
        >
          Auto {execution.automation_enabled ? "ON" : "OFF"}
        </button>
      </div>
      <div className="space-y-2 text-sm text-gray-300">
        <div>
          Mode: <span className="text-gray-100">{execution.mode}</span>
        </div>
        {last && (
          <div>
            Last order: {last.state}
            {last.avg_fill_price != null && (
              <span className="text-gray-500"> @ ${last.avg_fill_price.toFixed(2)}</span>
            )}
          </div>
        )}
        {execution.last_exit_reason && (
          <div className="text-degraded">Last exit: {execution.last_exit_reason}</div>
        )}
        {execution.messages?.slice(-3).map((m, i) => (
          <div key={i} className="text-[11px] text-gray-500">
            {m}
          </div>
        ))}
      </div>
    </section>
  );
}
