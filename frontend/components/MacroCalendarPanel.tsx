"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { MacroCalendarDay, MacroCalendarEvent } from "@/lib/types";

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });
  } catch {
    return iso;
  }
}

const importanceBadge: Record<string, string> = {
  high: "bg-red-500/20 text-red-400 border-red-500/30",
  medium: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  low: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

const statusBadge: Record<string, string> = {
  scheduled: "bg-blue-500/15 text-blue-400",
  release_window: "bg-orange-500/15 text-orange-400",
  released: "bg-green-500/15 text-green-400",
  delayed: "bg-yellow-500/15 text-yellow-400",
  cancelled: "bg-gray-500/15 text-gray-400",
  unavailable: "bg-red-500/15 text-red-400",
};

function EventRow({ event }: { event: MacroCalendarEvent }) {
  return (
    <tr className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
      <td className="py-2 px-2">
        <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase border ${importanceBadge[event.importance] ?? importanceBadge.low}`}>
          {event.importance}
        </span>
      </td>
      <td className="py-2 px-2 text-sm text-gray-200 font-medium">{event.name}</td>
      <td className="py-2 px-2 text-xs text-gray-400 font-mono">
        <div>{formatTime(event.release_time_gmt3)} <span className="text-gray-600">GMT+3</span></div>
        <div className="text-gray-600">{formatTime(event.release_time_et)} ET</div>
      </td>
      <td className="py-2 px-2 text-xs font-mono text-gray-400">{event.consensus ?? "—"}</td>
      <td className="py-2 px-2 text-xs font-mono text-gray-400">{event.prior ?? "—"}</td>
      <td className="py-2 px-2 text-xs font-mono text-gray-300">{event.actual ?? "—"}</td>
      <td className="py-2 px-2">
        <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${statusBadge[event.status] ?? statusBadge.scheduled}`}>
          {event.status}
        </span>
      </td>
    </tr>
  );
}

export function MacroCalendarPanel({
  calendar,
  blocked,
  blockType,
}: {
  calendar: MacroCalendarDay | null;
  blocked?: boolean;
  blockType?: string | null;
}) {
  const events = calendar?.events ?? [];

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/80 p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-bold text-gray-200 uppercase tracking-wider">
          Macro Calendar
        </h2>
        {blocked && (
          <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 bg-red-500/15 text-red-400 text-[10px] font-semibold uppercase">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-red-400 animate-pulse" />
            {blockType === "pre_release" ? "Pre-Release Block" : "Post-Release Block"}
          </span>
        )}
      </div>

      {calendar && (
        <div className="text-xs text-gray-500 mb-2">
          {calendar.date_gmt3} <span className="text-gray-600">GMT+3</span>{" "}
          · {calendar.date_et} <span className="text-gray-600">ET</span>
        </div>
      )}

      {events.length === 0 ? (
        <p className="text-xs text-gray-600 italic">No macro events today</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] text-gray-500 uppercase tracking-wider border-b border-gray-800">
                <th className="py-1.5 px-2">Impact</th>
                <th className="py-1.5 px-2">Event</th>
                <th className="py-1.5 px-2">Time</th>
                <th className="py-1.5 px-2">Cons.</th>
                <th className="py-1.5 px-2">Prior</th>
                <th className="py-1.5 px-2">Actual</th>
                <th className="py-1.5 px-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <EventRow key={e.event_id} event={e} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
