"""
tests/test_unit4_writer_core.py — Unit 4: data.json Writer 核心四個 section
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.accounts import Account
from engine.data_writer import build_meta, build_summary, build_portfolio, build_positions
from engine.strategy_loader import load_and_validate

TOP10  = load_and_validate("top10")
D2P2T6 = load_and_validate("d2p2t6")

_ACCOUNT_1 = Account(id="1", strategy="top10",  label="帳戶 #1 (TOP10)")
_ACCOUNT_2 = Account(id="2", strategy="d2p2t6", label="帳戶 #2 (D2P2T6)")

_POSITIONS_SAMPLE = [
    {"symbol": "NVDA", "qty": 30.0, "avg_entry_price": 820.0,
     "current_price": 1050.4, "market_value": 31512.0,
     "unrealized_pl": 6912.0, "unrealized_plpc": 0.281},
    {"symbol": "MSFT", "qty": 30.0, "avg_entry_price": 380.0,
     "current_price": 415.2, "market_value": 12456.0,
     "unrealized_pl": 1056.0, "unrealized_plpc": 0.0926},
]
_TOP10_SYMBOLS = ["NVDA", "MSFT", "AAPL", "GOOGL", "META",
                  "AMZN", "TSLA", "AVGO", "AMD", "TSM"]
_NAV  = 128450.0
_CASH = 2340.5


# ══════════════════════════════════════════════════════════════════════════════
#  build_meta
# ══════════════════════════════════════════════════════════════════════════════

def test_meta_account_id_matches_input():
    m = build_meta(TOP10, _ACCOUNT_1, [_ACCOUNT_1], trading_date="2026-05-16")
    assert m["account_id"] == "1"


def test_meta_strategy_matches_strategy_cfg():
    m = build_meta(TOP10, _ACCOUNT_1, [_ACCOUNT_1], trading_date="2026-05-16")
    assert m["strategy"] == "top10"


def test_meta_dry_run_is_bool():
    m = build_meta(TOP10, _ACCOUNT_1, [_ACCOUNT_1], dry_run=True, trading_date="2026-05-16")
    assert m["dry_run"] is True
    assert isinstance(m["dry_run"], bool)


def test_meta_generated_at_is_iso8601():
    from datetime import datetime
    m = build_meta(TOP10, _ACCOUNT_1, [_ACCOUNT_1], trading_date="2026-05-16")
    # 應可被 datetime.fromisoformat 解析（去掉末尾 Z）
    datetime.fromisoformat(m["generated_at"].replace("Z", "+00:00"))


def test_meta_same_strategy_accounts_correct():
    same = [_ACCOUNT_1, Account(id="3", strategy="top10", label="帳戶3")]
    m = build_meta(TOP10, _ACCOUNT_1, same, trading_date="2026-05-16")
    ids = [a["id"] for a in m["same_strategy_accounts"]]
    assert "1" in ids and "3" in ids


def test_meta_accent_color_from_strategy():
    m = build_meta(TOP10, _ACCOUNT_1, [_ACCOUNT_1], trading_date="2026-05-16")
    assert m["accent_color"] == TOP10["dashboard"]["accent_color"]


def test_meta_schema_version_is_string():
    m = build_meta(TOP10, _ACCOUNT_1, [_ACCOUNT_1], trading_date="2026-05-16")
    assert isinstance(m["schema_version"], str)


# ══════════════════════════════════════════════════════════════════════════════
#  build_summary
# ══════════════════════════════════════════════════════════════════════════════

def _make_summary(**kwargs):
    defaults = dict(
        nav=_NAV,
        cash=_CASH,
        initial_nav=100000.0,
        inception_date="2024-01-15",
        prev_nav=127219.6,
        nav_history=[
            {"date": "2024-01-15", "nav": 100000.0},
            {"date": "2026-05-15", "nav": 127219.6},
        ],
        events=[],
        trading_date="2026-05-16",
    )
    defaults.update(kwargs)
    return build_summary(**defaults)


def test_summary_nav_correct():
    s = _make_summary()
    assert s["nav"] == round(_NAV, 2)


def test_summary_today_change_correct():
    s = _make_summary(prev_nav=127219.6)
    expected = round(_NAV - 127219.6, 2)
    assert abs(s["today_change"] - expected) < 0.01


def test_summary_today_change_can_be_negative():
    s = _make_summary(nav=99000.0, prev_nav=100000.0)
    assert s["today_change"] < 0


def test_summary_total_return_calculation():
    s = _make_summary(nav=128450.0, initial_nav=100000.0)
    assert abs(s["total_return"] - 28450.0) < 0.01
    assert abs(s["total_return_pct"] - 28.45) < 0.01


def test_summary_max_drawdown_is_non_positive():
    s = _make_summary()
    assert s["max_drawdown_pct"] <= 0


def test_summary_ytd_null_when_no_prior_year_data():
    # 歷史只有本年 → 沒有去年底的資料 → ytd 為 None
    s = build_summary(
        nav=105000.0, cash=1000.0,
        initial_nav=100000.0, inception_date="2026-01-02",
        prev_nav=104000.0,
        nav_history=[{"date": "2026-01-02", "nav": 100000.0}],
        events=[], trading_date="2026-05-16",
    )
    assert s["ytd_return_pct"] is None


def test_summary_is_paused_false_by_default():
    s = _make_summary()
    assert s["is_paused"] is False


def test_summary_net_contribution_zero_when_no_events():
    s = _make_summary()
    assert s["net_contribution"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  build_portfolio
# ══════════════════════════════════════════════════════════════════════════════

def test_portfolio_symbols_match_top_n():
    p = build_portfolio(TOP10, _TOP10_SYMBOLS, orders_count=2)
    assert p["symbols"] == _TOP10_SYMBOLS


def test_portfolio_label_from_strategy():
    p = build_portfolio(TOP10, _TOP10_SYMBOLS)
    assert p["label"] == TOP10["dashboard"]["portfolio_label"]


def test_portfolio_rebalance_count():
    p = build_portfolio(TOP10, _TOP10_SYMBOLS, orders_count=3)
    assert p["rebalance_count"] == 3


# ══════════════════════════════════════════════════════════════════════════════
#  build_positions
# ══════════════════════════════════════════════════════════════════════════════

def test_positions_no_duplicates():
    pos = build_positions(_POSITIONS_SAMPLE, _TOP10_SYMBOLS, _NAV)
    symbols = [p["symbol"] for p in pos]
    assert len(symbols) == len(set(symbols))


def test_positions_weight_sums_near_100():
    # 只有兩個持倉時，weight 加總不會是 100，但應為正數
    pos = build_positions(_POSITIONS_SAMPLE, _TOP10_SYMBOLS, _NAV)
    total_mv = sum(p["market_value"] for p in pos)
    expected_weight = total_mv / _NAV * 100
    total_weight = sum(p["weight"] for p in pos)
    assert abs(total_weight - expected_weight) < 0.1


def test_positions_market_value_approx_qty_times_price():
    pos = build_positions(_POSITIONS_SAMPLE, _TOP10_SYMBOLS, _NAV)
    for p in pos:
        expected_mv = p["qty"] * p["current_price"]
        assert abs(p["market_value"] - expected_mv) < 1.0


def test_positions_in_portfolio_consistent():
    pos = build_positions(_POSITIONS_SAMPLE, _TOP10_SYMBOLS, _NAV)
    for p in pos:
        if p["symbol"] in _TOP10_SYMBOLS:
            assert p["in_portfolio"] is True
        else:
            assert p["in_portfolio"] is False


def test_positions_unrealized_plpc_is_percent():
    """unrealized_plpc 應是百分比形式（e.g. 28.1），不是小數（0.281）"""
    pos = build_positions(_POSITIONS_SAMPLE, _TOP10_SYMBOLS, _NAV)
    nvda = next(p for p in pos if p["symbol"] == "NVDA")
    # 原始值 0.281 → 應轉換為 28.1
    assert nvda["unrealized_plpc"] > 1.0


def test_positions_sorted_by_market_value_desc():
    pos = build_positions(_POSITIONS_SAMPLE, _TOP10_SYMBOLS, _NAV)
    mvs = [p["market_value"] for p in pos]
    assert mvs == sorted(mvs, reverse=True)
