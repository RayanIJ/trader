"""Configuration manager.

Loads YAML, validates against the schema, hashes and versions every accepted
config into the database, and enforces the safety rule that risk limits cannot
be loosened while a Live session is active. Invalid config is rejected and the
last-known-good config is retained.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schema import AppConfig
from app.core.enums import TradingMode
from app.core.logging import get_logger

logger = get_logger("config")

DEFAULTS_PATH = Path(__file__).with_name("defaults.yaml")


class ConfigError(Exception):
    """Raised when a config payload is invalid or violates a safety rule."""


def _hash_config(cfg: AppConfig) -> str:
    payload = json.dumps(cfg.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Risk fields where a larger number means *more* risk (loosening).
_RISK_LOOSEN_IF_LARGER = {
    "max_daily_loss_usd",
    "max_premium_per_contract_usd",
    "max_open_positions",
    "max_position_per_underlying",
    "max_total_premium_exposure_usd",
}
# Cooldowns: smaller means more risk (loosening).
_RISK_LOOSEN_IF_SMALLER = {
    "cooldown_after_trade_sec",
    "cooldown_after_loss_sec",
    "cooldown_same_underlying_sec",
}


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULTS_PATH
        self._config: AppConfig = self.load()

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def version_hash(self) -> str:
        return _hash_config(self._config)

    def load(self) -> AppConfig:
        """Load and validate config from disk; raise ConfigError on failure."""
        try:
            raw = yaml.safe_load(self._path.read_text()) or {}
        except FileNotFoundError:
            logger.warning("config file %s not found; using schema defaults", self._path)
            raw = {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"config YAML is invalid: {exc}") from exc
        try:
            cfg = AppConfig.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(f"config failed validation: {exc}") from exc
        self._apply_broker_env_overrides(cfg)
        self._apply_market_data_env_overrides(cfg)
        self._config = cfg
        logger.info(
            "config loaded (version=%s, mode_default=%s, broker=%s:%s/%s)",
            _hash_config(cfg), cfg.default_mode, cfg.broker.host,
            cfg.broker.paper_port, cfg.broker.live_port,
        )
        return cfg

    @staticmethod
    def _apply_broker_env_overrides(cfg: AppConfig) -> None:
        """Let environment variables drive the broker connection.

        Mirrors the legacy app's .env (IB_HOST/IB_PORT/IB_CLIENT_ID) so the same
        VPS/Docker setup connects without editing YAML. ``IB_PORT`` (legacy single
        port) maps to BOTH paper and live ports only when the explicit
        IB_PAPER_PORT/IB_LIVE_PORT are not provided; prefer the explicit vars.
        """
        host = os.environ.get("IB_HOST")
        if host:
            cfg.broker.host = host
        cid = os.environ.get("IB_CLIENT_ID")
        if cid and cid.isdigit():
            cfg.broker.client_id = int(cid)

        paper = os.environ.get("IB_PAPER_PORT")
        live = os.environ.get("IB_LIVE_PORT")
        legacy = os.environ.get("IB_PORT")
        if paper and paper.isdigit():
            cfg.broker.paper_port = int(paper)
        if live and live.isdigit():
            cfg.broker.live_port = int(live)
        if legacy and legacy.isdigit() and not (paper or live):
            # Legacy single-port .env: apply to whichever port matches the
            # connection you intend. We map it to the live port (the old
            # docker-compose used IB_PORT=4001 = live) and leave paper as-is,
            # so Shadow/Paper still default to the safer paper port.
            logger.warning(
                "legacy IB_PORT=%s detected; mapping to live_port. Set "
                "IB_PAPER_PORT/IB_LIVE_PORT explicitly to avoid ambiguity.",
                legacy,
            )
            cfg.broker.live_port = int(legacy)

    @staticmethod
    def _apply_market_data_env_overrides(cfg: AppConfig) -> None:
        """Allow the market-data source + cadence to be set per-machine via env.

        Keeps the code default ``simulated`` (offline + deterministic for tests)
        while letting this machine opt into the live TWS feed with
        ``MARKET_DATA_SOURCE=tws`` in .env.
        """
        source = os.environ.get("MARKET_DATA_SOURCE")
        if source in ("simulated", "tws"):
            cfg.market_data.source = source
        interval = os.environ.get("MARKET_DATA_SCAN_INTERVAL_SEC")
        if interval:
            try:
                val = float(interval)
                if val > 0:
                    cfg.market_data.scan_interval_sec = val
            except ValueError:
                logger.warning("invalid MARKET_DATA_SCAN_INTERVAL_SEC=%s ignored", interval)

    def validate_payload(self, raw: dict) -> AppConfig:
        try:
            return AppConfig.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

    def assert_not_loosening_risk(self, new_cfg: AppConfig, active_mode: TradingMode) -> None:
        """Block loosening risk limits while a Live session is active."""
        if active_mode != TradingMode.LIVE:
            return
        old, new = self._config.risk, new_cfg.risk
        for field in _RISK_LOOSEN_IF_LARGER:
            if getattr(new, field) > getattr(old, field):
                raise ConfigError(
                    f"cannot loosen risk.{field} from {getattr(old, field)} to "
                    f"{getattr(new, field)} during a Live session"
                )
        for field in _RISK_LOOSEN_IF_SMALLER:
            if getattr(new, field) < getattr(old, field):
                raise ConfigError(
                    f"cannot shorten risk.{field} from {getattr(old, field)} to "
                    f"{getattr(new, field)} during a Live session"
                )

    def apply(self, new_cfg: AppConfig, active_mode: TradingMode = TradingMode.SHADOW) -> str:
        """Validate the safety rules and swap in the new config. Returns version hash."""
        self.assert_not_loosening_risk(new_cfg, active_mode)
        self._config = new_cfg
        version = _hash_config(new_cfg)
        logger.info("config applied (version=%s)", version)
        return version
