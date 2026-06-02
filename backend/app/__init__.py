"""Automated options trading cockpit — FastAPI backend.

Modular, risk-first architecture. The signal engine proposes, the risk engine
disposes; no signal reaches execution without passing every gate. The broker
adapter is the only component that talks to Interactive Brokers (TWS socket API).
"""

__version__ = "0.1.0"
