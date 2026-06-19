"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { connectWs } from "@/lib/ws";
import type {
  BrokerSnapshot,
  ChartContextStatus,
  ExecutionSnapshot,
  HealthReport,
  HealthResponse,
  JournalEntry,
  MacroCalendarDay,
  ModeState,
  RiskStatusResponse,
  ScanResult,
} from "@/lib/types";
import { SystemHealthPanel } from "@/components/SystemHealthPanel";
import { ModeControl } from "@/components/ModeControl";
import { EmergencyStop } from "@/components/EmergencyStop";
import { IbkrConnect } from "@/components/IbkrConnect";
import { MarketRegimePanel } from "@/components/MarketRegimePanel";
import { ScannerPanel } from "@/components/ScannerPanel";
import { RiskPanel } from "@/components/RiskPanel";
import { ExecutionPanel } from "@/components/ExecutionPanel";
import { ActivePositionPanel } from "@/components/ActivePositionPanel";
import { JournalPanel } from "@/components/JournalPanel";
import { MacroCalendarPanel } from "@/components/MacroCalendarPanel";
import { ChartContextPanel } from "@/components/ChartContextPanel";

export default function Dashboard() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [broker, setBroker] = useState<BrokerSnapshot | null>(null);
  const [mode, setMode] = useState<ModeState | null>(null);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [risk, setRisk] = useState<RiskStatusResponse | null>(null);
  const [execution, setExecution] = useState<ExecutionSnapshot | null>(null);
  const [liveJournalEntry, setLiveJournalEntry] = useState<JournalEntry | null>(null);
  const [wsLive, setWsLive] = useState(false);
  const [macroCalendar, setMacroCalendar] = useState<MacroCalendarDay | null>(null);
  const [chartContext, setChartContext] = useState<ChartContextStatus | null>(null);
  const [macroBlocked, setMacroBlocked] = useState(false);
  const [macroBlockType, setMacroBlockType] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const h: HealthResponse = await api.health();
      setHealth(h.health);
      setBroker(h.broker);
      setMode({
        mode: h.mode,
        locked_out: h.locked_out,
        lockout_reason: h.lockout_reason,
      });
    } catch {
      /* backend may be starting */
    }
    try {
      setScan(await api.scanner());
    } catch {
      /* scanner may not have produced a result yet */
    }
    try {
      setRisk(await api.riskStatus());
    } catch {
      /* risk endpoint may not be ready */
    }
    try {
      setExecution(await api.executionStatus());
    } catch {
      /* execution endpoint may not be ready */
    }
    try {
      setMacroCalendar(await api.macroCalendar());
    } catch {
      /* macro calendar may not be ready */
    }
    try {
      setChartContext(await api.chartContextStatus());
    } catch {
      /* chart context may not be ready */
    }
    try {
      const next = await api.macroNextEvent() as { blocked: boolean; block_type: string | null };
      setMacroBlocked(next.blocked);
      setMacroBlockType(next.block_type);
    } catch {
      /* macro next event may not be ready */
    }
  }, []);

  const toggleAutomation = useCallback(async (enabled: boolean) => {
    try {
      await api.setAutomation(enabled);
      setExecution(await api.executionStatus());
    } catch {
      /* ignore */
    }
  }, []);

  const rescan = useCallback(async () => {
    try {
      setScan(await api.scanNow());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
    const disconnect = connectWs((msg) => {
      setWsLive(true);
      if (msg.topic === "health") setHealth(msg.data);
      if (msg.topic === "snapshot") {
        setHealth(msg.data.health);
        setMode((m) => ({
          mode: msg.data.mode,
          locked_out: msg.data.locked_out,
          lockout_reason: m?.lockout_reason ?? null,
        }));
      }
      if (msg.topic === "mode")
        setMode({
          mode: msg.data.mode,
          locked_out: msg.data.locked_out,
          lockout_reason: msg.data.lockout_reason,
        });
      if (msg.topic === "scanner") setScan(msg.data as ScanResult);
      if (msg.topic === "execution") setExecution(msg.data as ExecutionSnapshot);
      if (msg.topic === "journal") setLiveJournalEntry(msg.data as JournalEntry);
      if (msg.topic === "macro_calendar") setMacroCalendar(msg.data as MacroCalendarDay);
      if (msg.topic === "chart_context") setChartContext(msg.data as ChartContextStatus);
    });
    return disconnect;
  }, [refresh]);

  const isLive = mode?.mode === "LIVE";

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      {isLive && (
        <div className="mb-4 rounded-lg border-2 border-live bg-live/10 px-4 py-2 text-center text-sm font-bold uppercase tracking-widest text-live">
          ● Live trading enabled — real orders may be sent
        </div>
      )}

      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">
            Options Trading Cockpit
          </h1>
          <p className="text-xs text-gray-500">
            SPX + semiconductor 0DTE scalping · risk-first · Phase 6
          </p>
        </div>
        <span className="flex items-center gap-2 text-xs text-gray-500">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              wsLive ? "bg-ok" : "bg-gray-600"
            }`}
          />
          {wsLive ? "live" : "polling"}
        </span>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <SystemHealthPanel health={health} broker={broker} />
          <ScannerPanel scan={scan} onRescan={rescan} />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <MarketRegimePanel regime={scan?.regime ?? null} />
            <RiskPanel risk={risk} />
            <ExecutionPanel execution={execution} onToggleAutomation={toggleAutomation} />
            <ActivePositionPanel position={execution?.active_position ?? null} />
            <MacroCalendarPanel
              calendar={macroCalendar}
              blocked={macroBlocked}
              blockType={macroBlockType}
            />
            <ChartContextPanel context={chartContext} />
            <JournalPanel liveEntry={liveJournalEntry} />
          </div>
        </div>

        <div className="space-y-4">
          <ModeControl mode={mode} onChanged={refresh} />
          <IbkrConnect broker={broker} onChanged={refresh} />
          <EmergencyStop onTriggered={refresh} />
        </div>
      </div>
    </main>
  );
}
