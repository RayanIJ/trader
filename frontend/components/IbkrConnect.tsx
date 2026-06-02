"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { BrokerSnapshot } from "@/lib/types";

export function IbkrConnect({
  broker,
  onChanged,
}: {
  broker: BrokerSnapshot | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function connect() {
    setBusy(true);
    try {
      await api.ibkrConnect();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await api.ibkrDisconnect();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-panelborder bg-panel p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-300">
        IBKR (TWS Socket)
      </h2>
      <p className="mb-3 text-xs text-gray-500">
        Connects via the TWS/IB Gateway socket API. Start TWS or IB Gateway and
        enable the API socket; if a manual login is required, status stays
        blocked until authenticated.
      </p>
      <div className="flex gap-2">
        <button
          disabled={busy}
          onClick={connect}
          className="rounded border border-panelborder px-3 py-1.5 text-sm text-gray-200 hover:bg-gray-800 disabled:opacity-50"
        >
          Connect
        </button>
        <button
          disabled={busy}
          onClick={disconnect}
          className="rounded border border-panelborder px-3 py-1.5 text-sm text-gray-400 hover:bg-gray-800 disabled:opacity-50"
        >
          Disconnect
        </button>
      </div>
      {broker && (
        <p className="mt-3 text-xs text-gray-500">
          feed: <span className="text-gray-300">{broker.data_feed}</span> ·
          tradable:{" "}
          <span className={broker.is_tradable ? "text-ok" : "text-down"}>
            {String(broker.is_tradable)}
          </span>
        </p>
      )}
    </section>
  );
}
