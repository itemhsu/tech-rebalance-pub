"""Phase 1 單元測試 — 對應計劃書 U-01 ~ U-05。

只測 base.py 的 ABC 與 dataclass 行為，不碰網路。
"""
import pytest

from brokers.base import (
    AccountBalance, Position, OrderResult,
    BrokerClient, BrokerCapabilityError, BrokerError,
)


# ── U-01 ───────────────────────────────────────────────────────────────
def test_base_engine_abstract():
    """BrokerClient 不可直接實例化（含 abstract methods）。"""
    with pytest.raises(TypeError, match="abstract"):
        BrokerClient({}, {}, "paper")  # type: ignore


# ── U-02 ───────────────────────────────────────────────────────────────
def test_dataclass_account_balance():
    """AccountBalance 初始化 + repr 不含敏感資訊。"""
    b = AccountBalance(nav=10000.0, cash=2500.0, buying_power=5000.0)
    assert b.nav == 10000.0
    assert b.cash == 2500.0
    assert b.currency == "USD"

    r = repr(b)
    assert "10000.00" in r
    assert "2500.00" in r
    # 確認沒洩露非預期欄位
    assert "secret" not in r.lower()


# ── U-03 ───────────────────────────────────────────────────────────────
def test_dataclass_position_auto_market_value():
    """Position 若不給 market_value，由 qty × current_price 自動算。"""
    p = Position(symbol="AAPL", qty=10, avg_entry_price=200.0, current_price=210.0)
    assert p.market_value == 2100.0


def test_dataclass_position_explicit_market_value():
    """明確給 market_value 時不被覆蓋。"""
    p = Position(symbol="AAPL", qty=10, avg_entry_price=200.0,
                 current_price=210.0, market_value=999.99)
    assert p.market_value == 999.99


# ── U-04 ───────────────────────────────────────────────────────────────
def test_dataclass_order_result_defaults():
    """OrderResult 預設值。"""
    o = OrderResult(order_id="abc", symbol="AAPL", side="buy", qty=1)
    assert o.status == "new"
    assert o.filled_qty == 0.0
    assert o.filled_avg_price == 0.0
    assert o.raw == {}


# ── U-05 ───────────────────────────────────────────────────────────────
def test_capabilities_check_fractional_rejected():
    """spec capabilities.fractional_shares=False 時，traits 應拒絕零股。"""

    class StubClient(BrokerClient):
        def is_trading_day(self, target_date=None): return True
        def get_account_balance(self): return AccountBalance(0, 0)
        def get_positions(self): return []
        def get_latest_prices(self, symbols): return {}
        def place_order(self, symbol, qty, side, **kw):
            self.check_capability("fractional_shares", qty != int(qty))
            return OrderResult(order_id="x", symbol=symbol, side=side, qty=qty)
        def cancel_all_open_orders(self): return 0
        def wait_for_fills(self, order_ids, timeout_seconds=120): pass

    spec = {
        "id": "stub",
        "environments": {"paper": {}},
        "capabilities": {"fractional_shares": False},
    }
    c = StubClient(spec, env={}, environment="paper")

    # 整股 OK
    r = c.place_order("AAPL", 1, "buy")
    assert r.qty == 1

    # 零股應拒絕
    with pytest.raises(BrokerCapabilityError, match="零股"):
        c.place_order("AAPL", 0.5, "buy")


def test_capabilities_check_time_in_force():
    """time_in_force 不在 allowed list 時拒絕。"""

    class StubClient(BrokerClient):
        def is_trading_day(self, target_date=None): return True
        def get_account_balance(self): return AccountBalance(0, 0)
        def get_positions(self): return []
        def get_latest_prices(self, symbols): return {}
        def place_order(self, symbol, qty, side, **kw): pass
        def cancel_all_open_orders(self): return 0
        def wait_for_fills(self, order_ids, timeout_seconds=120): pass

    spec = {
        "id": "stub",
        "environments": {"paper": {}},
        "capabilities": {"time_in_force": ["day", "gtc"]},
    }
    c = StubClient(spec, env={}, environment="paper")
    c.check_capability("time_in_force", "day")          # OK
    with pytest.raises(BrokerCapabilityError):
        c.check_capability("time_in_force", "ext_hours") # 不允許


# ── 其他 ───────────────────────────────────────────────────────────────
def test_invalid_environment_raises():
    """env 不在 spec.environments 時拋 ValueError。"""

    class StubClient(BrokerClient):
        def is_trading_day(self, target_date=None): return True
        def get_account_balance(self): return AccountBalance(0, 0)
        def get_positions(self): return []
        def get_latest_prices(self, symbols): return {}
        def place_order(self, symbol, qty, side, **kw): pass
        def cancel_all_open_orders(self): return 0
        def wait_for_fills(self, order_ids, timeout_seconds=120): pass

    spec = {"id": "stub", "environments": {"paper": {}, "live": {}}}
    with pytest.raises(ValueError, match="environment"):
        StubClient(spec, env={}, environment="dev")


def test_mask_secret_helper():
    """_mask_secret 正確遮蔽。"""
    assert BrokerClient._mask_secret("abc") == "***"           # 太短全遮
    assert BrokerClient._mask_secret("abcdefghi") == "ab***hi"
    assert BrokerClient._mask_secret("") == ""


def test_repr_no_secrets():
    """__repr__ 不洩露任何 env 內容。"""

    class StubClient(BrokerClient):
        def is_trading_day(self, target_date=None): return True
        def get_account_balance(self): return AccountBalance(0, 0)
        def get_positions(self): return []
        def get_latest_prices(self, symbols): return {}
        def place_order(self, symbol, qty, side, **kw): pass
        def cancel_all_open_orders(self): return 0
        def wait_for_fills(self, order_ids, timeout_seconds=120): pass

    spec = {"id": "stub", "environments": {"paper": {}}}
    c = StubClient(spec, env={"API_SECRET": "SUPER_SECRET_xyz"}, environment="paper")
    r = repr(c)
    assert "SUPER_SECRET_xyz" not in r
    assert "stub" in r
