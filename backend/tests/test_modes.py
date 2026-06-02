"""Mode gating: Live requires confirmation + tradable session; lockout is hard.

The broker is faked (via ``make_broker``) so these tests exercise the gating and
the connect-on-switch / rollback logic without needing a live gateway.
"""
import pytest

import app.modes.manager as manager_module
from app.brokers.adapter import BrokerStatus
from app.config.schema import BrokerConfig
from app.core.enums import DataFeedStatus, TradingMode
from app.modes.manager import ModeManager


class FakeBroker:
    """Minimal broker stand-in. ``connect_tradable`` controls post-connect health."""

    connect_tradable = True  # class-level switch shared via monkeypatch helper

    def __init__(self, mode: TradingMode) -> None:
        self.mode = mode
        self.connected = False

    def _status(self) -> BrokerStatus:
        tradable = self.connected and FakeBroker.connect_tradable
        return BrokerStatus(
            mode=self.mode,
            gateway_reachable=tradable,
            session_connected=tradable,
            next_valid_id_received=tradable,
            account_available=tradable,
            account_id="U1234567" if tradable else None,
            data_feed=DataFeedStatus.LIVE if tradable else DataFeedStatus.UNAVAILABLE,
        )

    async def connect(self) -> BrokerStatus:
        self.connected = True
        return self._status()

    async def disconnect(self) -> None:
        self.connected = False

    async def status(self) -> BrokerStatus:
        return self._status()


@pytest.fixture(autouse=True)
def _patch_make_broker(monkeypatch):
    FakeBroker.connect_tradable = True
    monkeypatch.setattr(manager_module, "make_broker", lambda mode, cfg: FakeBroker(mode))
    yield


def _tradable_status() -> BrokerStatus:
    return BrokerStatus(
        mode=TradingMode.LIVE,
        gateway_reachable=True,
        session_connected=True,
        next_valid_id_received=True,
        account_available=True,
        account_id="U1234567",
        data_feed=DataFeedStatus.LIVE,
    )


def _down_status() -> BrokerStatus:
    return BrokerStatus(mode=TradingMode.LIVE)


@pytest.mark.asyncio
async def test_default_mode_is_shadow():
    mm = ModeManager(BrokerConfig())
    assert mm.mode == TradingMode.SHADOW


@pytest.mark.asyncio
async def test_live_requires_confirmation():
    mm = ModeManager(BrokerConfig())
    res = await mm.switch_mode(TradingMode.LIVE, confirm_live=False, broker_status=_tradable_status())
    assert not res.ok
    assert mm.mode == TradingMode.SHADOW


@pytest.mark.asyncio
async def test_live_requires_tradable_session():
    FakeBroker.connect_tradable = False
    mm = ModeManager(BrokerConfig())
    res = await mm.switch_mode(TradingMode.LIVE, confirm_live=True, broker_status=_down_status())
    assert not res.ok
    assert mm.mode == TradingMode.SHADOW
    assert res.reason and "LIVE blocked" in res.reason


@pytest.mark.asyncio
async def test_live_allowed_when_confirmed_and_tradable():
    mm = ModeManager(BrokerConfig())
    res = await mm.switch_mode(TradingMode.LIVE, confirm_live=True, broker_status=_tradable_status())
    assert res.ok
    assert mm.mode == TradingMode.LIVE


@pytest.mark.asyncio
async def test_live_rolls_back_when_reconnect_not_tradable():
    # Pre-trade gate passes, but the new LIVE broker fails to become tradable
    # after connect -> we must roll back to SHADOW rather than stay LIVE.
    FakeBroker.connect_tradable = False
    mm = ModeManager(BrokerConfig())
    res = await mm.switch_mode(TradingMode.LIVE, confirm_live=True, broker_status=_tradable_status())
    assert not res.ok
    assert mm.mode == TradingMode.SHADOW


@pytest.mark.asyncio
async def test_emergency_stop_forces_shadow_and_locks_out():
    mm = ModeManager(BrokerConfig())
    await mm.switch_mode(TradingMode.PAPER)
    await mm.force_safe_mode("test emergency")
    assert mm.mode == TradingMode.SHADOW
    assert mm.locked_out
    # While locked out, only SHADOW is allowed.
    res = await mm.switch_mode(TradingMode.LIVE, confirm_live=True, broker_status=_tradable_status())
    assert not res.ok
    assert mm.mode == TradingMode.SHADOW


@pytest.mark.asyncio
async def test_clear_lockout_reenables_switching():
    mm = ModeManager(BrokerConfig())
    await mm.force_safe_mode("x")
    mm.clear_lockout()
    assert not mm.locked_out
