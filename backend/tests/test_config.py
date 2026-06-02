"""Config validation + safety rules."""
import pytest

from app.config.manager import ConfigError, ConfigManager
from app.config.schema import AppConfig
from app.core.enums import TradingMode


def test_defaults_load_and_on_symbol_is_string():
    cm = ConfigManager()
    cfg = cm.config
    # "ON" (ON Semiconductor) must survive YAML parsing as a string, not bool True.
    assert "ON" in cfg.universe.semiconductor_symbols
    assert cfg.risk.max_daily_loss_usd == 100.0
    assert cfg.risk.max_premium_per_contract_usd == 200.0
    assert cfg.default_mode == TradingMode.SHADOW


def test_default_mode_cannot_be_live():
    with pytest.raises(Exception):
        AppConfig.model_validate({"default_mode": "LIVE"})


def test_invalid_risk_rejected():
    with pytest.raises(Exception):
        AppConfig.model_validate({"risk": {"max_daily_loss_usd": -1}})


def test_spread_preferred_must_be_le_max():
    with pytest.raises(Exception):
        AppConfig.model_validate({"options": {"max_spread_pct": 5, "preferred_spread_pct": 8}})


def test_scalp_targets_strong_ge_first():
    with pytest.raises(Exception):
        AppConfig.model_validate(
            {"execution": {"first_profit_target_pct": 40, "strong_profit_target_pct": 20}}
        )


def test_cannot_loosen_risk_during_live_session():
    cm = ConfigManager()
    loosened = cm.config.model_copy(deep=True)
    loosened.risk.max_daily_loss_usd = 500.0  # loosening the loss cap
    with pytest.raises(ConfigError):
        cm.assert_not_loosening_risk(loosened, active_mode=TradingMode.LIVE)
    # Same change is allowed when not live.
    cm.assert_not_loosening_risk(loosened, active_mode=TradingMode.SHADOW)


def test_can_tighten_risk_during_live_session():
    cm = ConfigManager()
    tightened = cm.config.model_copy(deep=True)
    tightened.risk.max_daily_loss_usd = 50.0  # tighter is always allowed
    cm.assert_not_loosening_risk(tightened, active_mode=TradingMode.LIVE)
