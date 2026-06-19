"use client";

import type { ChartContextStatus } from "@/lib/types";

function freshnessColor(valid: boolean | null, barCount: number): string {
  if (valid === null || barCount === 0) return "bg-gray-600";
  return valid ? "bg-ok" : "bg-red-500";
}

function compressionLabel(method: string | null): string {
  if (!method || method === "full") return "Full";
  if (method === "tiered_90m") return "90min+5min";
  if (method === "pivots_only") return "Pivots Only";
  return method;
}

export function ChartContextPanel({
  context,
}: {
  context: ChartContextStatus | null;
}) {
  if (!context || !context.enabled) {
    return (
      <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
        <h2 className="text-sm font-bold text-gray-200 uppercase tracking-wider mb-3">
          Chart Context
        </h2>
        <p className="text-xs text-gray-600 italic">LLM guidance not enabled</p>
      </div>
    );
  }

  const summary = context.session_summary as Record<string, unknown> | undefined;
  const lastBarET = summary?.last_completed_bar_time_et as string | undefined;
  const lastBarGMT3 = summary?.last_completed_bar_time_gmt3 as string | undefined;

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-bold text-gray-200 uppercase tracking-wider">
          Chart Context
        </h2>
        <span className="flex items-center gap-1.5">
          <span
            className={`inline-block h-2 w-2 rounded-full ${freshnessColor(
              context.chart_valid,
              context.bar_count
            )}`}
          />
          <span className="text-[10px] text-gray-400 uppercase font-semibold">
            {context.chart_valid ? "Valid" : "Stale"}
          </span>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div>
          <span className="text-gray-500">Bars sent</span>
          <span className="ml-2 font-mono text-gray-200">{context.bar_count}</span>
        </div>
        <div>
          <span className="text-gray-500">Compression</span>
          <span className="ml-2">
            <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${
              context.compression_method === "full"
                ? "bg-green-500/15 text-green-400"
                : "bg-yellow-500/15 text-yellow-400"
            }`}>
              {compressionLabel(context.compression_method)}
            </span>
          </span>
        </div>
        {lastBarGMT3 && (
          <div className="col-span-2">
            <span className="text-gray-500">Last bar</span>
            <span className="ml-2 font-mono text-gray-300 text-[11px]">
              {lastBarGMT3 ? new Date(lastBarGMT3).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true }) : "—"}
              <span className="text-gray-600 ml-1">GMT+3</span>
            </span>
            {lastBarET && (
              <span className="ml-2 font-mono text-gray-500 text-[11px]">
                {new Date(lastBarET).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true })}
                <span className="text-gray-600 ml-1">ET</span>
              </span>
            )}
          </div>
        )}
      </div>

      {context.chart_issues && context.chart_issues.length > 0 && (
        <div className="mt-2 space-y-1">
          {context.chart_issues.map((issue, i) => (
            <div key={i} className="text-[10px] text-yellow-500/80 flex items-start gap-1">
              <span className="shrink-0">⚠</span>
              <span>{issue}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
