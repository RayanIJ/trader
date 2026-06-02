"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export function EmergencyStop({ onTriggered }: { onTriggered: () => void }) {
  const [busy, setBusy] = useState(false);

  async function stop() {
    if (!window.confirm("EMERGENCY STOP: force Shadow mode and lock out trading?"))
      return;
    setBusy(true);
    try {
      await api.emergencyStop();
      onTriggered();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={stop}
      disabled={busy}
      className="w-full rounded-lg border-2 border-live bg-live/10 px-4 py-3 text-sm font-bold uppercase tracking-wide text-live transition hover:bg-live/20 disabled:opacity-50"
    >
      ⛔ Emergency Stop
    </button>
  );
}
