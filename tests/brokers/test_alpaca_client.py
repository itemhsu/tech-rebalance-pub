"""Phase 1 整合測試 — 對應計劃書 I-01 ~ I-10。

用 responses 庫 mock HTTP，不打真實 API。
"""
import json as _json
import pytest

responses = pytest.importorskip("responses")

from brokers.alpaca_client import AlpacaClient
from brokers.base import (
    AccountBalance, BrokerAuthError, BrokerCapabilityError,
    BrokerError, BrokerRateLimitError, Position, OrderResult,
)
from brokers.registry import load_broker_spec


SPEC = load_broker_spec("alpaca")
ENV = {"API_KEY": "PK_TEST", "API_SECRET": "SECRET_TEST"}
PAPER = "https://paper-api.alpaca.markets"
DATA  = "https://data.alpaca.markets"


def _client():
    return AlpacaClient(spec=SPEC, env=ENV, environment="paper")


# ── I-01 ───────────────────────────────────────────────────────────────
@responses.activate
def test_get_account_balance_ok():
    responses.add(
        responses.GET, f"{PAPER}/v2/account",
        json={"portfolio_value": "100000.50", "cash": "25000.25",
              "buying_power": "50000.00", "currency": "USD"},
        status=200,
    )
    b = _client().get_account_balance()
    assert isinstance(b, AccountBalance)
    assert b.nav == 100000.50
    assert b.cash == 25000.25
    assert b.buying_power == 50000.00


# ── I-02 ───────────────────────────────────────────────────────────────
@responses.activate
def test_get_positions_empty():
    responses.add(responses.GET, f"{PAPER}/v2/positions", json=[], status=200)
    assert _client().get_positions() == []


# ── I-03 ───────────────────────────────────────────────────────────────
@responses.activate
def test_get_positions_multiple():
    responses.add(
        responses.GET, f"{PAPER}/v2/positions",
        json=[
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "200",
             "current_price": "210", "market_value": "2100",
             "unrealized_pl": "100", "unrealized_plpc": "0.05"},
            {"symbol": "NVDA", "qty": "5",  "avg_entry_price": "100",
             "current_price": "150", "market_value": "750"},
        ],
        status=200,
    )
    pos = _client().get_positions()
    assert len(pos) == 2
    assert pos[0].symbol == "AAPL"
    assert pos[0].qty == 10
    assert pos[0].unrealized_pl == 100
    assert pos[1].symbol == "NVDA"


# ── I-04 ───────────────────────────────────────────────────────────────
@responses.activate
def test_place_market_order_ok():
    responses.add(
        responses.POST, f"{PAPER}/v2/orders",
        json={"id": "abc-123", "status": "new", "filled_qty": "0"},
        status=200,
    )
    r = _client().place_order("AAPL", qty=1, side="buy")
    assert isinstance(r, OrderResult)
    assert r.order_id == "abc-123"
    assert r.status == "new"
    assert r.symbol == "AAPL"


# ── I-05 ───────────────────────────────────────────────────────────────
@responses.activate
def test_place_order_insufficient_funds():
    responses.add(
        responses.POST, f"{PAPER}/v2/orders",
        json={"message": "insufficient buying power"},
        status=403,
    )
    with pytest.raises(BrokerAuthError, match="403"):
        _client().place_order("AAPL", qty=1, side="buy")


# ── I-06 ───────────────────────────────────────────────────────────────
@responses.activate
def test_place_order_rate_limit_then_success(monkeypatch):
    # 第一次 429，第二次 200
    responses.add(responses.POST, f"{PAPER}/v2/orders",
                  json={"message": "too many"}, status=429)
    responses.add(responses.POST, f"{PAPER}/v2/orders",
                  json={"id": "ok-1", "status": "new"}, status=200)
    # 加速 backoff 等待
    import brokers.alpaca_client as ac
    monkeypatch.setattr(ac, "_BASE_BACKOFF", 0.01)
    r = _client().place_order("AAPL", qty=1, side="buy")
    assert r.order_id == "ok-1"
    assert len(responses.calls) == 2


# ── I-07 ───────────────────────────────────────────────────────────────
@responses.activate
def test_cancel_all_orders():
    responses.add(
        responses.DELETE, f"{PAPER}/v2/orders",
        json=[{"id": "x1", "status": "207"}, {"id": "x2", "status": "207"}],
        status=207,
    )
    n = _client().cancel_all_open_orders()
    assert n == 2


# ── I-08 ───────────────────────────────────────────────────────────────
@responses.activate
def test_is_trading_day_true():
    from datetime import date
    today = date.today()
    responses.add(
        responses.GET, f"{PAPER}/v2/calendar",
        json=[{"date": today.isoformat(), "open": "09:30", "close": "16:00"}],
        status=200,
    )
    assert _client().is_trading_day(today) is True


# ── I-09 ───────────────────────────────────────────────────────────────
@responses.activate
def test_is_trading_day_false():
    from datetime import date
    responses.add(responses.GET, f"{PAPER}/v2/calendar", json=[], status=200)
    assert _client().is_trading_day(date(2024, 1, 1)) is False  # 新年


# ── I-10 ───────────────────────────────────────────────────────────────
@responses.activate
def test_get_latest_prices_batch():
    responses.add(
        responses.GET, f"{DATA}/v2/stocks/bars/latest",
        json={"bars": {
            "AAPL": {"c": 210.5, "h": 211, "l": 209, "o": 210, "v": 1000000},
            "NVDA": {"c": 152.3},
        }},
        status=200,
    )
    prices = _client().get_latest_prices(["AAPL", "NVDA"])
    assert prices == {"AAPL": 210.5, "NVDA": 152.3}


# ── 額外：capability 守門 ───────────────────────────────────────────────
def test_place_fractional_when_allowed():
    """Alpaca 支援 fractional → qty=0.5 不該被 reject。"""
    @responses.activate
    def _inner():
        responses.add(responses.POST, f"{PAPER}/v2/orders",
                      json={"id": "frac-1", "status": "new"}, status=200)
        r = _client().place_order("AAPL", qty=0.5, side="buy")
        assert r.order_id == "frac-1"
    _inner()


def test_place_unsupported_order_type():
    """傳不在 capabilities.order_types 的 type → BrokerCapabilityError，不送 API。"""
    with pytest.raises(BrokerCapabilityError, match="order_types"):
        _client().place_order("AAPL", 1, "buy", order_type="iceberg")
