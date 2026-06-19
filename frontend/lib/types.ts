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

// --- LLM Guidance + Macro Calendar ---

export interface DualTimestamp {
  et: string;
  gmt3: string;
}

export interface MacroCalendarEvent {
  event_id: string;
  name: string;
  country: string;
  importance: "low" | "medium" | "high";
  release_time_et: string | null;
  release_time_gmt3: string | null;
  source: string;
  consensus: string | number | null;
  prior: string | number | null;
  actual: string | number | null;
  status: "scheduled" | "release_window" | "released" | "delayed" | "cancelled" | "unavailable";
  trading_block_before_minutes: number;
  trading_block_after_minutes: number;
  requires_release_update: boolean;
}

export interface MacroReleaseUpdate {
  event_id: string;
  name: string;
  release_time_et: string | null;
  release_time_gmt3: string | null;
  actual: string | number | null;
  consensus: string | number | null;
  prior: string | number | null;
  revision: string | number | null;
  surprise_direction: string;
  risk_asset_interpretation: string;
  rates_interpretation: string;
  volatility_interpretation: string;
  source: string;
  fetched_at_et: string | null;
  fetched_at_gmt3: string | null;
  status: string;
  spx_1m_change_pct: number | null;
  spx_3m_change_pct: number | null;
  spx_5m_change_pct: number | null;
  price_action: string | null;
}

export interface MacroCalendarDay {
  date_et: string | null;
  date_gmt3: string | null;
  events: MacroCalendarEvent[];
}

export interface ChartContextStatus {
  enabled: boolean;
  bar_count: number;
  compression_method: string | null;
  chart_valid: boolean | null;
  chart_issues: string[];
  status?: string;
  session_summary?: Record<string, unknown>;
}

export interface LLMGuidanceResponse {
  trade_permission: "allowed" | "no_trade" | "exit_only" | "blocked";
  direction: "CALL" | "PUT" | null;
  market_state: string | null;
  trigger_level: number | null;
  invalidation_level: number | null;
  target_1: number | null;
  target_2: number | null;
  stop_level: number | null;
  risk_mode: string | null;
  reasoning: string | null;
  confidence: number | null;
}

export interface LLMGuidanceSnapshot {
  guidance: LLMGuidanceResponse | null;
  request_metadata: Record<string, unknown> | null;
  bar_count: number;
  compression_method: string | null;
  chart_valid: boolean | null;
  enabled: boolean;
}

