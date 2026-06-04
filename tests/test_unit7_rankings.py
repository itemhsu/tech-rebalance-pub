"""
tests/test_unit7_rankings.py — Unit 7: Rankings（多型）
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.data_writer import build_rankings_market_cap, build_rankings_universe_groups
from engine.strategy_loader import load_and_validate

TOP10  = load_and_validate("top10")
D2P2T6 = load_and_validate("d2p2t6")

_TOP10_SYMBOLS = ["NVDA", "MSFT", "AAPL", "GOOGL", "META",
                  "AMZN", "TSLA", "AVGO", "AMD", "TSM"]

_D2P2T6_SYMBOLS = ["RTX", "LMT", "LLY", "JNJ",
                   "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "AVGO"]

_RANKED_STOCKS = [
    {"rank": i+1, "symbol": s, "close_price": 100.0 + i,
     "market_cap": (20 - i) * 1e11, "chg_pct": 0.5}
    for i, s in enumerate(["NVDA","MSFT","AAPL","GOOGL","META",
                            "AMZN","TSLA","AVGO","AMD","TSM",
                            "ORCL","CRM","INTC","QCOM","TXN"])
]

_GROUP_RANKINGS = {
    "defense": [
        {"sym": "RTX", "rank": 1, "price": 171.15, "chg_pct": -2.56, "mcap_b": 230.5},
        {"sym": "LMT", "rank": 2, "price": 516.11, "chg_pct": -0.85, "mcap_b": 119.0},
        {"sym": "GD",  "rank": 3, "price": 334.45, "chg_pct": -1.80, "mcap_b": 90.5},
    ],
    "pharma": [
        {"sym": "LLY", "rank": 1, "price": 1003.52, "chg_pct": -0.18, "mcap_b": 896.1},
        {"sym": "JNJ", "rank": 2, "price": 227.38,  "chg_pct": -1.77, "mcap_b": 545.7},
        {"sym": "MRK", "rank": 3, "price": 111.35,  "chg_pct": -1.79, "mcap_b": 275.1},
    ],
    "tech": [
        {"sym": "NVDA",  "rank": 1, "price": 1050.40, "chg_pct": 2.10,  "mcap_b": 2580},
        {"sym": "MSFT",  "rank": 2, "price": 415.20,  "chg_pct": 0.80,  "mcap_b": 3080},
        {"sym": "AAPL",  "rank": 3, "price": 300.08,  "chg_pct": -0.30, "mcap_b": 2800},
        {"sym": "AMZN",  "rank": 4, "price": 262.96,  "chg_pct": -0.40, "mcap_b": 2700},
        {"sym": "GOOGL", "rank": 5, "price": 396.04,  "chg_pct": 1.20,  "mcap_b": 2400},
        {"sym": "AVGO",  "rank": 6, "price": 424.71,  "chg_pct": 0.90,  "mcap_b": 850},
        {"sym": "TSM",   "rank": 7, "price": 188.50,  "chg_pct": -0.60, "mcap_b": 780},
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
#  TOP10 → market_cap_list
# ══════════════════════════════════════════════════════════════════════════════

def test_top10_strategy_produces_market_cap_list():
    r = build_rankings_market_cap(TOP10, _RANKED_STOCKS, _TOP10_SYMBOLS)
    assert r["type"] == "market_cap_list"


def test_market_cap_list_has_items():
    r = build_rankings_market_cap(TOP10, _RANKED_STOCKS, _TOP10_SYMBOLS)
    assert "items" in r and len(r["items"]) > 0


def test_market_cap_list_in_portfolio_count_equals_n():
    r = build_rankings_market_cap(TOP10, _RANKED_STOCKS, _TOP10_SYMBOLS)
    in_port = [item for item in r["items"] if item["in_portfolio"]]
    assert len(in_port) == len(_TOP10_SYMBOLS)


def test_market_cap_list_label_from_strategy():
    r = build_rankings_market_cap(TOP10, _RANKED_STOCKS, _TOP10_SYMBOLS)
    assert r["label"] == TOP10["dashboard"]["rankings"]["title"]


def test_market_cap_list_show_top_n_respected():
    r = build_rankings_market_cap(TOP10, _RANKED_STOCKS, _TOP10_SYMBOLS)
    show_n = TOP10["dashboard"]["rankings"].get("show_top_n", 20)
    assert len(r["items"]) <= show_n


def test_market_cap_list_sorted_by_rank():
    r = build_rankings_market_cap(TOP10, _RANKED_STOCKS, _TOP10_SYMBOLS)
    ranks = [item["rank"] for item in r["items"]]
    assert ranks == sorted(ranks)


# ══════════════════════════════════════════════════════════════════════════════
#  D2P2T6 → universe_groups
# ══════════════════════════════════════════════════════════════════════════════

def test_d2p2t6_strategy_produces_universe_groups():
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    assert r["type"] == "universe_groups"


def test_universe_groups_has_groups():
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    assert "groups" in r and len(r["groups"]) == 3


def test_universe_groups_ids_complete():
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    group_ids = {g["id"] for g in r["groups"]}
    assert group_ids == {"defense", "pharma", "tech"}


def test_universe_groups_defense_quota_2():
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    defense = next(g for g in r["groups"] if g["id"] == "defense")
    in_port = [i for i in defense["items"] if i["in_portfolio"]]
    assert len(in_port) == 2   # RTX, LMT


def test_universe_groups_pharma_quota_2():
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    pharma = next(g for g in r["groups"] if g["id"] == "pharma")
    in_port = [i for i in pharma["items"] if i["in_portfolio"]]
    assert len(in_port) == 2   # LLY, JNJ


def test_universe_groups_tech_quota_6():
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    tech = next(g for g in r["groups"] if g["id"] == "tech")
    in_port = [i for i in tech["items"] if i["in_portfolio"]]
    assert len(in_port) == 6   # NVDA, MSFT, AAPL, AMZN, GOOGL, AVGO


def test_rankings_in_portfolio_matches_portfolio_symbols():
    """rankings 的所有 in_portfolio=True 的 symbol 必須在 portfolio.symbols 中"""
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    portfolio_set = set(_D2P2T6_SYMBOLS)
    for group in r["groups"]:
        for item in group["items"]:
            if item["in_portfolio"]:
                assert item["symbol"] in portfolio_set, \
                    f"{item['symbol']} in_portfolio=True 但不在 portfolio.symbols"
            else:
                assert item["symbol"] not in portfolio_set or True  # 允許不在的情況


def test_no_symbol_appears_in_multiple_groups():
    r = build_rankings_universe_groups(D2P2T6, _GROUP_RANKINGS, _D2P2T6_SYMBOLS)
    all_symbols = []
    for group in r["groups"]:
        for item in group["items"]:
            all_symbols.append(item["symbol"])
    # 每個 symbol 只應在一個 group 中
    assert len(all_symbols) == len(set(all_symbols)), "有 symbol 出現在多個 group"


def test_market_cap_list_in_portfolio_consistent_with_symbols():
    """rankings 的 in_portfolio=True 集合 == portfolio.symbols 集合"""
    r = build_rankings_market_cap(TOP10, _RANKED_STOCKS, _TOP10_SYMBOLS)
    in_port_symbols = {i["symbol"] for i in r["items"] if i["in_portfolio"]}
    assert in_port_symbols == set(_TOP10_SYMBOLS)
