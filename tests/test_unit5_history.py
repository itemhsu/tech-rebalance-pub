"""
tests/test_unit5_history.py — Unit 5: NAV History + Drawdown
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.data_writer import build_nav_history, build_drawdown


# ══════════════════════════════════════════════════════════════════════════════
#  build_nav_history
# ══════════════════════════════════════════════════════════════════════════════

def test_nav_history_appended_not_overwritten():
    existing = [{"date": "2026-05-15", "nav": 127219.6}]
    result = build_nav_history(existing, 128450.0, "2026-05-16")
    assert len(result) == 2


def test_nav_history_dates_ascending():
    existing = [
        {"date": "2026-05-14", "nav": 126000.0},
        {"date": "2026-05-15", "nav": 127000.0},
    ]
    result = build_nav_history(existing, 128000.0, "2026-05-16")
    dates = [p["date"] for p in result]
    assert dates == sorted(dates)


def test_nav_history_no_duplicate_dates():
    existing = [{"date": "2026-05-16", "nav": 127000.0}]  # 同日已存在
    result = build_nav_history(existing, 128000.0, "2026-05-16")
    dates = [p["date"] for p in result]
    assert len(dates) == len(set(dates))


def test_nav_history_last_nav_matches_today():
    existing = [{"date": "2026-05-15", "nav": 127000.0}]
    result = build_nav_history(existing, 128450.0, "2026-05-16")
    assert result[-1]["nav"] == 128450.0


def test_nav_history_overwrite_same_day():
    """同日執行兩次應覆蓋，不是新增。"""
    existing = [{"date": "2026-05-16", "nav": 127000.0}]
    result = build_nav_history(existing, 128000.0, "2026-05-16")
    assert len(result) == 1
    assert result[0]["nav"] == 128000.0


def test_nav_history_event_marker_added():
    events = [{"id": "e1", "date": "2026-05-16", "type": "deposit",
               "nav_before": 100000.0, "nav_after": 150000.0, "amount": 50000.0}]
    result = build_nav_history([], 150000.0, "2026-05-16", today_events=events)
    assert "event" in result[-1]
    assert result[-1]["event"]["type"] == "deposit"


def test_nav_history_no_marker_on_normal_day():
    result = build_nav_history([], 128000.0, "2026-05-16", today_events=[])
    assert "event" not in result[-1]


def test_nav_history_no_marker_when_events_none():
    result = build_nav_history([], 128000.0, "2026-05-16", today_events=None)
    assert "event" not in result[-1]


def test_nav_history_deposit_event_shows_amount():
    events = [{"id": "e1", "date": "2026-05-16", "type": "deposit",
               "nav_before": 100000.0, "nav_after": 150000.0, "amount": 50000.0}]
    result = build_nav_history([], 150000.0, "2026-05-16", today_events=events)
    evt = result[-1]["event"]
    assert "amount" in evt
    assert evt["amount"] == 50000.0


# ══════════════════════════════════════════════════════════════════════════════
#  build_drawdown
# ══════════════════════════════════════════════════════════════════════════════

def _history(*navs, start="2026-01-01"):
    from datetime import date, timedelta
    d = date.fromisoformat(start)
    result = []
    for n in navs:
        result.append({"date": d.isoformat(), "nav": float(n)})
        d += timedelta(days=1)
    return result


def test_drawdown_same_length_as_nav_history():
    h = _history(100, 90, 95, 88, 100)
    dd = build_drawdown(h)
    assert len(dd["dates"]) == len(h)
    assert len(dd["portfolio"]) == len(h)
    assert len(dd["nasdaq"]) == len(h)
    assert len(dd["sp500"]) == len(h)


def test_drawdown_starts_at_zero():
    h = _history(100, 90, 95)
    dd = build_drawdown(h)
    assert dd["portfolio"][0] == 0.0


def test_drawdown_all_non_positive():
    h = _history(100, 90, 95, 80, 110)
    dd = build_drawdown(h)
    assert all(v <= 0.0 for v in dd["portfolio"])


def test_drawdown_correct_calculation():
    # [100, 90, 95] → [0%, -10%, -5%]
    h = _history(100, 90, 95)
    dd = build_drawdown(h)
    assert dd["portfolio"][0] == 0.0
    assert abs(dd["portfolio"][1] - (-10.0)) < 0.01
    assert abs(dd["portfolio"][2] - (-5.0)) < 0.01


def test_drawdown_benchmark_null_when_missing():
    h = _history(100, 90, 95)
    dd = build_drawdown(h, benchmark_data=None)
    assert all(v is None for v in dd["nasdaq"])
    assert all(v is None for v in dd["sp500"])


def test_drawdown_benchmark_computed_when_provided():
    h = _history(100, 90, 95)
    bench = {"QQQ": [100, 95, 98], "SPY": [100, 97, 99]}
    dd = build_drawdown(h, benchmark_data=bench)
    assert dd["nasdaq"][0] == 0.0
    assert dd["sp500"][0] == 0.0
    # QQQ: [100→95] → drawdown at [1] = (95/100-1)*100 = -5.0
    assert abs(dd["nasdaq"][1] - (-5.0)) < 0.01


def test_drawdown_dates_match_nav_history():
    h = _history(100, 90, 95)
    dd = build_drawdown(h)
    assert dd["dates"] == [p["date"] for p in h]
