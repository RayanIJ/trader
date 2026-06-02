# Automated Options Trading Cockpit

A **local, single-user, browser-based** automated options trading app focused on
**SPX and the semiconductor sector**, specializing in **0DTE / short-hold
momentum scalps** (1–5 minute holds). It connects to Interactive Brokers through
the **TWS socket API** (`ibapi`), and is built as a **probabilistic, rule-based,
risk-controlled** system — not a "100% accuracy" promise.

> Design principle: **the app prefers missing a trade over taking a bad one.**
> "No Trade" is a normal, visible outcome. The signal engine *proposes*; the
> risk engine *disposes*. No signal reaches execution without passing every gate.

This repository also contains a legacy Python/Streamlit AI scalper under `src/`
(stock trading via the TWS socket API). The cockpit **reuses** that broker layer
but is otherwise a fresh, modular build under `backend/` and `frontend/`.

---

## Status — Phases 1–6 complete

| Phase | Scope | State |
|------|-------|-------|
| **1** | Project setup, config system, DB schema (17 entities), system-health dashboard, IBKR connection status, Shadow mode | ✅ Done |
| **2** | Market data ingestion, option chain builder, scanner universe, feature engine | ✅ Done |
| **3** | Signal engine + scoring, no-trade filters, scanner dashboard | ✅ Done |
| **4** | Risk engine, daily-loss lockout, premium cap, cooldowns, macro guard, behavior state | ✅ Done |
| **5** | Execution engine, order state machine, position/exit engine, paper/live via TWS | ✅ Done |
| **6** | Audit journal, EOD summary, backtest/replay, trade persistence to SQLite | ✅ Done |

**Current capabilities:** local backend + browser dashboard with live TWS market data
(equities via tick-by-tick, indices/options via streaming `reqMktData`), scanner with
GO/WATCH badges, risk/macro gates, shadow/paper/live execution with 0DTE scalping exits,
emergency stop, session auto-recovery, journal + EOD summary, and deterministic backtest
replay via `POST /api/backtest/run`.

---

## Architecture

```
Frontend (Next.js)  ──HTTP/WS──▶  Backend API (FastAPI)
                                      │
   Orchestrator · Signal · Risk(veto) · Execution · Health · Mode manager
   Feature · Macro · News · OrderStateMachine · Position · Journal/Audit
                                      │
                          Broker Adapter (Shadow/Paper/Live)
                                      │
                     TWS socket API transport (src/ib TradingApp)
```

- **Strict separation:** strategy logic, risk logic, execution logic, and broker
  connectivity are independent modules. Only the broker adapter touches IBKR.
- **Modes:** `SHADOW` (signals only, never sends orders — default), `PAPER`
  (paper port 7497), `LIVE` (live port 7496, explicit enable only). A lockout,
  session failure, data failure, or risk breach auto-drops the app to Shadow.

### Scalping behavior (binds Phases 3 & 5)

Encoded in `backend/app/config/defaults.yaml` and validated by the schema:

- **Holding:** 1–5 min target; **hard time stop 300s**; **fast-failure exit 30–90s**
  if premium doesn't move favorably; immediate exit on setup invalidation, stop,
  spread widening, stale data, or broker instability.
- **No late entry:** reject if the move already traveled >70% of the expected
  scalp distance, if the premium already expanded >25%, if the trigger candle is
  >2× the recent 1-min body, or if entry would require chasing.
- **Exits (% of entry premium):** first target +20%, strong target +40%, stop
  −25%, give-back 10% from peak after a target. **Never hold to close; never turn
  a scalp into a swing; flatten before high-impact macro events.**
- **Sizing:** long calls/puts only, max **$200/contract** (`max_ask = 200/multiplier`,
  blocked if multiplier missing), max **$100 daily loss** (hard, non-bypassable).
  Reject if the stop's dollar risk exceeds the remaining daily allowance.

---

## Setup

Choose **Docker** (recommended — IB Gateway + backend + frontend) or **local dev** below.

### Docker (full stack)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) and a `.env`
with IBKR credentials (`TWS_USERID`, `TWS_PASSWORD`). See `.env.docker.example`.

```bash
# Stop any host-native backend/frontend on ports 8000/3000 first.
docker compose up -d --build

# Dashboard: http://127.0.0.1:3000
# API:       http://127.0.0.1:8000
# IB 2FA:    VNC localhost:5900  (password = VNC_PASSWORD in .env, default 123456)
```

Services:

| Container | Role |
|-----------|------|
| `ib-gateway` | IBKR login + TWS API (socat relays on 4003 live / 4004 paper) |
| `trading-cockpit-backend` | FastAPI cockpit (`./data` persisted on host) |
| `trading-cockpit-frontend` | Next.js dashboard |

Logs: `docker compose logs -f backend` · Stop: `docker compose down`

**Troubleshooting**

- Open the dashboard at **http://127.0.0.1:3000** or **http://localhost:3000** (either works after the CORS/proxy fix).
- REST calls are proxied through the frontend container (`/api/*` → backend). WebSocket still connects to port **8000** on your host.
- IB Gateway needs **2FA** on first login: connect a VNC client to `localhost:5900` (password = `VNC_PASSWORD` in `.env`, default `123456`). Health stays **DOWN** until login completes.
- If IB was already logged in elsewhere, approve the competing-session prompt or rely on `EXISTING_SESSION_DETECTED_ACTION=primary`.
- Stop any host-native backend on port 8000 before starting Docker (`python -m app.main` in a terminal).

The legacy Streamlit scalper stack is in `docker-compose.legacy.yml`.

### Local development

#### Prerequisites
- Python 3.11+ (tested on 3.14), Node 18+ (tested on 25)
- Interactive Brokers **TWS** or **IB Gateway** running locally with the API
  socket enabled (paper 7497 / live 7496). Auth is **not** automated — log in
  manually; the dashboard shows session status and blocks trading until ready.

### Backend
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example ../.env.cockpit   # optional; see env vars below
python -m app.main                # serves http://127.0.0.1:8000 (localhost only)
```

### Frontend
```bash
cd frontend
npm install
npm run dev                       # http://127.0.0.1:3000
```

Open **http://127.0.0.1:3000**. Click **Connect** under "IBKR (TWS Socket)".
With TWS/Gateway down you'll see IB components red and the pre-trade gate
**BLOCKED** — expected.

### Tests
```bash
cd backend && source .venv/bin/activate && python -m pytest -q
```

### Key API endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | System + broker health, mode, lockout |
| `GET /api/scanner` | Latest scan result |
| `POST /api/scanner/scan` | Force rescan |
| `GET /api/risk/status` | Daily P/L, behavior, macro block |
| `GET /api/execution/status` | Automation flag, active position |
| `POST /api/execution/automation` | Enable/disable auto entries |
| `GET /api/journal` | Recent audit log entries |
| `GET /api/journal/summary` | End-of-day summary |
| `POST /api/backtest/run` | Replay scanner over simulated data |
| `GET /api/macro/events` | Upcoming macro events (from DB) |
| `POST /api/macro/events` | Add a macro block window |

---

## Environment variables (backend)

All services bind to **localhost** by default; nothing is exposed publicly and no
credentials are hardcoded. Secrets are encrypted at rest under `data/`.

| Var | Default | Purpose |
|-----|---------|---------|
| `BACKEND_HOST` | `127.0.0.1` | API bind address (keep local) |
| `BACKEND_PORT` | `8000` | API port |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | CORS allow-origin |
| `TRADER_SECRET_KEY` | *(auto-generated)* | Fernet key for the encrypted secret store |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MARKET_DATA_SOURCE` | `simulated` | `tws` for live IB data, `simulated` for offline |
| `IB_HOST` / `IB_PORT` | `127.0.0.1` / `7497` | TWS/Gateway socket (see `.env`) |

Frontend: `NEXT_PUBLIC_BACKEND_URL` (default `http://127.0.0.1:8000`).

---

## Safety guarantees (Phase 1)

- Default mode is **Shadow**; the app can **never default to Live**.
- Live requires explicit confirmation **and** a tradable broker session.
- **Emergency Stop** forces Shadow + a non-bypassable session lockout.
- Risk limits **cannot be loosened** while a Live session is active.
- Invalid config is rejected and the last-known-good config is retained.
- Delayed/stale market data blocks new trades (`require_live_data`).
