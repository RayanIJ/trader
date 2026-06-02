"""
Streamlit Dashboard for AI Trading Application.
Enhanced with Live Portfolio, Performance Charts, Risk Metrics, and more.
"""
import os
import sys
import time
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
import dotenv
import streamlit as st
import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import settings
from src.config.market_calendar import get_market_status

# Page config
st.set_page_config(
    page_title="🤖 IB AI Trader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 10px;
        padding: 15px;
        margin: 5px 0;
    }
    .positive { color: #00ff88 !important; }
    .negative { color: #ff4444 !important; }
    .stMetric > div { background: rgba(0,0,0,0.2); border-radius: 8px; padding: 10px; }
</style>
""", unsafe_allow_html=True)

# --- Data Refresh Infrastructure ---

def refresh_all_data():
    """Force refresh all cached data."""
    st.cache_data.clear()
    if 'last_refresh' in st.session_state:
        del st.session_state['last_refresh']
    if 'pending_orders' in st.session_state:
        del st.session_state['pending_orders']
    if 'portfolio_data' in st.session_state:
        del st.session_state['portfolio_data']
    st.session_state['last_refresh'] = datetime.now().strftime("%H:%M:%S")

# Initialize last refresh time
if 'last_refresh' not in st.session_state:
    st.session_state['last_refresh'] = datetime.now().strftime("%H:%M:%S")

# --- Helper Functions ---

def load_config():
    """Load raw config from .env file."""
    return dotenv.dotenv_values(PROJECT_ROOT / ".env")

def save_config(config_dict):
    """Save config to .env file."""
    env_path = PROJECT_ROOT / ".env"
    with open(env_path, "w") as f:
        for key, value in config_dict.items():
            # Ensure value is quoted
            safe_val = str(value).replace('"', '\\"')
            f.write(f'{key}="{safe_val}"\n')
    st.cache_data.clear()

def check_log_file():
    """Read the latest logs."""
    log_path = PROJECT_ROOT / "trader.log"
    if log_path.exists():
        with open(log_path, "r") as f:
            lines = f.readlines()
            return "".join(reversed(lines[-100:]))
    return "No logs found."

def load_execution_history():
    """Load trading history from JSON."""
    history_path = PROJECT_ROOT / "trades" / "execution_history.json"
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def calculate_risk_metrics(history):
    """Calculate trading performance metrics."""
    if not history:
        return {}
    
    # Extract confidence scores
    confidences = [h.get('recommendation', {}).get('confidence', 0) for h in history]
    
    # Count actions
    actions = [h.get('recommendation', {}).get('action', 'HOLD') for h in history]
    buy_count = actions.count('BUY')
    sell_count = actions.count('SELL')
    hold_count = actions.count('HOLD')
    
    # Win rate placeholder (would need actual P/L tracking)
    total_trades = buy_count + sell_count
    
    return {
        "total_cycles": len(history),
        "buy_signals": buy_count,
        "sell_signals": sell_count,
        "hold_signals": hold_count,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else 0,
        "trade_rate": (total_trades / len(history) * 100) if history else 0
    }

def get_alerts(history):
    """Extract alerts and warnings from history."""
    alerts = []
    for h in history[-10:]:  # Last 10 cycles
        rec = h.get('recommendation', {})
        ctx = h.get('ai_context', {})
        
        # Check for errors
        if ctx.get('error'):
            alerts.append({"type": "error", "msg": f"API Error: {ctx['error']}", "time": h.get('timestamp')})
        
        # Check for low confidence
        if rec.get('confidence', 1) < 0.5:
            alerts.append({"type": "warning", "msg": f"Low confidence ({rec['confidence']:.0%}) on {rec.get('symbol')}", "time": h.get('timestamp')})
        
        # Check for risk level
        if rec.get('risk_level') == 'High':
            alerts.append({"type": "warning", "msg": f"High risk trade: {rec.get('symbol')}", "time": h.get('timestamp')})
    
    return alerts[:5]  # Return max 5 alerts

# --- Sidebar Status ---

st.sidebar.title("🤖 Status")

market_status = get_market_status()
if market_status["is_open"]:
    st.sidebar.success(f"🟢 Market OPEN ({market_status['market_close_time']} Close)")
else:
    st.sidebar.warning(f"🔴 Market CLOSED (Next: {market_status['next_open']})")

if settings.dry_run:
    st.sidebar.info("🧪 DRY RUN Mode")
else:
    st.sidebar.error("💸 REAL TRADING Mode")

# Load history once for all tabs
history = load_execution_history()
metrics = calculate_risk_metrics(history)

st.sidebar.markdown("---")
st.sidebar.metric("Total Cycles", metrics.get('total_cycles', 0))
st.sidebar.metric("Avg Confidence", f"{metrics.get('avg_confidence', 0):.1%}")

# --- Tab Persistence via URL Query Params ---
TAB_OPTIONS = {
    "dashboard": "📊 Dashboard",
    "manual": "🎯 Manual Run",
    "portfolio": "💼 Portfolio",
    "orders": "📋 Pending Orders",
    "history": "📜 Cycle History",
    "performance": "📈 Performance",
    "config": "⚙️ Configuration",
    "logs": "📋 Logs"
}

TAB_NAMES = list(TAB_OPTIONS.keys())
TAB_LABELS = list(TAB_OPTIONS.values())

# Get current tab from URL query params
query_params = st.query_params
current_tab_name = query_params.get("tab", "dashboard")
if current_tab_name not in TAB_NAMES:
    current_tab_name = "dashboard"

default_index = TAB_NAMES.index(current_tab_name)

# Sidebar Navigation (Radio button for persistence)
st.sidebar.markdown("---")
st.sidebar.subheader("📍 Navigation")
selected_tab_label = st.sidebar.radio(
    "Go to:", 
    options=TAB_LABELS, 
    index=default_index,
    key="nav_radio"
)

# Update query param when selection changes
selected_tab_name = TAB_NAMES[TAB_LABELS.index(selected_tab_label)]
if selected_tab_name != current_tab_name:
    st.query_params["tab"] = selected_tab_name

# Helper to update URL when tab changes internally
def set_tab_param(tab_name):
    st.query_params["tab"] = tab_name

# =============================================================================
# RENDER TABS
# =============================================================================

if selected_tab_name == "dashboard":
    # --- TAB 1: MAIN DASHBOARD ---
    st.header("🤖 AI Trading Dashboard")
    
    # Refresh controls
    col_ref, col_time = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 Refresh Data", key="dash_refresh", width="stretch"):
            refresh_all_data()
            st.rerun()
    with col_time:
        st.caption(f"Last updated: {st.session_state.get('last_refresh', 'N/A')}")
    
    # Alerts Section
    alerts = get_alerts(history)
    if alerts:
        st.subheader("🔔 Recent Alerts")
        for alert in alerts:
            if alert['type'] == 'error':
                st.error(f"❌ {alert['msg']}")
            else:
                st.warning(f"⚠️ {alert['msg']}")
    
    # Key Metrics Row
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("📊 Total Cycles", metrics.get('total_cycles', 0))
    with col2:
        st.metric("🟢 BUY Signals", metrics.get('buy_signals', 0))
    with col3:
        st.metric("🔴 SELL Signals", metrics.get('sell_signals', 0))
    with col4:
        st.metric("⏸️ HOLD Signals", metrics.get('hold_signals', 0))
    with col5:
        st.metric("🎯 Trade Rate", f"{metrics.get('trade_rate', 0):.1f}%")
    
    st.divider()
    
    # Recent Activity
    st.subheader("📝 Recent Activity")
    if history:
        recent = history[-5:][::-1]  # Last 5, reversed
        for h in recent:
            rec = h.get('recommendation', {})
            action = rec.get('action', 'N/A')
            symbol = rec.get('symbol', 'N/A')
            confidence = rec.get('confidence', 0)
            timestamp = h.get('timestamp', '')[:19]
            
            # Web search indicator
            web_used = h.get('ai_context', {}).get('web_search_used', False)
            web_icon = "🌐" if web_used else ""
            
            color = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🔵"}.get(action, "⚪")
            st.markdown(f"{color} **{action}** {symbol} ({confidence:.0%}) {web_icon} — `{timestamp}`")
    else:
        st.info("No activity yet. Start the trading bot to see results.")
    
    # Confidence Distribution
    st.divider()
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.subheader("📊 Confidence Distribution")
        if history:
            confidences = [h.get('recommendation', {}).get('confidence', 0) for h in history]
            conf_df = pd.DataFrame({'Confidence': confidences})
            st.bar_chart(conf_df['Confidence'].value_counts().sort_index())
        else:
            st.info("No data for histogram.")
    
    with col_chart2:
        st.subheader("📈 Action Distribution")
        if history:
            actions = [h.get('recommendation', {}).get('action', 'HOLD') for h in history]
            action_counts = pd.Series(actions).value_counts()
            st.bar_chart(action_counts)
        else:
            st.info("No data for chart.")

# =============================================================================
# TAB 2: MANUAL RUN
# =============================================================================

elif selected_tab_name == "manual":
    st.header("🎯 Manual Trading Cycle")
    st.markdown("Run a single trading cycle for any ticker. Get AI analysis and optionally execute trades.")
    
    # Input Section
    col_input1, col_input2 = st.columns([2, 1])
    
    with col_input1:
        ticker_input = st.text_input(
            "Enter Ticker Symbol",
            placeholder="e.g., AAPL, NVDA, SOXL",
            help="Enter a US stock ticker symbol",
            key="manual_ticker"
        ).upper().strip()
    
    with col_input2:
        st.markdown("<br>", unsafe_allow_html=True)  # Spacing
        analyze_only = st.checkbox(
            "🔍 Analyze Only",
            value=True,
            help="If checked, will only analyze - no trades will be executed"
        )
    
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
    
    with col_btn1:
        run_button = st.button(
            "🚀 Run Cycle",
            type="primary",
            disabled=not ticker_input,
            width="stretch"
        )
    
    with col_btn2:
        skip_safety = st.checkbox(
            "Skip Safety Checks",
            value=False,
            help="Skip EOD and auto TP/SL checks"
        )
    
    st.divider()
    
    # Results Section
    if run_button and ticker_input:
        with st.spinner(f"Running analysis for {ticker_input}..."):
            try:
                from src.main import get_trading_bot, ManualCycleResult
                
                bot = get_trading_bot()
                result: ManualCycleResult = bot.run_manual_cycle(
                    ticker=ticker_input,
                    analyze_only=analyze_only,
                    skip_safety_checks=skip_safety
                )
                
                if result.success:
                    st.success(f"✅ Analysis complete for {result.ticker}")
                    
                    # Indicators Section
                    st.subheader("📊 Technical Indicators")
                    
                    ind = result.indicators
                    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
                    
                    with col_p1:
                        price = ind.get('current_price', 0)
                        day_chg = ind.get('day_change_pct', 0)
                        st.metric(
                            "Price",
                            f"${price:.2f}",
                            f"{day_chg:+.2f}%",
                            delta_color="normal" if day_chg >= 0 else "inverse"
                        )
                    with col_p2:
                        rsi = ind.get('rsi')
                        rsi_signal = ind.get('rsi_signal', 'N/A')
                        st.metric("RSI (14)", f"{rsi:.1f}" if rsi else "N/A", rsi_signal)
                    with col_p3:
                        vwap = ind.get('vwap')
                        vwap_sig = "Above" if price and vwap and price > vwap else "Below"
                        st.metric("VWAP", f"${vwap:.2f}" if vwap else "N/A", vwap_sig)
                    with col_p4:
                        vol_sig = ind.get('volume_signal', 'N/A')
                        st.metric("Volume", f"{ind.get('volume', 0):,}", vol_sig.split('(')[0].strip() if vol_sig else "N/A")
                    
                    # MACD and Trend
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    with col_m1:
                        st.metric("MACD Signal", ind.get('macd_crossover', 'N/A')[:20] + "..." if len(ind.get('macd_crossover', '')) > 20 else ind.get('macd_crossover', 'N/A'))
                    with col_m2:
                        st.metric("Trend (SMA20)", ind.get('trend', 'N/A'))
                    with col_m3:
                        st.metric("ATR (14)", f"${ind.get('atr', 0):.2f}" if ind.get('atr') else "N/A")
                    with col_m4:
                        st.metric("Price Source", ind.get('price_source', 'N/A'))
                    
                    st.divider()
                    
                    # AI Recommendation
                    if result.recommendation:
                        rec = result.recommendation
                        st.subheader("🤖 AI Recommendation")
                        
                        # Action badge
                        action_colors = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🔵"}
                        action_icon = action_colors.get(str(rec.action), "⚪")
                        
                        col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                        with col_r1:
                            st.metric("Action", f"{action_icon} {rec.action}")
                        with col_r2:
                            st.metric("Confidence", f"{rec.confidence:.0%}")
                        with col_r3:
                            st.metric("Quantity", rec.quantity)
                        with col_r4:
                            st.metric("Order Type", str(rec.order_type))
                        
                        # Prices
                        if rec.limit_price or rec.stop_price or rec.target_price:
                            col_pr1, col_pr2, col_pr3 = st.columns(3)
                            with col_pr1:
                                if rec.limit_price:
                                    st.metric("Limit Price", f"${rec.limit_price:.2f}")
                            with col_pr2:
                                if rec.stop_price:
                                    st.metric("Stop Price", f"${rec.stop_price:.2f}")
                            with col_pr3:
                                if rec.target_price:
                                    st.metric("Target Price", f"${rec.target_price:.2f}")
                        
                        # Reasoning
                        st.markdown("**💭 AI Reasoning:**")
                        st.info(rec.reasoning)
                        
                        # Additional context
                        if rec.market_regime:
                            st.markdown(f"**📈 Market Regime:** {rec.market_regime}")
                        if rec.risk_level:
                            risk_colors = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}
                            st.markdown(f"**⚠️ Risk Level:** {risk_colors.get(rec.risk_level, '')} {rec.risk_level}")
                        if rec.news_catalysts:
                            st.markdown("**📰 News Catalysts:**")
                            for news in rec.news_catalysts:
                                st.markdown(f"- {news}")
                    
                    st.divider()
                    
                    # Action Taken
                    st.subheader("⚡ Action Taken")
                    if result.action_taken:
                        if "DRY RUN" in result.action_taken:
                            st.warning(f"🧪 {result.action_taken}")
                        elif "ANALYZE ONLY" in result.action_taken:
                            st.info(f"🔍 {result.action_taken}")
                        elif "HOLD" in result.action_taken:
                            st.info(f"⏸️ {result.action_taken}")
                        elif "Trade placed" in result.action_taken:
                            st.success(f"✅ {result.action_taken}")
                        else:
                            st.write(result.action_taken)
                    else:
                        st.caption("No action taken")
                    
                    # Web Search indicator
                    if result.ai_context.get('web_search_used'):
                        st.success("🌐 AI used real-time web search for this analysis")
                    
                else:
                    st.error(f"❌ Analysis failed: {result.error}")
                    
            except Exception as e:
                st.error(f"❌ Error running manual cycle: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    
    elif not ticker_input:
        st.info("👆 Enter a ticker symbol above and click 'Run Cycle' to start")
    
    # Quick Actions
    st.divider()
    st.subheader("⚡ Quick Actions")
    col_q1, col_q2, col_q3, col_q4 = st.columns(4)
    
    with col_q1:
        if st.button("📈 SOXL", width="stretch"):
            st.session_state.manual_ticker = "SOXL"
            st.rerun()
    with col_q2:
        if st.button("📉 SOXS", width="stretch"):
            st.session_state.manual_ticker = "SOXS"
            st.rerun()
    with col_q3:
        if st.button("🟢 NVDA", width="stretch"):
            st.session_state.manual_ticker = "NVDA"
            st.rerun()
    with col_q4:
        if st.button("🍎 AAPL", width="stretch"):
            st.session_state.manual_ticker = "AAPL"
            st.rerun()

# =============================================================================
# TAB 3: PORTFOLIO
# =============================================================================

elif selected_tab_name == "portfolio":
    st.header("💼 Live Portfolio")
    
    # Refresh controls
    col_ref, col_time = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 Refresh Portfolio", key="port_refresh", width="stretch"):
            refresh_all_data()
            st.rerun()
    with col_time:
        st.caption(f"Last updated: {st.session_state.get('last_refresh', 'N/A')}")
    
    # Get latest portfolio from history
    if history:
        latest = history[-1]
        portfolio = latest.get('portfolio', {})
        account = portfolio.get('account', {})
        positions = portfolio.get('positions', [])
        
        # Account Summary
        st.subheader("💰 Account Summary")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Net Liquidation", f"${account.get('net_liquidation') or 0:,.2f}")
        with col2:
            st.metric("Cash Available", f"${account.get('total_cash_value') or 0:,.2f}")
        with col3:
            st.metric("Buying Power", f"${account.get('buying_power') or 0:,.2f}")
        with col4:
            st.metric("Position Value", f"${account.get('gross_position_value') or 0:,.2f}")
        
        st.divider()
        
        # Positions Table
        st.subheader("📋 Current Positions")
        if positions:
            # Import yfinance for live prices
            import yfinance as yf
            
            pos_data = []
            total_market_value = 0
            total_pnl_calculated = 0
            
            for p in positions:
                qty = float(p.get('quantity', 0))
                avg_cost = float(p.get('avg_cost', 0))
                sec_type = p.get('sec_type', 'STK')
                symbol = p.get('symbol')
                multiplier = float(p.get('multiplier', 1.0))
                
                # Prioritize IB-provided market price/value/pnl
                market_price = p.get('market_price')
                market_value = p.get('market_value')
                unrealized_pnl = p.get('unrealized_pnl')
                
                # Fallback if IB data is missing
                if not market_price and symbol and sec_type == 'STK':
                    try:
                        ticker = yf.Ticker(symbol)
                        market_price = ticker.fast_info.last_price
                    except:
                        market_price = None
                
                # Calculate if IB value is missing but we have price
                if market_value is None and market_price is not None:
                    market_value = qty * market_price * multiplier
                    unrealized_pnl = market_value - (qty * avg_cost * multiplier)
                
                # Accumulate totals
                total_market_value += (market_value or 0)
                total_pnl_calculated += (unrealized_pnl or 0)
                
                pos_data.append({
                    "Symbol": symbol,
                    "Type": sec_type,
                    "Qty": int(qty),
                    "Avg Cost": f"${avg_cost:.2f}",
                    "Mkt Price": f"${market_price:.2f}" if market_price else "N/A",
                    "Mkt Value": f"${market_value:,.2f}" if market_value is not None else "N/A",
                    "P/L": f"${unrealized_pnl:+,.2f}" if unrealized_pnl is not None else "N/A",
                })
            
            df = pd.DataFrame(pos_data)
            st.dataframe(df, width="stretch", hide_index=True)
            
            # Summary totals
            total_cost = sum(p.get('cost_basis') or (float(p.get('quantity',0)) * float(p.get('avg_cost',0)) * float(p.get('multiplier',1.0))) for p in positions)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Cost Basis", f"${total_cost:,.2f}")
            with col2:
                st.metric("Total Mkt Value", f"${total_market_value:,.2f}" if total_market_value > 0 else "N/A")
            with col3:
                if total_pnl_calculated != 0:
                    st.metric(
                        "Unrealized P/L", 
                        f"${total_pnl_calculated:+,.2f}", 
                        delta=f"{(total_pnl_calculated/total_cost if total_cost else 0):.2%}"
                    )
                else:
                    st.metric("Unrealized P/L", "N/A")
        else:
            st.info("No positions found.")
    else:
        st.info("No portfolio data available. Run the trading bot first.")

# =============================================================================
# TAB 4: PENDING ORDERS
# =============================================================================

elif selected_tab_name == "orders":
    st.header("📋 Pending Orders")
    st.markdown("View all open/pending orders from Interactive Brokers.")
    
    # Refresh controls
    col_ref, col_time = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 Refresh Orders", key="orders_refresh", width="stretch"):
            refresh_all_data()
            st.rerun()
    with col_time:
        st.caption(f"Last updated: {st.session_state.get('last_refresh', 'N/A')}")
        try:
            from src.main import get_trading_bot
            bot = get_trading_bot()
            
            if bot.ib_app.is_connected:
                orders = bot.ib_app.get_open_orders()
                st.session_state.pending_orders = orders
            else:
                st.session_state.pending_orders = []
                st.warning("Not connected to IB Gateway")
        except Exception as e:
            st.session_state.pending_orders = []
            st.error(f"Error fetching orders: {e}")
    
    orders = st.session_state.get('pending_orders', [])
    
    if orders:
        st.success(f"Found {len(orders)} pending order(s)")
        
        # Orders table
        order_data = []
        for o in orders:
            order_data.append({
                "Order ID": o.get('order_id'),
                "Symbol": o.get('symbol'),
                "Action": o.get('action'),
                "Qty": o.get('quantity'),
                "Type": o.get('order_type'),
                "Limit": f"${o.get('limit_price', 0):.2f}" if o.get('limit_price') else "MKT",
                "Stop": f"${o.get('stop_price', 0):.2f}" if o.get('stop_price') else "-",
                "Status": o.get('status'),
                "Filled": o.get('filled', 0),
                "Remaining": o.get('remaining', 0),
            })
        
        df = pd.DataFrame(order_data)
        st.dataframe(df, width="stretch", hide_index=True)
        
        # Summary
        st.divider()
        symbols = list(set(o.get('symbol') for o in orders))
        buy_orders = len([o for o in orders if o.get('action') == 'BUY'])
        sell_orders = len([o for o in orders if o.get('action') == 'SELL'])
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Symbols with Orders", ", ".join(symbols))
        with col2:
            st.metric("BUY Orders", buy_orders)
        with col3:
            st.metric("SELL Orders", sell_orders)
        
        st.info("🔒 **Duplicate Prevention Active**: The bot will not submit new BUY orders for symbols with pending orders.")
    else:
        st.info("No pending orders found. All orders are either filled or cancelled.")

# =============================================================================
# TAB 5: CYCLE HISTORY (Enhanced)
# =============================================================================

elif selected_tab_name == "history":
    st.header("📜 Trading Cycle History")
    
    # Refresh controls
    col_ref, col_time = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 Refresh History", key="hist_refresh", width="stretch"):
            refresh_all_data()
            st.rerun()
    with col_time:
        st.caption(f"Last updated: {st.session_state.get('last_refresh', 'N/A')}")
    
    if history:
        # Filters
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            action_filter = st.multiselect("Filter by Action", ["BUY", "SELL", "HOLD"], default=["BUY", "SELL", "HOLD"])
        with col_f2:
            limit = st.slider("Show last N cycles", 5, 50, 10)
        
        filtered = [h for h in history if h.get('recommendation', {}).get('action') in action_filter][-limit:][::-1]
        
        for h in filtered:
            rec = h.get('recommendation', {})
            action = rec.get('action', 'N/A')
            symbol = rec.get('symbol', 'N/A')
            timestamp = h.get('timestamp', 'N/A')
            ai_ctx = h.get('ai_context', {})
            
            # Color code
            color = {"BUY": "green", "SELL": "red", "HOLD": "blue"}.get(action, "gray")
            
            with st.expander(f":{color}[{action}] {symbol} @ {timestamp}"):
                # Web Search Results
                if ai_ctx.get('web_search_used'):
                    st.success("🌐 AI used Web Search for this decision")
                
                st.subheader("🤖 AI Reasoning")
                st.write(rec.get('reasoning', 'No reasoning provided.'))
                
                # Details columns
                col_a, col_b = st.columns(2)
                
                with col_a:
                    st.markdown("**📊 Trade Details:**")
                    st.json({
                        "Action": rec.get('action'),
                        "Symbol": rec.get('symbol'),
                        "Quantity": rec.get('quantity'),
                        "Order Type": rec.get('order_type'),
                        "Limit Price": rec.get('limit_price'),
                        "Stop Price": rec.get('stop_price'),
                        "Confidence": f"{rec.get('confidence', 0):.0%}",
                        "Risk Level": rec.get('risk_level'),
                        "Market Regime": rec.get('market_regime'),
                    })
                
                with col_b:
                    st.markdown("**📰 News/Catalysts:**")
                    news = rec.get('news_catalysts')
                    if news:
                        st.info(news)
                    else:
                        st.caption("No news catalysts reported.")
                    
                    st.markdown("**⚠️ Invalidation:**")
                    inv = rec.get('invalidation_condition')
                    if inv:
                        st.warning(inv)
                    else:
                        st.caption("No invalidation condition set.")
                
                # Prompts (collapsible)
                st.divider()
                st.subheader("📝 Raw Prompts & Response")
                
                prompt_tab1, prompt_tab2, prompt_tab3 = st.tabs(["📤 User Prompt", "🔧 System Prompt", "📥 Raw Response"])
                
                with prompt_tab1:
                    st.code(ai_ctx.get('user_prompt', 'N/A'), language="text")
                
                with prompt_tab2:
                    st.code(ai_ctx.get('system_prompt', 'N/A')[:3000], language="text")
                    if len(ai_ctx.get('system_prompt', '')) > 3000:
                        st.caption("(Truncated for display)")
                
                with prompt_tab3:
                    raw_response = ai_ctx.get('raw_response', 'N/A')
                    if raw_response and raw_response != 'N/A':
                        st.code(raw_response, language="markdown")
                    else:
                        st.info("Raw response not captured for this cycle.")
                
                st.caption(f"Model: {ai_ctx.get('model', 'N/A')}")
    else:
        st.info("No execution history found. Run the bot to generate history.")

# =============================================================================
# TAB 5: PERFORMANCE
# =============================================================================

elif selected_tab_name == "performance":
    st.header("📈 Performance Analytics")
    
    # Refresh controls
    col_ref, col_time = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 Refresh Performance", key="perf_refresh", width="stretch"):
            refresh_all_data()
            st.rerun()
    with col_time:
        st.caption(f"Last updated: {st.session_state.get('last_refresh', 'N/A')}")
    
    if history and len(history) > 1:
        # Equity Curve (simulated from Net Liq snapshots)
        st.subheader("💰 Equity Curve")
        
        equity_data = []
        for h in history:
            portfolio = h.get('portfolio', {})
            account = portfolio.get('account', {})
            net_liq = account.get('net_liquidation', 0)
            timestamp = h.get('timestamp', '')[:19]
            if net_liq and timestamp:
                equity_data.append({"Time": timestamp, "Net Liquidation": net_liq})
        
        if equity_data:
            eq_df = pd.DataFrame(equity_data)
            eq_df['Time'] = pd.to_datetime(eq_df['Time'])
            eq_df = eq_df.set_index('Time')
            st.line_chart(eq_df['Net Liquidation'])
        
        st.divider()
        
        # Risk Metrics
        st.subheader("📊 Risk Metrics")
        col1, col2, col3 = st.columns(3)
        
        # Calculate some basic metrics
        if equity_data:
            values = [e['Net Liquidation'] for e in equity_data]
            start_val = values[0]
            end_val = values[-1]
            pnl = end_val - start_val
            pnl_pct = (pnl / start_val * 100) if start_val else 0
            max_val = max(values)
            min_val = min(values)
            max_dd = ((max_val - min_val) / max_val * 100) if max_val else 0
            
            with col1:
                delta_color = "normal" if pnl >= 0 else "inverse"
                st.metric("Total P/L", f"${pnl:,.2f}", f"{pnl_pct:+.2f}%", delta_color=delta_color)
            with col2:
                st.metric("Max Drawdown", f"{max_dd:.2f}%")
            with col3:
                # Win rate (simplified: actions that weren't HOLD are "trades")
                trades = [h for h in history if h.get('recommendation', {}).get('action') in ['BUY', 'SELL']]
                st.metric("Total Trades Executed", len(trades))
        
        st.divider()
        
        # Confidence over time
        st.subheader("🎯 Confidence Trend")
        conf_data = []
        for h in history:
            conf = h.get('recommendation', {}).get('confidence', 0)
            timestamp = h.get('timestamp', '')[:19]
            if timestamp:
                conf_data.append({"Time": timestamp, "Confidence": conf})
        
        if conf_data:
            conf_df = pd.DataFrame(conf_data)
            conf_df['Time'] = pd.to_datetime(conf_df['Time'])
            conf_df = conf_df.set_index('Time')
            st.line_chart(conf_df['Confidence'])
    else:
        st.info("Not enough data for performance analytics. Run more trading cycles.")

# =============================================================================
# TAB 6: CONFIGURATION
# =============================================================================

elif selected_tab_name == "config":
    st.header("⚙️ Bot Configuration")
    
    current_config = load_config()
    
    with st.form("config_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📈 Strategy & Scope")
            
            trading_strategy = st.text_input(
                "Trading Strategy", 
                value=current_config.get("TRADING_STRATEGY", "Momentum Trend Following"),
                help="Primary trading approach"
            )
            
            exit_strategy = st.text_input(
                "Exit Strategy", 
                value=current_config.get("EXIT_STRATEGY", "Trailing Stop 2%"),
                help="Rules for closing positions"
            )
            
            target_tickers = st.text_area(
                "Target Tickers (Comma separated)", 
                value=current_config.get("TARGET_TICKERS", "SOXL, SOXS"),
                help="Stocks to analyze"
            )
            
            strategy_context = st.text_area(
                "Additional AI Context", 
                value=current_config.get("STRATEGY_CONTEXT", "Focus on high volume liquid stocks."),
                help="Extra instructions for AI"
            )

        with col2:
            st.subheader("⚙️ Risk & System")
            
            max_dollars = st.number_input(
                "Max $ Per Trade", 
                min_value=100,
                step=100,
                value=int(current_config.get("MAX_DOLLARS_PER_TRADE", 1000))
            )
            
            confidence = st.slider(
                "Min Confidence Threshold", 
                0.0, 1.0, 
                float(current_config.get("CONFIDENCE_THRESHOLD", 0.7))
            )
            
            ib_port = st.number_input(
                "IB Port (7497=Paper, 7496=Live)", 
                value=int(current_config.get("IB_PORT", 7497))
            )
            
            trading_interval = st.number_input(
                "Trading Interval (Seconds)", 
                min_value=60,
                value=int(current_config.get("TRADING_INTERVAL_SECONDS", 300))
            )
            
            is_dry_run = st.toggle(
                "Enable DRY RUN Mode", 
                value=current_config.get("DRY_RUN", "true").lower() == "true",
                help="If enabled, no real orders sent"
            )

            st.subheader("🔑 API Keys")
            openai_key = st.text_input(
                "OpenAI API Key", 
                value=current_config.get("OPENAI_API_KEY", ""), 
                type="password"
            )

        submitted = st.form_submit_button("💾 Save Configuration")
        
        if submitted:
            new_config = current_config.copy()
            new_config["TRADING_STRATEGY"] = trading_strategy
            new_config["EXIT_STRATEGY"] = exit_strategy
            new_config["TARGET_TICKERS"] = target_tickers
            new_config["STRATEGY_CONTEXT"] = strategy_context
            new_config["MAX_DOLLARS_PER_TRADE"] = str(max_dollars)
            new_config["CONFIDENCE_THRESHOLD"] = str(confidence)
            new_config["IB_PORT"] = str(ib_port)
            new_config["TRADING_INTERVAL_SECONDS"] = str(trading_interval)
            new_config["DRY_RUN"] = "true" if is_dry_run else "false"
            new_config["OPENAI_API_KEY"] = openai_key
            
            save_config(new_config)
            st.success("✅ Configuration saved! Restart the bot to apply changes.")

# =============================================================================
# TAB 7: LOGS
# =============================================================================

elif selected_tab_name == "logs":
    st.header("📋 Live Bot Logs")
    
    # Controls row
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    
    with col1:
        if st.button("🔄 Refresh Now"):
            st.rerun()
    
    with col2:
        auto_refresh = st.toggle("🔴 Live", value=False, help="Auto-refresh every 3 seconds")
    
    with col3:
        line_count = st.selectbox("Lines", [50, 100, 200, 500], index=1)
    
    with col4:
        log_filter = st.text_input("🔍 Filter", placeholder="e.g. ERROR, OpenAI, ANSWER")
    
    # Read logs
    log_path = PROJECT_ROOT / "trader.log"
    if log_path.exists():
        with open(log_path, "r") as f:
            lines = f.readlines()
            # Get last N lines, reversed (newest first)
            recent_lines = lines[-line_count:][::-1]
            
            # Apply filter if provided
            if log_filter:
                recent_lines = [l for l in recent_lines if log_filter.lower() in l.lower()]
            
            log_text = "".join(recent_lines)
    else:
        log_text = "No logs found."
    
    # Display with syntax highlighting for log levels
    st.code(log_text, language="text", line_numbers=True)
    
    # Status indicator
    st.caption(f"📊 Showing {min(line_count, len(lines) if log_path.exists() else 0)} lines | Last updated: {time.strftime('%H:%M:%S')}")
    
    # Auto-refresh with faster interval
    if auto_refresh:
        time.sleep(3)
        st.rerun()

# =============================================================================
# FOOTER
# =============================================================================

st.markdown("---")
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    st.caption(f"**IB AI Trader** v2.0")
with col_f2:
    st.caption(f"Model: GPT-5 + Web Search")
with col_f3:
    st.caption(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
