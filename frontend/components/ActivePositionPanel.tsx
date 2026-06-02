"use client";

import type { ActivePositionView } from "@/lib/types";

export function ActivePositionPanel({ position }: { position: ActivePositionView | null }) {
  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">
        Active Position
      </h2>
      {!position ? (
        <p className="text-sm text-gray-500">No open position</p>
      ) : (
        <div className="grid gap-2 text-sm md:grid-cols-2">
          <div>
            <div className="text-[11px] uppercase text-gray-500">Contract</div>
            <div className="text-gray-100">
              {position.underlying} {position.direction} {position.strike}
              {position.right} · {position.expiry}
              {position.is_shadow && (
                <span className="ml-2 text-xs text-gray-500">(shadow)</span>
              )}
            </div>
          </div>
          <div>
            <div className="text-[11px] uppercase text-gray-500">Entry</div>
            <div>${position.entry_price.toFixed(2)}</div>
          </div>
          {position.mark != null && (
            <>
              <div>
                <div className="text-[11px] uppercase text-gray-500">Mark</div>
                <div>${position.mark.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase text-gray-500">Unrealized</div>
                <div className={position.unrealized_pnl! >= 0 ? "text-ok" : "text-down"}>
                  ${position.unrealized_pnl!.toFixed(2)}
                </div>
              </div>
            </>
          )}
          <div>
            <div className="text-[11px] uppercase text-gray-500">Stop / Target</div>
            <div className="text-gray-400">
              ${position.stop_price.toFixed(2)} / ${position.target_price.toFixed(2)}
            </div>
          </div>
          {position.time_in_trade_sec != null && (
            <div>
              <div className="text-[11px] uppercase text-gray-500">Time in trade</div>
              <div>{Math.round(position.time_in_trade_sec)}s</div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
