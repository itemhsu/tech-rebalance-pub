"""
tests/test_unit8_integration.py — Unit 8: write_data_json() 端對端整合測試
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.accounts import Account
from engine.data_writer import write_data_json
from engine.data_validator import validate_data_json
from engine.strategy_loader import load_and_validate

TOP10  = load_and_validate("top10")
D2P2T6 = load_and_validate("d2p2t6")

_ACCOUNT_1 = Account(id="1", strategy="top10",  label="帳戶 #1 (TOP10)")
_ACCOUNT_2 = Account(id="2", strategy="d2p2t6", label="帳戶 #2 (D2P2T6)")

_POSITIONS = [
    {"symbol": "NVDA", "qty": 30.0, "avg_entry_price": 820.0,
     "current_price": 1050.4, "market_value": 31512.0,
     "unrealized_pl": 6912.0, "unrealized_plpc": 0.281},
    {"symbol": "MSFT", "qty": 30.0, "avg_entry_price": 380.0,
     "current_price": 415.2, "market_value": 12456.0,
     "unrealized_pl": 1056.0, "unrealized_plpc": 0.0926},
]

_TOP10_SYMBOLS = ["NVDA", "MSFT", "AAPL", "GOOGL", "META",
                  "AMZN", "TSLA", "AVGO", "AMD", "TSM"]

_RANKED_STOCKS = [
    {"rank": i+1, "symbol": s, "close_price": 100.0 + i * 10,
     "market_cap": (20 - i) * 1e11, "chg_pct": 0.5}
    for i, s in enumerate(_TOP10_SYMBOLS)
]

_D2P2T6_SYMBOLS = ["RTX", "LMT", "LLY", "JNJ",
                   "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "AVGO"]

_GROUP_RANKINGS = {
    "defense": [
        {"sym": "RTX", "rank": 1, "price": 171.15, "chg_pct": -2.56, "mcap_b": 230.5},
        {"sym": "LMT", "rank": 2, "price": 516.11, "chg_pct": -0.85, "mcap_b": 119.0},
    ],
    "pharma": [
        {"sym": "LLY", "rank": 1, "price": 1003.52, "chg_pct": -0.18, "mcap_b": 896.1},
        {"sym": "JNJ", "rank": 2, "price": 227.38,  "chg_pct": -1.77, "mcap_b": 545.7},
    ],
    "tech": [
        {"sym": "NVDA",  "rank": 1, "price": 1050.40, "chg_pct": 2.10,  "mcap_b": 2580},
        {"sym": "MSFT",  "rank": 2, "price": 415.20,  "chg_pct": 0.80,  "mcap_b": 3080},
        {"sym": "AAPL",  "rank": 3, "price": 300.08,  "chg_pct": -0.30, "mcap_b": 2800},
        {"sym": "AMZN",  "rank": 4, "price": 262.96,  "chg_pct": -0.40, "mcap_b": 2700},
        {"sym": "GOOGL", "rank": 5, "price": 396.04,  "chg_pct": 1.20,  "mcap_b": 2400},
        {"sym": "AVGO",  "rank": 6, "price": 424.71,  "chg_pct": 0.90,  "mcap_b": 850},
    ],
}

_ORDERS = [
    {"symbol": "TSLA", "side": "sell", "qty": 5, "price": 312.40},
    {"symbol": "AMD",  "side": "buy",  "qty": 8, "price": 198.20},
]


def _write_top10(tmp_path, date="2026-05-16", existing=None, dry_run=False) -> dict:
    out = tmp_path / "1" / "data.json"
    return write_data_json(
        output_path           = out,
        strategy_cfg          = TOP10,
        account               = _ACCOUNT_1,
        same_strategy_accounts= [_ACCOUNT_1],
        nav                   = 128450.0,
        cash                  = 2340.5,
        positions             = _POSITIONS,
        top_n_symbols         = _TOP10_SYMBOLS,
        executed_orders       = _ORDERS,
        rankings_raw          = _RANKED_STOCKS,
        trading_date          = date,
        dry_run               = dry_run,
        existing_data         = existing,
    )


def _write_d2p2t6(tmp_path, date="2026-05-16", existing=None) -> dict:
    out = tmp_path / "2" / "data.json"
    return write_data_json(
        output_path           = out,
        strategy_cfg          = D2P2T6,
        account               = _ACCOUNT_2,
        same_strategy_accounts= [_ACCOUNT_2],
        nav                   = 100734.59,
        cash                  = 1609.73,
        positions             = _POSITIONS,
        top_n_symbols         = _D2P2T6_SYMBOLS,
        executed_orders       = [],
        rankings_raw          = _GROUP_RANKINGS,
        trading_date          = date,
        existing_data         = existing,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Schema 驗證
# ══════════════════════════════════════════════════════════════════════════════

def test_top10_full_data_json_passes_schema(tmp_path):
    data = _write_top10(tmp_path)
    validate_data_json(data)


def test_d2p2t6_full_data_json_passes_schema(tmp_path):
    data = _write_d2p2t6(tmp_path)
    validate_data_json(data)


def test_output_file_created(tmp_path):
    _write_top10(tmp_path)
    assert (tmp_path / "1" / "data.json").exists()


# ══════════════════════════════════════════════════════════════════════════════
#  歷史 append
# ══════════════════════════════════════════════════════════════════════════════

def test_two_consecutive_runs_accumulate_nav_history(tmp_path):
    d1 = _write_top10(tmp_path, date="2026-05-15")
    d2 = _write_top10(tmp_path, date="2026-05-16", existing=d1)
    assert len(d2["nav_history"]) == 2


def test_two_consecutive_runs_accumulate_trade_log(tmp_path):
    d1 = _write_top10(tmp_path, date="2026-05-15")
    d2 = _write_top10(tmp_path, date="2026-05-16", existing=d1)
    assert len(d2["trade_log"]) == 2


def test_trade_log_latest_first(tmp_path):
    d1 = _write_top10(tmp_path, date="2026-05-15")
    d2 = _write_top10(tmp_path, date="2026-05-16", existing=d1)
    assert d2["trade_log"][0]["date"] == "2026-05-16"


# ══════════════════════════════════════════════════════════════════════════════
#  dry_run
# ══════════════════════════════════════════════════════════════════════════════

def test_dry_run_writes_data_json_with_flag(tmp_path):
    data = _write_top10(tmp_path, dry_run=True)
    assert data["meta"]["dry_run"] is True


def test_dry_run_data_json_passes_schema(tmp_path):
    data = _write_top10(tmp_path, dry_run=True)
    validate_data_json(data)


# ══════════════════════════════════════════════════════════════════════════════
#  一致性跨 section
# ══════════════════════════════════════════════════════════════════════════════

def test_in_portfolio_consistent_across_all_sections(tmp_path):
    """portfolio.symbols ↔ positions[].in_portfolio ↔ rankings[].in_portfolio"""
    data = _write_top10(tmp_path)
    port_set = set(data["portfolio"]["symbols"])

    # positions
    for p in data["positions"]:
        expected = p["symbol"] in port_set
        assert p["in_portfolio"] == expected, \
            f"positions {p['symbol']}: in_portfolio={p['in_portfolio']}, expected={expected}"

    # rankings (market_cap_list)
    for item in data["rankings"]["items"]:
        expected = item["symbol"] in port_set
        assert item["in_portfolio"] == expected, \
            f"rankings {item['symbol']}: in_portfolio={item['in_portfolio']}, expected={expected}"


def test_account_id_in_meta_matches_account(tmp_path):
    data = _write_top10(tmp_path)
    assert data["meta"]["account_id"] == "1"


def test_email_section_present(tmp_path):
    data = _write_top10(tmp_path)
    assert "email" in data
    assert data["email"]["subject"]


def test_initial_nav_preserved_across_runs(tmp_path):
    """多次執行後 initial_nav 應保持第一次的 NAV。"""
    d1 = _write_top10(tmp_path, date="2026-05-15")
    d2 = _write_top10(tmp_path, date="2026-05-16", existing=d1)
    assert d2["summary"]["initial_nav"] == d1["summary"]["initial_nav"]
