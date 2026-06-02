"""Structured logging setup.

Logs are line-oriented and component-tagged so the audit trail and the journal
remain greppable. Account identifiers are masked by ``mask_account``.
"""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def mask_account(account_id: str | None) -> str:
    """Mask an account identifier for logs (e.g. ``U12***789``)."""
    if not account_id:
        return "<none>"
    if len(account_id) <= 4:
        return "***"
    return f"{account_id[:3]}***{account_id[-3:]}"
