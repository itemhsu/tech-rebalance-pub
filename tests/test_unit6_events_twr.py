"""
tests/test_unit6_events_twr.py — Unit 6: Events + TWR
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from engine.data_writer import append_event, get_today_events
from engine.twr import (
    compute_twr, compute_net_contribution,
    compute_totals, compute_investment_gain,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Events
# ══════════════════════════════════════════════════════════════════════════════

def test_event_ids_unique():
    events = []
    events = append_event(events, "deposit",    "2026-05-16", 100000, 150000, amount=50000)
    events = append_event(events, "withdrawal", "2026-05-16", 150000, 120000, amount=-30000)
    ids = [e["id"] for e in events]
    assert len(ids) == len(set(ids))


def test_deposit_amount_positive():
    events = append_event([], "deposit", "2026-05-16", 100000, 150000, amount=50000)
    assert events[0]["amount"] > 0


def test_withdrawal_amount_negative():
    events = append_event([], "withdrawal", "2026-05-16", 150000, 120000, amount=-30000)
    assert events[0]["amount"] < 0


def test_nav_after_deposit_equals_before_plus_amount():
    amt = 50000.0
    nav_before = 100000.0
    nav_after  = nav_before + amt
    events = append_event([], "deposit", "2026-05-16", nav_before, nav_after, amount=amt)
    e = events[0]
    assert abs(e["nav_after"] - (e["nav_before"] + amt)) < 0.01


def test_non_cash_event_nav_unchanged():
    events = append_event([], "strategy_pause", "2026-05-16", 100000, 100000,
                          pause_reason="手動停用")
    e = events[0]
    assert e["nav_before"] == e["nav_after"]


def test_strategy_switch_fields():
    events = append_event([], "strategy_switch", "2026-05-16", 100000, 100000,
                          from_strategy="top10", to_strategy="d2p2t6")
    e = events[0]
    assert e["from_strategy"] == "top10"
    assert e["to_strategy"]   == "d2p2t6"


def test_get_today_events_filters_correctly():
    events = [
        {"id": "e1", "date": "2026-05-15", "type": "deposit",
         "nav_before": 100000, "nav_after": 150000},
        {"id": "e2", "date": "2026-05-16", "type": "deposit",
         "nav_before": 150000, "nav_after": 200000},
    ]
    today = get_today_events(events, "2026-05-16")
    assert len(today) == 1
    assert today[0]["id"] == "e2"


def test_is_paused_true_when_last_event_is_pause():
    from engine.data_writer import build_summary
    events = append_event([], "strategy_pause", "2026-05-10", 100000, 100000)
    s = build_summary(
        nav=100000, cash=1000, initial_nav=100000,
        inception_date="2024-01-01", prev_nav=100000,
        nav_history=[{"date": "2024-01-01", "nav": 100000}],
        events=events, trading_date="2026-05-16",
    )
    assert s["is_paused"] is True
    assert s["paused_since"] == "2026-05-10"


def test_is_paused_false_after_resume():
    from engine.data_writer import build_summary
    events = []
    events = append_event(events, "strategy_pause",  "2026-05-10", 100000, 100000)
    events = append_event(events, "strategy_resume", "2026-05-15", 100000, 100000)
    s = build_summary(
        nav=100000, cash=1000, initial_nav=100000,
        inception_date="2024-01-01", prev_nav=100000,
        nav_history=[{"date": "2024-01-01", "nav": 100000}],
        events=events, trading_date="2026-05-16",
    )
    assert s["is_paused"] is False


def test_paused_days_counted_correctly():
    from engine.data_writer import build_summary
    events = []
    events = append_event(events, "strategy_pause",  "2026-05-01", 100000, 100000)
    events = append_event(events, "strategy_resume", "2026-05-11", 100000, 100000)
    s = build_summary(
        nav=100000, cash=1000, initial_nav=100000,
        inception_date="2024-01-01", prev_nav=100000,
        nav_history=[{"date": "2024-01-01", "nav": 100000}],
        events=events, trading_date="2026-05-16",
    )
    assert s["total_paused_days"] == 10   # 05-01 到 05-11 = 10 天


# ══════════════════════════════════════════════════════════════════════════════
#  TWR
# ══════════════════════════════════════════════════════════════════════════════

def _history(*navs):
    from datetime import date, timedelta
    d = date(2026, 1, 1)
    result = []
    for n in navs:
        result.append({"date": d.isoformat(), "nav": float(n)})
        d += timedelta(days=1)
    return result


def test_twr_no_cash_flow_equals_simple_return():
    h = _history(100000, 128000)
    twr = compute_twr(h, [])
    simple = (128000 / 100000 - 1) * 100
    assert abs(twr - simple) < 0.01


def test_twr_deposit_excluded_from_return():
    """
    NAV: 100 → 入金50 → 150 → 漲到 165
    TWR = (165/150) - 1 = +10%，不是 +65%
    """
    h = _history(100, 150, 165)   # index 0=before, 1=after deposit, 2=final
    events = [{
        "id": "e1", "date": h[1]["date"], "type": "deposit",
        "nav_before": 100, "nav_after": 150, "amount": 50,
    }]
    twr = compute_twr(h, events)
    assert abs(twr - 10.0) < 0.1


def test_twr_withdrawal_excluded():
    """
    NAV: 100 → 出金20 → 80 → 漲到 88
    TWR ≈ +10%（排除出金影響）
    """
    h = _history(100, 80, 88)
    events = [{
        "id": "e1", "date": h[1]["date"], "type": "withdrawal",
        "nav_before": 100, "nav_after": 80, "amount": -20,
    }]
    twr = compute_twr(h, events)
    assert abs(twr - 10.0) < 0.1


def test_twr_empty_history_returns_zero():
    assert compute_twr([], []) == 0.0


def test_net_contribution_sum_of_cash_events():
    events = [
        {"id": "e1", "date": "2026-01-01", "type": "deposit",
         "nav_before": 100, "nav_after": 150, "amount": 50},
        {"id": "e2", "date": "2026-02-01", "type": "withdrawal",
         "nav_before": 160, "nav_after": 130, "amount": -30},
    ]
    nc = compute_net_contribution(events)
    assert abs(nc - 20.0) < 0.01


def test_investment_gain_excludes_contributions():
    gain = compute_investment_gain(nav=130, initial_nav=100, net_contribution=20)
    assert abs(gain - 10.0) < 0.01


def test_compute_totals_separate_deposit_withdrawal():
    events = [
        {"id": "e1", "date": "2026-01-01", "type": "deposit",
         "nav_before": 100, "nav_after": 150, "amount": 50},
        {"id": "e2", "date": "2026-02-01", "type": "deposit",
         "nav_before": 160, "nav_after": 210, "amount": 50},
        {"id": "e3", "date": "2026-03-01", "type": "withdrawal",
         "nav_before": 220, "nav_after": 190, "amount": -30},
    ]
    deposited, withdrawn = compute_totals(events)
    assert abs(deposited - 100.0) < 0.01
    assert abs(withdrawn - 30.0) < 0.01
