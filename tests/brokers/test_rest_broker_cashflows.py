"""生產路徑的現金流：registry 對 alpaca 建的是通用 RestBrokerClient（spec 無 client_class），
它必須依 spec 的 account_activities 端點抓 CSD/CSW/JNLC；沒有該端點的券商 → []。

回歸：2026-10-07 v1.0.26 首跑 cash_flows.json 為空——get_cash_flows 只實作在 AlpacaClient，
而生產用的 RestBrokerClient 繼承 base 永遠回 []。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
responses = pytest.importorskip("responses")

from brokers.registry import build_client, load_broker_spec   # noqa: E402
from brokers.rest_broker import RestBrokerClient              # noqa: E402

PAPER = "https://paper-api.alpaca.markets"
# #3 真實回應的形狀（probe 2026-10-07）
_ACTS = [
    {"activity_type": "FEE",  "date": "2026-10-01", "net_amount": "-0.01"},
    {"activity_type": "DIV",  "date": "2026-09-30", "net_amount": "4.55", "symbol": "AVGO"},
    {"activity_type": "JNLC", "date": "2026-08-17", "net_amount": "0.06",
     "description": "Juneteenth Margin Reimbursement"},
    {"activity_type": "CSD",  "date": "2026-06-23", "net_amount": "9476.82",
     "description": "type: wire, subtype: none"},
    {"activity_type": "CSW",  "date": "2026-06-10", "net_amount": "-250.00"},
]


def _prod_alpaca(monkeypatch):
    monkeypatch.setenv("ACC9_API_KEY", "PK_TEST")
    monkeypatch.setenv("ACC9_API_SECRET", "SECRET_TEST")
    return build_client("alpaca", "paper", "ACC9")


@responses.activate
def test_production_alpaca_client_fetches_cash_flows(monkeypatch):
    c = _prod_alpaca(monkeypatch)
    assert isinstance(c, RestBrokerClient), "生產路徑是通用 RestBrokerClient"
    responses.add(responses.GET, f"{PAPER}/v2/account/activities", json=_ACTS, status=200)
    flows = c.get_cash_flows("2026-06-01")
    assert {"date": "2026-06-23", "type": "deposit",    "amount": 9476.82} in flows
    assert {"date": "2026-06-10", "type": "withdrawal", "amount": 250.0}   in flows
    assert {"date": "2026-08-17", "type": "deposit",    "amount": 0.06}    in flows
    assert all(f["type"] in ("deposit", "withdrawal") for f in flows)
    assert len(flows) == 3, "FEE/DIV 不是外部現金流"
    q = responses.calls[0].request.url
    assert "activity_types=CSD%2CCSW%2CJNLC" in q and "after=2026-06-01" in q


def test_broker_without_activities_endpoint_returns_empty(monkeypatch):
    spec = dict(load_broker_spec("alpaca"))
    spec["endpoints"] = {k: v for k, v in spec["endpoints"].items() if k != "account_activities"}
    c = RestBrokerClient(spec=spec, env={"API_KEY": "k", "API_SECRET": "s"}, environment="paper")
    assert c.get_cash_flows("2026-01-01") == []


def test_alpaca_spec_declares_activities_endpoint():
    assert load_broker_spec("alpaca")["endpoints"]["account_activities"] == "/v2/account/activities"
