// Shared types mirroring the backend Phase 1 API payloads.

export type HealthStatus = "OK" | "DEGRADED" | "DOWN" | "UNKNOWN";
export type TradingMode = "SHADOW" | "PAPER" | "LIVE";

export interface ComponentHealth {
  component: string;
  status: HealthStatus;
  detail: string | null;
}

export interface HealthReport {
  ts: string;
  overall: HealthStatus;
  can_trade: boolean;
  components: ComponentHealth[];
}

export interface BrokerSnapshot {
  gateway_reachable: boolean;
  session_connected: boolean;
  account_available: boolean;
  data_feed: string;
  is_tradable: boolean;
  last_error: string | null;
}

export interface HealthResponse {
  mode: TradingMode;
  locked_out: boolean;
  lockout_reason: string | null;
  health: HealthReport;
  broker: BrokerSnapshot;
}

export interface ModeState {
  mode: TradingMode;
  locked_out: boolean;
  lockout_reason: string | null;
}

// --- Phase 2: market regime + scanner ---

export type Bias = "UP" | "DOWN" | "FLAT";

export interface SymbolView {
  symbol: string;
  bias: Bias;
  momentum_score: number;
  price: number | null;
  vwap: number | null;
  dist_from_vwap_pct: number | null;
  above_vwap: boolean | null;
}

export interface MarketRegime {
  market: Record<string, SymbolView>;
  tech: Record<string, SymbolView>;
  sector: Record<string, SymbolView>;
  volatility: SymbolView | null;
  overall: "RISK_ON" | "RISK_OFF" | "MIXED";
  vix_elevated: boolean;
}

export interface ContractView {
  expiry: string;
  strike: number;
  right: string;
  premium: number | null;
  ask: number | null;
  bid: number | null;
  spread_pct: number | null;
  volume: number | null;
  open_interest: number | null;
  delta: number | null;
  has_zero_dte: boolean;
}

export type ScoreBand = "NO_TRADE" | "WATCH" | "REDUCED_RISK" | "NORMAL";

export interface ScanCandidate {
  symbol: string;
  direction: "CALL" | "PUT";
  signal_type: string;
  score: number;
  band: ScoreBand;
  tradable: boolean;
  reject_codes: string[];
  score_breakdown: Record<string, number>;
  contract: ContractView | null;
  price: number | null;
  vwap: number | null;
  relative_volume: number | null;
  chop_band: string;
  chop_score: number;
  signal_ok?: boolean;
  risk_ok?: boolean;
  approved?: boolean;
  signal_decision?: Record<string, unknown>;
  risk_decision?: Record<string, unknown>;
}

export interface DayState {
  session_date: string;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  remaining_loss_allowance: number;
  open_premium_exposure: number;
  trades_today: number;
  lockout: boolean;
  lockout_reason: string | null;
  open_positions: number;
}

export interface BehaviorStatus {
  state: "CONTROLLED" | "CAUTION" | "RED";
  reasons: string[];
}

export interface MacroStatus {
  blocked: boolean;
  reason: string | null;
  active_event: string | null;
  next_event: string | null;
  next_event_time: string | null;
  minutes_to_next: number | null;
  should_exit_open: boolean;
}

export interface RiskStatusResponse {
  day: DayState;
  behavior: BehaviorStatus;
  macro: MacroStatus;
}

export interface ActivePositionView {
  underlying: string;
  expiry: string;
  strike: number;
  right: string;
  direction: string;
  quantity: number;
  entry_price: number;
  entry_ts: string;
  multiplier: number;
  stop_price: number;
  target_price: number;
  peak_premium: number;
  signal_type: string;
  is_shadow: boolean;
  mark?: number;
  unrealized_pnl?: number;
  premium_change_pct?: number;
  time_in_trade_sec?: number;
}

export interface ExecutionSnapshot {
  enabled: boolean;
  mode: string;
  active_position: ActivePositionView | null;
  last_order: {
    broker_order_id: number | null;
    state: string;
    filled_qty: number;
    avg_fill_price: number | null;
    message: string | null;
  } | null;
  last_exit_reason: string | null;
  messages: string[];
  automation_enabled?: boolean;
}

export interface ScanResult {
  asof: string;
  source: string;
  regime: MarketRegime;
  candidates: ScanCandidate[];
  top_calls: ScanCandidate[];
  top_puts: ScanCandidate[];
}

export interface JournalEntry {
  id: number;
  ts: string;
  kind: string;
  symbol: string | null;
  mode: string;
  payload: Record<string, unknown>;
}

export interface DailySummary {
  trade_date: string;
  realized_pnl: number;
  unrealized_pnl?: number;
  trades: number;
  rejected: number;
  lockouts?: number;
  top_rejections?: Record<string, number>;
  metrics?: Record<string, unknown>;
}

export interface BacktestResult {
  seed: number;
  steps: number;
  total_candidates: number;
  approved_count: number;
  rejected_count: number;
  approval_rate: number;
  top_symbols: { symbol: string; max_score: number }[];
  rejection_reasons: Record<string, number>;
}
