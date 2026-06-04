"""Phase C：Tradier 純 JSON 整合測試（T-01 ~ T-06）。

驗收重點：Tradier 整合「0 行 Python」——只有 brokers/tradier.json，
由通用 RestBrokerClient 驅動。本測試 mock Tradier 真實回應格式，
確認引擎照 JSON 對應表正確翻譯。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from brokers.registry import build_client
from brokers.rest_broker import RestBrokerClient
from brokers.base import BrokerCapabilityError


def _client(monkeypatch):
    monkeypatch.setenv("ACC9_API_KEY", "FAKE_SANDBOX_TOKEN")
    monkeypatch.setenv("ACC9_ACCOUNT_ID", "VA80282763")
    return build_client("tradier", "sandbox", "ACC9")


def _resp(status=200, json_data=None, ok=None):
    r = MagicMock()
    r.status_code = status
    r.ok = (200 <= status < 300) if ok is None else ok
    r.json.return_value = json_data if json_data is not None else {}
    r.text = ""
    return r


def test_C_tradier_uses_generic_engine(monkeypatch):
    """前提：Tradier 走通用引擎，無自訂 client（0 Python 的證明）。"""
    c = _client(monkeypatch)
    assert isinstance(c, RestBrokerClient)
    assert c.broker_id == "tradier"


def test_T01_balances_maps_total_equity_to_nav(monkeypatch):
    c = _client(monkeypatch)
    data = {"balances": {"total_equity": 100000.0, "total_cash": 100000.0}}
    with patch("brokers.rest_broker.requests.request", return_value=_resp(json_data=data)):
        b = c.get_account_balance()
    assert b.nav == 100000.0
    assert b.cash == 100000.0


def test_T02_single_position_dict_normalized(monkeypatch):
    """Tradier 單筆持倉回 dict（非 list）→ 引擎正規化成 1 筆。"""
    c = _client(monkeypatch)
    data = {"positions": {"position": {
        "symbol": "AAPL", "quantity": 10, "cost_basis": 1500.0,
    }}}
    with patch("brokers.rest_broker.requests.request", return_value=_resp(json_data=data)):
        pos = c.get_positions()
    assert len(pos) == 1
    assert pos[0].symbol == "AAPL"
    assert pos[0].qty == 10
    assert pos[0].avg_entry_price == 1500.0


def test_T03_quotes_map_symbol_to_last(monkeypatch):
    c = _client(monkeypatch)
    data = {"quotes": {"quote": [
        {"symbol": "AAPL", "last": 306.6},
        {"symbol": "NVDA", "last": 219.22},
    ]}}
    with patch("brokers.rest_broker.requests.request", return_value=_resp(json_data=data)):
        px = c.get_latest_prices(["AAPL", "NVDA"])
    assert px == {"AAPL": 306.6, "NVDA": 219.22}


def test_T04_order_body_form_encoded_with_constants(monkeypatch):
    c = _client(monkeypatch)
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": 123, "status": "ok"}})
        c.place_order("AAPL", 10, "buy", "market", "day")
        kw = m.call_args.kwargs
        body = kw["data"]
        assert kw["json"] is None          # form 編碼
        assert body["class"] == "equity"   # constants
        assert body["quantity"] == "10"    # qty → quantity
        assert body["duration"] == "day"   # time_in_force → duration
        assert body["type"] == "market"
        # URL 帶 account_id
        assert "/accounts/VA80282763/orders" in m.call_args.args[1]


def test_T05_order_id_from_nested_order_path(monkeypatch):
    c = _client(monkeypatch)
    with patch("brokers.rest_broker.requests.request",
               return_value=_resp(json_data={"order": {"id": 456, "status": "ok"}})):
        r = c.place_order("AAPL", 10, "buy")
    assert r.order_id == "456"
    assert r.status == "ok"


def test_T06_fractional_rejected(monkeypatch):
    """Tradier 不支援零股（spec fractional_shares=false）。"""
    c = _client(monkeypatch)
    with pytest.raises(BrokerCapabilityError):
        c.place_order("AAPL", 1.5, "buy")
