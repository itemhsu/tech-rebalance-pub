"""驗證 AlpacaClient 的向下相容方法：

讓 main.py（從 tr.client_from_env 切換到 build_client_for_account 後）
與 trader.execute_rebalance 都能繼續無痛運作。
"""
import pytest

responses = pytest.importorskip("responses")

from brokers.alpaca_client import AlpacaClient
from brokers.registry import load_broker_spec


SPEC = load_broker_spec("alpaca")
ENV = {"API_KEY": "PK_TEST", "API_SECRET": "SECRET_TEST"}
PAPER = "https://paper-api.alpaca.markets"


def _client():
    return AlpacaClient(spec=SPEC, env=ENV, environment="paper")


# ── compat-01: get_account_nav 回傳 (nav, cash) ─────────────────────────
@responses.activate
def test_compat_get_account_nav_returns_tuple():
    responses.add(
        responses.GET, f"{PAPER}/v2/account",
        json={"portfolio_value": "100000", "cash": "25000",
              "buying_power": "50000", "currency": "USD"},
        status=200,
    )
    result = _client().get_account_nav()
    assert isinstance(result, tuple)
    assert len(result) == 2
    nav, cash = result
    assert nav == 100000.0
    assert cash == 25000.0


# ── compat-02: get_current_positions 回傳 portfolio.Position ─────────
@responses.activate
def test_compat_get_current_positions_returns_portfolio_position():
    from portfolio import Position as _PortfolioPosition
    responses.add(
        responses.GET, f"{PAPER}/v2/positions",
        json=[
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "200",
             "current_price": "210", "market_value": "2100",
             "unrealized_pl": "100", "unrealized_plpc": "0.05"},
        ],
        status=200,
    )
    positions = _client().get_current_positions()
    assert len(positions) == 1
    p = positions[0]
    # 必須是 portfolio.Position 不是 brokers.base.Position
    assert isinstance(p, _PortfolioPosition)
    assert p.symbol == "AAPL"
    assert p.qty == 10
    assert p.unrealized_pl == 100


# ── compat-03: submit_market_order 回傳 dict 含 'id' ─────────────────
@responses.activate
def test_compat_submit_market_order_returns_dict():
    responses.add(
        responses.POST, f"{PAPER}/v2/orders",
        json={"id": "ord-xyz", "status": "new"},
        status=200,
    )
    result = _client().submit_market_order("AAPL", 1, "buy", time_in_force="day")
    assert isinstance(result, dict)
    assert result["id"] == "ord-xyz"


# ── compat-04: get_open_orders 回傳 list ─────────────────────────────
@responses.activate
def test_compat_get_open_orders_returns_list():
    responses.add(
        responses.GET, f"{PAPER}/v2/orders",
        json=[
            {"id": "o1", "symbol": "AAPL", "status": "new", "side": "buy"},
            {"id": "o2", "symbol": "NVDA", "status": "accepted", "side": "sell"},
        ],
        status=200,
    )
    orders = _client().get_open_orders()
    assert len(orders) == 2
    assert orders[0]["symbol"] == "AAPL"


# ── compat-05: build_client_for_account 回的 client 可被 main.py 用 ────
def test_compat_main_py_can_use_broker_client(monkeypatch):
    """模擬 main.py 啟動流程：能 build client 並呼叫 main.py 用到的 method 名。"""
    monkeypatch.setenv("ACC1_API_KEY", "PK")
    monkeypatch.setenv("ACC1_API_SECRET", "SECRET")
    from brokers.from_env import build_client_for_account
    client = build_client_for_account("1")
    # main.py 會用這幾個方法名：
    for name in ("is_trading_day", "get_account_nav", "get_current_positions"):
        assert hasattr(client, name), f"client 缺方法 {name}"
        assert callable(getattr(client, name))
