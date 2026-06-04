"""Phase A 單元測試：brokers/rest_broker.py 通用引擎（U-01 ~ U-16）。

全部 mock HTTP + 假 spec/key，不打網路。對應 docs/json-broker-plan.html。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from brokers.rest_broker import RestBrokerClient, dig, normalize_list
from brokers.base import (
    BrokerAuthError, BrokerCapabilityError, AccountBalance,
)


# ── 假 spec：模擬一家「Tradier 風格」券商（form、巢狀、帳號路徑）──────────
FAKE_SPEC = {
    "id": "faker",
    "display_name": "Faker",
    "integration": {"type": "rest"},
    "auth": {
        "method": "bearer_token",
        "required_env": ["{PREFIX}_API_KEY", "{PREFIX}_ACCOUNT_ID"],
        "header_template": {"Authorization": "Bearer {api_key}"},
    },
    "environments": {"sandbox": {"base_url": "https://sb.faker.test/v1"}},
    "market_data": {
        "quotes_endpoint": "/markets/quotes",
        "clock_endpoint": "/markets/clock",
        "calendar_endpoint": "/markets/calendar",
    },
    "endpoints": {
        "balances": "/accounts/{account_id}/balances",
        "positions": "/accounts/{account_id}/positions",
        "orders": "/accounts/{account_id}/orders",
        "order_by_id": "/accounts/{account_id}/orders/{order_id}",
    },
    "request": {
        "encoding": "form",
        "field_map": {
            "symbol": "symbol", "qty": "quantity", "side": "side",
            "order_type": "type", "time_in_force": "duration",
        },
        "constants": {"class": "equity"},
    },
    "response": {
        "order_id_path": "order.id",
        "order_status_path": "order.status",
        "positions_path": "positions.position",
        "quote_list_path": "quotes.quote",
        "quote_symbol_field": "symbol",
        "quote_price_field": "last",
        "balance": {"nav": "balances.total_equity", "cash": "balances.total_cash",
                    "buying_power": "balances.total_cash"},
    },
    "value_maps": {
        "side": {"buy": "buy", "sell": "sell"},
        "time_in_force": {"day": "day", "gtc": "gtc"},
    },
    "capabilities": {
        "fractional_shares": False,
        "asset_classes": ["us_equity"],
        "order_types": ["market", "limit"],
        "time_in_force": ["day", "gtc"],
    },
}

FAKE_ENV = {"API_KEY": "FAKE_TOKEN", "ACCOUNT_ID": "VA999"}


def _client():
    return RestBrokerClient(FAKE_SPEC, FAKE_ENV, environment="sandbox")


def _resp(status=200, json_data=None, ok=None):
    r = MagicMock()
    r.status_code = status
    r.ok = (200 <= status < 300) if ok is None else ok
    r.json.return_value = json_data if json_data is not None else {}
    r.text = ""
    return r


# ════════════════════════════════════════════════════════════════════════
#  helpers：dig / normalize_list
# ════════════════════════════════════════════════════════════════════════

def test_U01_dig_nested():
    assert dig({"order": {"id": 7}}, "order.id") == 7


def test_U02_dig_missing_returns_none():
    assert dig({"a": 1}, "a.b.c") is None
    assert dig({}, "x") is None


def test_U03_normalize_single_dict():
    assert normalize_list({"symbol": "AAPL"}) == [{"symbol": "AAPL"}]


def test_U04_normalize_list_unchanged():
    lst = [{"s": 1}, {"s": 2}]
    assert normalize_list(lst) == lst
    assert normalize_list(None) == []
    assert normalize_list("null") == []


# ════════════════════════════════════════════════════════════════════════
#  place_order：編碼 / field_map / constants / value_maps
# ════════════════════════════════════════════════════════════════════════

def test_U05_json_encoding_uses_json_body():
    spec = {**FAKE_SPEC, "request": {**FAKE_SPEC["request"], "encoding": "json"}}
    c = RestBrokerClient(spec, FAKE_ENV, "sandbox")
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": "1", "status": "ok"}})
        c.place_order("AAPL", 10, "buy")
        _, kwargs = m.call_args
        assert kwargs["json"] is not None
        assert kwargs["data"] is None


def test_U06_form_encoding_uses_data_body():
    c = _client()
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": "1", "status": "ok"}})
        c.place_order("AAPL", 10, "buy")
        _, kwargs = m.call_args
        assert kwargs["data"] is not None
        assert kwargs["json"] is None


def test_U07_field_map_renames_qty():
    c = _client()
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": "1"}})
        c.place_order("AAPL", 10, "buy")
        body = m.call_args.kwargs["data"]
        assert body["quantity"] == "10"     # qty → quantity
        assert body["duration"] == "day"    # time_in_force → duration
        assert body["type"] == "market"     # order_type → type
        assert "qty" not in body


def test_U08_constants_injected():
    c = _client()
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": "1"}})
        c.place_order("AAPL", 10, "buy")
        assert m.call_args.kwargs["data"]["class"] == "equity"


def test_U09_value_maps_translate_side():
    spec = {**FAKE_SPEC, "value_maps": {"side": {"buy": "buy_to_open"}}}
    c = RestBrokerClient(spec, FAKE_ENV, "sandbox")
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": "1"}})
        c.place_order("AAPL", 10, "buy")
        assert m.call_args.kwargs["data"]["side"] == "buy_to_open"


def test_U10_endpoint_template_fills_account_id():
    c = _client()
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": "1"}})
        c.place_order("AAPL", 10, "buy")
        url = m.call_args.args[1]
        assert "/accounts/VA999/orders" in url


# ════════════════════════════════════════════════════════════════════════
#  回應解析：balance / positions / order id
# ════════════════════════════════════════════════════════════════════════

def test_U11_balance_via_nested_path():
    c = _client()
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"balances": {"total_equity": 12345.0,
                                                       "total_cash": 9999.0}})
        b = c.get_account_balance()
        assert isinstance(b, AccountBalance)
        assert b.nav == 12345.0
        assert b.cash == 9999.0


def test_U12_positions_path_and_normalize():
    c = _client()
    single = {"positions": {"position": {"symbol": "AAPL", "quantity": 5}}}
    spec = {**FAKE_SPEC, "response": {**FAKE_SPEC["response"],
            "position_fields": {"qty": "quantity"}}}
    c = RestBrokerClient(spec, FAKE_ENV, "sandbox")
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data=single)
        pos = c.get_positions()
        assert len(pos) == 1
        assert pos[0].symbol == "AAPL"
        assert pos[0].qty == 5


def test_U13_order_id_from_nested_path():
    c = _client()
    with patch("brokers.rest_broker.requests.request") as m:
        m.return_value = _resp(json_data={"order": {"id": "ORD-7", "status": "ok"}})
        r = c.place_order("AAPL", 10, "buy")
        assert r.order_id == "ORD-7"
        assert r.status == "ok"


# ════════════════════════════════════════════════════════════════════════
#  capability / 安全 / registry 預設
# ════════════════════════════════════════════════════════════════════════

def test_U14_fractional_rejected():
    c = _client()
    with pytest.raises(BrokerCapabilityError):
        c.place_order("AAPL", 1.5, "buy")


def test_U15_401_raises_auth_error_without_token():
    c = _client()
    with patch("brokers.rest_broker.requests.request") as m:
        r = _resp(status=401, ok=False)
        r.text = "unauthorized"
        m.return_value = r
        with pytest.raises(BrokerAuthError) as ei:
            c.get_account_balance()
        assert "FAKE_TOKEN" not in str(ei.value)


def test_U16_registry_defaults_to_rest_broker(monkeypatch, tmp_path):
    """spec 無 client_class → registry 自動用 RestBrokerClient。"""
    import json
    import brokers.registry as reg
    spec_no_class = {k: v for k, v in FAKE_SPEC.items()}
    # 寫到臨時 brokers dir
    monkeypatch.setattr(reg, "BROKERS_DIR", tmp_path)
    (tmp_path / "faker.json").write_text(json.dumps(spec_no_class), encoding="utf-8")
    monkeypatch.setenv("ACC9_API_KEY", "K")
    monkeypatch.setenv("ACC9_ACCOUNT_ID", "VA1")
    client = reg.build_client("faker", "sandbox", "ACC9")
    assert isinstance(client, RestBrokerClient)
