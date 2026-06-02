"use client";

import type { Bias, MarketRegime, SymbolView } from "@/lib/types";

function biasColor(bias: Bias): string {
  if (bias === "UP") return "text-ok";
  if (bias === "DOWN") return "text-down";
  return "text-gray-500";
}

function biasArrow(bias: Bias): string {
  if (bias === "UP") return "▲";
  if (bias === "DOWN") return "▼";
  return "•";
}

function Row({ v }: { v: SymbolView }) {
  return (
    <li className="flex items-center justify-between text-sm">
      <span className="flex items-center gap-2 text-gray-300">
        <span className={`${biasColor(v.bias)} w-3 text-center`}>
          {biasArrow(v.bias)}
        </span>
        <span className="font-medium">{v.symbol}</span>
      </span>
      <span className="flex items-center gap-3 text-xs text-gray-500">
        {v.price != null && <span>{v.price.toFixed(2)}</span>}
        {v.dist_from_vwap_pct != null && (
          <span
            className={
              v.dist_from_vwap_pct >= 0 ? "text-ok/80" : "text-down/80"
            }
            title="Distance from VWAP"
          >
            {v.dist_from_vwap_pct >= 0 ? "+" : ""}
            {v.dist_from_vwap_pct.toFixed(2)}%
          </span>
        )}
        <span className="w-10 text-right text-gray-600">
          {v.momentum_score.toFixed(0)}
        </span>
      </span>
    </li>
  );
}

function Group({
  label,
  views,
}: {
  label: string;
  views: Record<string, SymbolView>;
}) {
  const items = Object.values(views ?? {});
  if (!items.length) return null;
  return (
    <div>
      <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-600">
        {label}
      </h3>
      <ul className="space-y-1">
        {items.map((v) => (
          <Row key={v.symbol} v={v} />
        ))}
      </ul>
    </div>
  );
}

const OVERALL_STYLE: Record<string, string> = {
  RISK_ON: "bg-ok/15 text-ok",
  RISK_OFF: "bg-down/15 text-down",
  MIXED: "bg-gray-700/40 text-gray-300",
};

export function MarketRegimePanel({
  regime,
}: {
  regime: MarketRegime | null;
}) {
  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-300">
          Market Regime
        </h2>
        {regime && (
          <span
            className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
              OVERALL_STYLE[regime.overall] ?? OVERALL_STYLE.MIXED
            }`}
          >
            {regime.overall.replace("_", " ")}
          </span>
        )}
      </div>

      {!regime ? (
        <p className="text-sm text-gray-500">Scanning…</p>
      ) : (
        <div className="space-y-3">
          <Group label="Market (SPX / SPY)" views={regime.market} />
          <Group label="Tech (QQQ)" views={regime.tech} />
          <Group label="Sector (SMH / SOXX)" views={regime.sector} />
          {regime.volatility && (
            <div>
              <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-600">
                Volatility
              </h3>
              <ul className="space-y-1">
                <Row v={regime.volatility} />
              </ul>
              {regime.vix_elevated && (
                <p className="mt-1 text-[11px] text-degraded">
                  VIX elevated — risk-off tilt
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
