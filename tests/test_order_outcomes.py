"""訂單下落追蹤：_record_outcomes（即時）+ reconcile_outcomes（跨日對帳）。

對應使用者問題：帳號 #3 只有 ORDER_PLANNED，沒有「交易指令的下落」。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import trader


class MockClient:
    def __init__(self, orders):  # {order_id: order_dict}
        self._o = orders

    def get_order(self, oid):
        return self._o[oid]


class FakeTL:
    def __init__(self, events=None):
        self._ev = events or []
        self.fills = []
        self.rejects = []
        self.stale = []

    def read_events(self, account_id=None, path=None):
        return self._ev

    def record_order_fill(self, **k):
        self.fills.append(k)

    def record_order_reject(self, **k):
        self.rejects.append(k)

    def record_order_stale(self, **k):
        self.stale.append(k)


def _order(sym, act, qty, reason="x"):
    return SimpleNamespace(symbol=sym, action=act, qty=qty, reason=reason)


# ── _record_outcomes（送單後即時查）────────────────────────────────────────
def test_record_outcomes_filled():
    tl = FakeTL()
    client = MockClient({"a": {"status": "filled", "filled_qty": "6", "filled_avg_price": "320.5"}})
    trader._record_outcomes(client, [("a", _order("V", "BUY", 6))], tl, "3", "mom_6m_t20")
    assert len(tl.fills) == 1
    assert tl.fills[0]["symbol"] == "V" and tl.fills[0]["filled_avg_price"] == 320.5
    assert tl.fills[0]["qty"] == 6.0


def test_record_outcomes_rejected():
    tl = FakeTL()
    client = MockClient({"a": {"status": "rejected", "filled_qty": "0"}})
    trader._record_outcomes(client, [("a", _order("ORCL", "SELL", 10))], tl, "3", "s")
    assert len(tl.rejects) == 1 and "rejected" in tl.rejects[0]["error"]


def test_record_outcomes_partial():
    tl = FakeTL()
    client = MockClient({"a": {"status": "partially_filled", "filled_qty": "3", "filled_avg_price": "100"}})
    trader._record_outcomes(client, [("a", _order("AAPL", "BUY", 6))], tl, "3", "s")
    assert len(tl.fills) == 1 and "partial" in tl.fills[0]["reason"] and tl.fills[0]["qty"] == 3.0


def test_record_outcomes_pending_no_event():
    tl = FakeTL()
    client = MockClient({"a": {"status": "accepted", "filled_qty": "0"}})
    trader._record_outcomes(client, [("a", _order("V", "BUY", 6))], tl, "3", "s")
    assert not tl.fills and not tl.rejects   # 仍 pending → 不記終態，待對帳


# ── reconcile_outcomes（跨日對帳）──────────────────────────────────────────
def test_reconcile_records_fill():
    ev = [{"type": "ORDER_SUBMITTED", "order_id": "a", "symbol": "V",
           "action": "BUY", "qty": 6, "reason": "new_entrant", "strategy": "mom_6m_t20"}]
    tl = FakeTL(ev)
    client = MockClient({"a": {"status": "filled", "filled_qty": "6", "filled_avg_price": "321"}})
    n = trader.reconcile_outcomes(client, "3", trade_log=tl)
    assert n == 1 and tl.fills[0]["symbol"] == "V" and tl.fills[0]["filled_avg_price"] == 321.0


def test_reconcile_skips_already_resolved():
    ev = [{"type": "ORDER_SUBMITTED", "order_id": "a", "symbol": "V", "action": "BUY", "qty": 6},
          {"type": "ORDER_FILLED", "order_id": "a"}]
    tl = FakeTL(ev)
    client = MockClient({"a": {"status": "filled", "filled_qty": "6"}})
    assert trader.reconcile_outcomes(client, "3", trade_log=tl) == 0
    assert not tl.fills   # 已結，不重複


def test_reconcile_records_reject():
    ev = [{"type": "ORDER_SUBMITTED", "order_id": "a", "symbol": "ORCL",
           "action": "SELL", "qty": 10, "reason": "exit"}]
    tl = FakeTL(ev)
    client = MockClient({"a": {"status": "expired", "filled_qty": "0"}})
    n = trader.reconcile_outcomes(client, "3", trade_log=tl)
    assert n == 1 and tl.rejects[0]["symbol"] == "ORCL"


# ── ORDER_STALE：送出超過 N 天仍未結 → 告警 ───────────────────────────────
def test_reconcile_flags_stale():
    import datetime as dt
    old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).isoformat()
    ev = [{"type": "ORDER_SUBMITTED", "order_id": "a", "symbol": "V",
           "action": "BUY", "qty": 6, "ts": old_ts}]
    tl = FakeTL(ev)
    client = MockClient({"a": {"status": "accepted", "filled_qty": "0"}})  # 仍未結
    n = trader.reconcile_outcomes(client, "3", trade_log=tl, stale_days=3)
    assert n == 1 and tl.stale and tl.stale[0]["symbol"] == "V" and tl.stale[0]["age_days"] >= 5


def test_reconcile_stale_dedup():
    import datetime as dt
    old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).isoformat()
    ev = [{"type": "ORDER_SUBMITTED", "order_id": "a", "symbol": "V", "action": "BUY", "qty": 6, "ts": old_ts},
          {"type": "ORDER_STALE", "order_id": "a"}]   # 已告警過
    tl = FakeTL(ev)
    client = MockClient({"a": {"status": "accepted", "filled_qty": "0"}})
    assert trader.reconcile_outcomes(client, "3", trade_log=tl, stale_days=3) == 0
    assert not tl.stale
