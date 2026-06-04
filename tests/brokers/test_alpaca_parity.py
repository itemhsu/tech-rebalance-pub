"""Phase B 安全核心：Alpaca 新舊 client parity（P-01 ~ P-07）。

同一份 alpaca.json spec + 同一組 mock HTTP 回應，
舊 AlpacaClient 與新 RestBrokerClient 必須產出相同結果。

P-01~P-04 任一不過 = 停工（4 個 live Alpaca 帳戶切引擎後不能有行為差異）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from brokers.alpaca_client import AlpacaClient
from brokers.rest_broker import RestBrokerClient
from brokers.base import BrokerAuthError, BrokerError

SPEC = json.loads((ROOT / "brokers" / "alpaca.json").read_text(encoding="utf-8"))
ENV = {"API_KEY": "PK_TEST", "API_SECRET": "SECRET_TEST"}


def _both():
    return AlpacaClient(SPEC, ENV, "paper"), RestBrokerClient(SPEC, ENV, "paper")


def _resp(status=200, json_data=None, ok=None):
    r = MagicMock()
    r.status_code = status
    r.ok = (200 <= status < 300) if ok is None else ok
    r.json.return_value = json_data if json_data is not None else {}
    r.text = ""
    return r


# ── P-01 balance ────────────────────────────────────────────────────────
def test_P01_balance_identical():
    acct = {"portfolio_value": "100000.50", "cash": "25000.25",
            "buying_power": "50000.00", "currency": "USD"}
    old, new = _both()
    with patch("brokers.alpaca_client.requests.request", return_value=_resp(json_data=acct)), \
         patch("brokers.rest_broker.requests.request", return_value=_resp(json_data=acct)):
        bo, bn = old.get_account_balance(), new.get_account_balance()
    assert (bo.nav, bo.cash, bo.buying_power) == (bn.nav, bn.cash, bn.buying_power)
    assert bn.nav == 100000.50


# ── P-02 positions ──────────────────────────────────────────────────────
def test_P02_positions_identical():
    poss = [
        {"symbol": "AAPL", "qty": "10", "avg_entry_price": "150.0",
         "current_price": "160.0", "market_value": "1600.0",
         "unrealized_pl": "100.0", "unrealized_plpc": "0.066"},
        {"symbol": "NVDA", "qty": "5", "avg_entry_price": "200.0",
         "current_price": "220.0", "market_value": "1100.0",
         "unrealized_pl": "100.0", "unrealized_plpc": "0.10"},
    ]
    old, new = _both()
    with patch("brokers.alpaca_client.requests.request", return_value=_resp(json_data=poss)), \
         patch("brokers.rest_broker.requests.request", return_value=_resp(json_data=poss)):
        po, pn = old.get_positions(), new.get_positions()
    sig = lambda lst: sorted((p.symbol, p.qty, p.avg_entry_price, p.current_price,
                              p.market_value, p.unrealized_pl) for p in lst)
    assert sig(po) == sig(pn)


# ── P-03 order body ─────────────────────────────────────────────────────
def test_P03_order_body_identical():
    ordresp = {"id": "ORD-1", "status": "accepted", "filled_qty": "0"}
    old, new = _both()
    with patch("brokers.alpaca_client.requests.request") as mo:
        mo.return_value = _resp(json_data=ordresp)
        old.place_order("AAPL", 10, "buy", "market", "day")
        body_old = mo.call_args.kwargs["json"]
    with patch("brokers.rest_broker.requests.request") as mn:
        mn.return_value = _resp(json_data=ordresp)
        new.place_order("AAPL", 10, "buy", "market", "day")
        body_new = mn.call_args.kwargs["json"]
    # 正規化 qty（"10" vs "10.0" 同為 10 股，下同一筆單）
    norm = lambda b: {**b, "qty": float(b["qty"])}
    assert norm(body_old) == norm(body_new), f"\nold={body_old}\nnew={body_new}"


# ── P-04 latest prices ──────────────────────────────────────────────────
def test_P04_prices_identical():
    bars = {"bars": {"AAPL": {"c": 160.0}, "NVDA": {"c": 220.0}}}
    old, new = _both()
    with patch("brokers.alpaca_client.requests.request", return_value=_resp(json_data=bars)), \
         patch("brokers.rest_broker.requests.request", return_value=_resp(json_data=bars)):
        assert old.get_latest_prices(["AAPL", "NVDA"]) == new.get_latest_prices(["AAPL", "NVDA"])


# ── P-05 is_trading_day ─────────────────────────────────────────────────
def test_P05_trading_day_identical():
    from datetime import date
    cal = [{"date": "2026-06-02"}]
    old, new = _both()
    d = date(2026, 6, 2)
    with patch("brokers.alpaca_client.requests.request", return_value=_resp(json_data=cal)), \
         patch("brokers.rest_broker.requests.request", return_value=_resp(json_data=cal)):
        assert old.is_trading_day(d) == new.is_trading_day(d) == True


# ── P-06 cancel_all 行為相容 ────────────────────────────────────────────
def test_P06_cancel_all_behaves():
    """舊 client DELETE 整批；新 client 列出後逐筆 DELETE。
    兩者對「2 筆 open order」最終都回報取消 2 筆。"""
    old, new = _both()
    with patch("brokers.alpaca_client.requests.request",
               return_value=_resp(status=207, json_data=[{"id": "1"}, {"id": "2"}])):
        n_old = old.cancel_all_open_orders()
    # 新 client：先 GET open orders（list），再每筆 DELETE
    calls = {"n": 0}
    def fake_new(method, url, **kw):
        if method == "GET":
            return _resp(json_data=[{"id": "1"}, {"id": "2"}])
        calls["n"] += 1
        return _resp(status=200)
    with patch("brokers.rest_broker.requests.request", side_effect=fake_new):
        n_new = new.cancel_all_open_orders()
    assert n_old == 2 and n_new == 2


# ── P-07 error mapping ──────────────────────────────────────────────────
def test_P07_auth_error_mapping_identical():
    old, new = _both()
    r = _resp(status=401, ok=False); r.text = "unauthorized"
    with patch("brokers.alpaca_client.requests.request", return_value=r):
        with pytest.raises(BrokerAuthError):
            old.get_account_balance()
    with patch("brokers.rest_broker.requests.request", return_value=r):
        with pytest.raises(BrokerAuthError):
            new.get_account_balance()
