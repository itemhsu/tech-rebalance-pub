"""tests/test_trader.py — Alpaca API 整合測試（使用 responses mock）"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import responses as resp_mock

from trader import AlpacaClient, AuthenticationError, PAPER_URL


FAKE_KEY    = "PKTEST123"
FAKE_SECRET = "SECRET123"


def make_client() -> AlpacaClient:
    return AlpacaClient(api_key=FAKE_KEY, secret_key=FAKE_SECRET, base_url=PAPER_URL)


# ── 交易日曆 ──────────────────────────────────────────────────────────────────
class TestIsTradingDay:
    @resp_mock.activate
    def test_trading_day_returns_true(self):
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/calendar",
            json=[{"date": "2026-05-05", "open": "09:30", "close": "16:00"}],
            status=200,
        )
        client = make_client()
        from datetime import date
        assert client.is_trading_day(date(2026, 5, 5)) is True

    @resp_mock.activate
    def test_non_trading_day_returns_false(self):
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/calendar",
            json=[],   # 空陣列 = 非交易日
            status=200,
        )
        client = make_client()
        from datetime import date
        assert client.is_trading_day(date(2026, 5, 3)) is False   # 週六


# ── 帳戶 ──────────────────────────────────────────────────────────────────────
class TestGetAccount:
    @resp_mock.activate
    def test_returns_equity_and_cash(self):
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/account",
            json={"equity": "102345.67", "cash": "1234.56", "portfolio_value": "102345.67"},
            status=200,
        )
        client = make_client()
        nav, cash = client.get_account_nav()
        assert nav  == pytest.approx(102345.67)
        assert cash == pytest.approx(1234.56)

    @resp_mock.activate
    def test_auth_error_raises(self):
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/account",
            json={"message": "forbidden"},
            status=401,
        )
        client = make_client()
        with pytest.raises(AuthenticationError):
            client.get_account()


# ── 持倉 ──────────────────────────────────────────────────────────────────────
class TestGetPositions:
    @resp_mock.activate
    def test_returns_positions(self):
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/positions",
            json=[{
                "symbol": "AAPL",
                "qty": "10.5",
                "avg_entry_price": "185.00",
                "current_price": "192.00",
                "market_value": "2016.00",
                "unrealized_pl": "73.50",
            }],
            status=200,
        )
        client    = make_client()
        positions = client.get_current_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].qty    == pytest.approx(10.5)

    @resp_mock.activate
    def test_empty_positions(self):
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/positions",
            json=[],
            status=200,
        )
        client    = make_client()
        positions = client.get_current_positions()
        assert positions == []


# ── 訂單 ──────────────────────────────────────────────────────────────────────
class TestSubmitOrder:
    @resp_mock.activate
    def test_buy_order_fractional(self):
        resp_mock.add(
            resp_mock.POST,
            f"{PAPER_URL}/v2/orders",
            json={
                "id": "abc-123",
                "symbol": "AAPL",
                "qty": "5.500000000",
                "side": "buy",
                "status": "accepted",
            },
            status=201,
        )
        client = make_client()
        result = client.submit_market_order("AAPL", 5.5, "buy")
        assert result["id"] == "abc-123"
        # 驗證 qty 以字串格式傳送
        body = json.loads(resp_mock.calls[0].request.body)
        assert isinstance(body["qty"], str)
        assert body["side"] == "buy"
        assert body["type"] == "market"

    @resp_mock.activate
    def test_sell_order(self):
        resp_mock.add(
            resp_mock.POST,
            f"{PAPER_URL}/v2/orders",
            json={"id": "def-456", "symbol": "MSFT", "side": "sell", "status": "accepted"},
            status=201,
        )
        client = make_client()
        result = client.submit_market_order("MSFT", 10.0, "sell")
        assert result["id"] == "def-456"

    @resp_mock.activate
    def test_order_failure_returns_empty(self):
        resp_mock.add(
            resp_mock.POST,
            f"{PAPER_URL}/v2/orders",
            json={"message": "insufficient funds"},
            status=422,
        )
        client = make_client()
        result = client.submit_market_order("AAPL", 99999.0, "buy")
        assert result == {}


# ── 市場資料（收盤價）────────────────────────────────────────────────────────
class TestFetchPrices:
    @resp_mock.activate
    def test_returns_prices(self):
        from market_cap import fetch_latest_prices
        resp_mock.add(
            resp_mock.GET,
            "https://data.alpaca.markets/v2/stocks/bars/latest",
            json={"bars": {
                "AAPL": [{"c": 192.35, "o": 190.0, "h": 194.0, "l": 189.0, "v": 100000}],
                "MSFT": [{"c": 401.22, "o": 399.0, "h": 405.0, "l": 397.0, "v": 80000}],
            }},
            status=200,
        )
        prices = fetch_latest_prices(["AAPL", "MSFT"], FAKE_KEY, FAKE_SECRET)
        assert prices["AAPL"] == pytest.approx(192.35)
        assert prices["MSFT"] == pytest.approx(401.22)

    @resp_mock.activate
    def test_missing_symbol_excluded(self):
        from market_cap import fetch_latest_prices
        resp_mock.add(
            resp_mock.GET,
            "https://data.alpaca.markets/v2/stocks/bars/latest",
            json={"bars": {"AAPL": [{"c": 192.35, "o": 190.0, "h": 194.0, "l": 189.0, "v": 100000}]}},
            status=200,
        )
        prices = fetch_latest_prices(["AAPL", "MSFT"], FAKE_KEY, FAKE_SECRET)
        assert "MSFT" not in prices
        assert "AAPL" in prices


# ── Rate limit 退避 ──────────────────────────────────────────────────────────
class TestRateLimitRetry:
    @resp_mock.activate
    def test_retries_on_429(self):
        """HTTP 429 後應重試，最終成功"""
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/account",
            json={"message": "rate limit"},
            status=429,
        )
        resp_mock.add(
            resp_mock.GET,
            f"{PAPER_URL}/v2/account",
            json={"equity": "100000.00", "cash": "1000.00"},
            status=200,
        )
        client = make_client()
        # 第一次 429，第二次成功
        acc = client.get_account()
        assert acc["equity"] == "100000.00"
        assert len(resp_mock.calls) == 2
