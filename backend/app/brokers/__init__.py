"""Broker connectivity. The ONLY layer that talks to Interactive Brokers.

Transport is the existing TWS socket API (``ibapi`` via src/ib). Mode-specific
adapters (Shadow/Paper/Live) decide whether orders are actually transmitted;
the transport itself is identical. Order placement arrives in Phase 5/6 — in
Phase 1 these adapters expose connection, session, and data-feed status only.
"""
