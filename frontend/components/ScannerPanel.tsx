"use client";

import { useState } from "react";
import type { ScanCandidate, ScanResult, ScoreBand } from "@/lib/types";

const BAND_STYLE: Record<ScoreBand, string> = {
  NORMAL: "bg-ok/20 text-ok",
  REDUCED_RISK: "bg-degraded/20 text-degraded",
  WATCH: "bg-yellow-500/15 text-yellow-400",
  NO_TRADE: "bg-gray-700/40 text-gray-400",
};

function CandidateRow({ c }: { c: ScanCandidate }) {
  const [open, setOpen] = useState(false);
  const ct = c.contract;
  return (
    <>
      <tr
        className="cursor-pointer border-t border-panelborder/60 hover:bg-white/5"
        onClick={() => setOpen((v) => !v)}
      >
        <td className="py-1.5 pr-2 font-medium text-gray-200">{c.symbol}</td>
        <td className="pr-2">
          <span
            className={
              c.direction === "CALL" ? "text-ok" : "text-down"
            }
          >
            {c.direction}
          </span>
        </td>
        <td className="pr-2 text-right font-semibold text-gray-100">
          {c.score.toFixed(0)}
        </td>
        <td className="pr-2">
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
              BAND_STYLE[c.band]
            }`}
          >
            {c.band.replace("_", " ")}
          </span>
        </td>
        <td className="pr-2 text-right text-gray-400">
          {ct?.ask != null ? `$${ct.ask.toFixed(2)}` : "—"}
        </td>
        <td className="pr-2 text-right text-gray-500">
          {ct?.spread_pct != null ? `${ct.spread_pct.toFixed(1)}%` : "—"}
        </td>
        <td className="text-right">
          {c.approved ? (
            <span className="text-ok font-semibold" title="Signal + risk approved">
              GO
            </span>
          ) : c.tradable ? (
            <span className="text-degraded" title={c.reject_codes.join(", ")}>
              WATCH
            </span>
          ) : (
            <span className="text-down" title={c.reject_codes.join(", ")}>
              ✕
            </span>
          )}
        </td>
      </tr>
      {open && (
        <tr className="bg-black/20 text-[11px] text-gray-400">
          <td colSpan={7} className="px-2 py-2">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-3">
              <span>Setup: {c.signal_type.replaceAll("_", " ")}</span>
              <span>
                Price: {c.price != null ? c.price.toFixed(2) : "—"} · VWAP:{" "}
                {c.vwap != null ? c.vwap.toFixed(2) : "—"}
              </span>
              <span>
                RVol:{" "}
                {c.relative_volume != null
                  ? `${c.relative_volume.toFixed(2)}x`
                  : "—"}
              </span>
              <span>
                Chop: {c.chop_band} ({c.chop_score.toFixed(0)})
              </span>
              {ct && (
                <span>
                  Contract: {ct.strike} {ct.right}{" "}
                  {ct.has_zero_dte ? "0DTE" : ct.expiry}
                </span>
              )}
              {ct?.delta != null && <span>Δ {ct.delta.toFixed(2)}</span>}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.entries(c.score_breakdown)
                .filter(([k]) => k !== "total")
                .map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] text-gray-400"
                  >
                    {k.replaceAll("_", " ")}: {v}
                  </span>
                ))}
            </div>
            {c.reject_codes.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {c.reject_codes.map((rc) => (
                  <span
                    key={rc}
                    className="rounded bg-down/15 px-1.5 py-0.5 text-[10px] font-semibold text-down"
                  >
                    {rc}
                  </span>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function Table({
  title,
  rows,
}: {
  title: string;
  rows: ScanCandidate[];
}) {
  return (
    <div>
      <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-600">
        {title}
      </h3>
      {rows.length === 0 ? (
        <p className="text-xs text-gray-600">No candidates.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider text-gray-600">
              <th className="pb-1 pr-2 font-medium">Sym</th>
              <th className="pr-2 font-medium">Dir</th>
              <th className="pr-2 text-right font-medium">Score</th>
              <th className="pr-2 font-medium">Band</th>
              <th className="pr-2 text-right font-medium">Ask</th>
              <th className="pr-2 text-right font-medium">Spr</th>
              <th className="text-right font-medium">OK</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <CandidateRow key={`${c.symbol}-${c.direction}`} c={c} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function ScannerPanel({
  scan,
  onRescan,
}: {
  scan: ScanResult | null;
  onRescan?: () => void;
}) {
  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-300">
          Scanner
        </h2>
        <div className="flex items-center gap-3 text-[10px] text-gray-500">
          {scan && (
            <span>
              {scan.source} · {new Date(scan.asof).toLocaleTimeString()}
            </span>
          )}
          {onRescan && (
            <button
              onClick={onRescan}
              className="rounded bg-gray-800 px-2 py-0.5 text-gray-300 hover:bg-gray-700"
            >
              Rescan
            </button>
          )}
        </div>
      </div>

      {!scan ? (
        <p className="text-sm text-gray-500">Scanning…</p>
      ) : (
        <div className="space-y-4">
          <Table title="Top Calls" rows={scan.top_calls} />
          <Table title="Top Puts" rows={scan.top_puts} />
          <p className="text-[10px] text-gray-600">
            Rows expand for features, score breakdown, and reason codes. “No
            Trade” is a valid, expected outcome.
          </p>
        </div>
      )}
    </section>
  );
}
