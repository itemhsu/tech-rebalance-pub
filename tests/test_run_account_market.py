"""run_account 市場分流：--market 只跑該市場帳戶（依券商判定）。純單元、不打網路。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run_account as ra


_ACCTS = [
    {"id": "1", "broker": "alpaca",  "strategy": "top10",         "enabled": True},
    {"id": "2", "broker": "sinopac", "strategy": "tw_tech_top10", "enabled": True},
    {"id": "3", "broker": "tradier", "strategy": "weekly_top10",  "enabled": True},
    {"id": "4", "broker": "sinopac", "strategy": "tw_tech_mom_6m_t10", "enabled": False},
]


def test_account_market_from_broker_spec():
    # sinopac spec.market.currency == TWD → tw；alpaca/tradier → us
    assert ra._account_market({"broker": "sinopac"}) == "tw"
    assert ra._account_market({"broker": "alpaca"}) == "us"
    assert ra._account_market({"broker": "tradier"}) == "us"


def test_account_market_unknown_broker_defaults_us():
    assert ra._account_market({"broker": "no_such"}) == "us"


def _run_with_market(monkeypatch, market):
    ran = []
    monkeypatch.setattr(ra, "_load_accounts_json", lambda: _ACCTS)
    monkeypatch.setattr(ra, "run_account",
                        lambda aid, **kw: (ran.append(aid) or 0))
    ra.run_all_accounts(market=market)
    return ran


def test_market_tw_runs_only_enabled_tw_accounts(monkeypatch):
    ran = _run_with_market(monkeypatch, "tw")
    assert ran == ["2"]          # #4 sinopac 但 enabled=false → 不跑


def test_market_us_runs_only_us_accounts(monkeypatch):
    ran = _run_with_market(monkeypatch, "us")
    assert ran == ["1", "3"]


def test_no_market_runs_all_enabled(monkeypatch):
    ran = _run_with_market(monkeypatch, None)
    assert ran == ["1", "2", "3"]
