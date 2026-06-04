"""Parity test: 新 runner.py 與 main.py 對同樣 state 應產生相同 orders。

直接呼叫 portfolio.calculate_rebalance 兩次（一次模擬 main.py 流程，
一次模擬 runner.py 流程），比對 orders 完全相同。

不啟動 subprocess、不打網路 — 純函式對拍。
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

import portfolio as pf
from engine.selection import select_portfolio


def _load_top10_spec():
    return json.loads((ROOT / "strategies" / "top10_v3.json").read_text(encoding="utf-8"))


def test_top10_parity_no_change():
    """既有持股 = picks → 兩條路徑都 0 訂單。"""
    spec = _load_top10_spec()
    universe = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "ASML",
                "AVGO", "AMD", "ORCL", "CRM", "ADBE", "CSCO", "INTC"]
    prices = {s: 100.0 for s in universe}
    mcaps = {s: (15 - i) * 1e11 for i, s in enumerate(universe)}

    # 既有持股 = top 10
    top10 = sorted(universe, key=lambda s: mcaps[s], reverse=True)[:10]
    holdings = {s: 100 for s in top10}
    positions = [
        pf.Position(symbol=s, qty=q, avg_entry_price=prices[s],
                    current_price=prices[s], market_value=q * prices[s], unrealized_pl=0.0, unrealized_plpc=0.0)
        for s, q in holdings.items()
    ]
    nav = sum(p.market_value for p in positions)

    # ── Path A: main.py 流程（直接傳 top10 給 calculate_rebalance）─────
    path_a = pf.calculate_rebalance(
        current_positions=positions, top10_symbols=top10,
        current_prices=prices, account_nav=nav, available_cash=0.0,
    )

    # ── Path B: runner.py 流程（selection.select_portfolio 算 picks）──
    picks_b = select_portfolio(
        spec,
        {"__all__": universe},
        {"market_cap": mcaps, "price": prices},
    )
    path_b = pf.calculate_rebalance(
        current_positions=positions, top10_symbols=picks_b,
        current_prices=prices, account_nav=nav, available_cash=0.0,
    )

    # 對拍
    sig_a = sorted([(o.symbol, o.action, round(o.qty, 4)) for o in path_a])
    sig_b = sorted([(o.symbol, o.action, round(o.qty, 4)) for o in path_b])
    assert sig_a == sig_b, f"\nPath A: {sig_a}\nPath B: {sig_b}"
    # 兩條都該無單
    assert len(sig_a) == 0


def test_top10_parity_one_swap():
    """1 檔換掉 → 兩條路徑產生相同 SELL + BUY。"""
    spec = _load_top10_spec()
    # 把 ORCL（排第 11）市值灌高，讓它取代 INTC
    universe = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "ASML",
                "AVGO", "AMD", "ORCL", "CRM", "ADBE", "CSCO", "INTC"]
    prices = {s: 100.0 for s in universe}
    mcaps = {s: (15 - i) * 1e11 for i, s in enumerate(universe)}
    mcaps["ORCL"] = 99 * 1e11   # 讓 ORCL > INTC（第 10 是 AMD = 6e11 / INTC = 1e11）
    # top10 by mcap (排序後)
    top10_b = sorted(universe, key=lambda s: mcaps[s], reverse=True)[:10]

    # 既有持股 = 改前的 top 10（含 INTC）
    old_top10 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM",
                 "ASML", "AVGO", "AMD"]
    holdings = {s: 100 for s in old_top10}
    positions = [
        pf.Position(symbol=s, qty=q, avg_entry_price=prices[s],
                    current_price=prices[s], market_value=q * prices[s], unrealized_pl=0.0, unrealized_plpc=0.0)
        for s, q in holdings.items()
    ]
    nav = sum(p.market_value for p in positions) + 1000

    # Path A：手動指定 picks
    path_a = pf.calculate_rebalance(
        current_positions=positions, top10_symbols=top10_b,
        current_prices=prices, account_nav=nav, available_cash=1000.0,
    )

    # Path B：透過 selection 算
    picks_b = select_portfolio(
        spec, {"__all__": universe},
        {"market_cap": mcaps, "price": prices},
    )
    path_b = pf.calculate_rebalance(
        current_positions=positions, top10_symbols=picks_b,
        current_prices=prices, account_nav=nav, available_cash=1000.0,
    )

    # 對拍
    sig_a = sorted([(o.symbol, o.action, round(o.qty, 4)) for o in path_a])
    sig_b = sorted([(o.symbol, o.action, round(o.qty, 4)) for o in path_b])
    assert sig_a == sig_b, (
        f"\nPicks_b: {picks_b}\nTop10_b: {top10_b}\n"
        f"Path A: {sig_a}\nPath B: {sig_b}"
    )
    # 必須有 SELL（換股）或無單（picks 算出來等同既有）
    # selection 算出的 picks 必須等於手動算的 top10_b
    assert sorted(picks_b) == sorted(top10_b)


def test_top10_parity_first_setup():
    """空帳戶（全現金）→ 應 BUY 10 檔，兩路徑相同。"""
    spec = _load_top10_spec()
    universe = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "ASML",
                "AVGO", "AMD", "ORCL", "CRM", "ADBE", "CSCO", "INTC"]
    prices = {s: 100.0 for s in universe}
    mcaps = {s: (15 - i) * 1e11 for i, s in enumerate(universe)}

    top10 = sorted(universe, key=lambda s: mcaps[s], reverse=True)[:10]
    positions = []  # 空帳戶
    nav, cash = 100000.0, 100000.0

    # Path A: main.py
    path_a = pf.calculate_rebalance(
        current_positions=positions, top10_symbols=top10,
        current_prices=prices, account_nav=nav, available_cash=cash,
    )
    # Path B: runner.py
    picks_b = select_portfolio(
        spec, {"__all__": universe},
        {"market_cap": mcaps, "price": prices},
    )
    path_b = pf.calculate_rebalance(
        current_positions=positions, top10_symbols=picks_b,
        current_prices=prices, account_nav=nav, available_cash=cash,
    )

    sig_a = sorted([(o.symbol, o.action, round(o.qty, 4)) for o in path_a])
    sig_b = sorted([(o.symbol, o.action, round(o.qty, 4)) for o in path_b])
    assert sig_a == sig_b
    # 必為 BUY 各 1 檔（new_entrant），無 SELL
    assert all(o.action == "BUY" for o in path_a)
    assert len(sig_a) >= 10
