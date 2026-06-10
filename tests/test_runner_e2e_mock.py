"""End-to-end mock test：runner.py 完整路徑（mock 所有 broker + market data I/O）。

驗證：給定固定的 spec + factor_values + broker state，runner 能跑出
與 main.py 流程一致的結果。
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date as _date

import pytest


ROOT = Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(ROOT))


def test_runner_full_flow_mocked(tmp_path, monkeypatch):
    """完整跑一遍 runner.run()，所有外部 I/O 用 mock。"""
    import runner
    import portfolio as pf

    # ── Mock factor fetch ────────────────────────────────────────────
    universe = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSM", "ASML",
        "AVGO", "AMD", "ORCL", "CRM", "ADBE", "CSCO", "INTC", "QCOM",
        "TXN", "NOW", "V", "MA", "IBM", "NFLX", "UBER", "SNOW", "PLTR",
    ]
    prices = {s: 100.0 + i for i, s in enumerate(universe)}
    mcaps = {s: (1_000_000_000 * (25 - i)) for i, s in enumerate(universe)}

    def fake_fetch_factor_values(needed, all_symbols, api_key, api_secret, market="us"):
        out = {"price": prices, "market_cap": mcaps}
        return out

    monkeypatch.setattr(runner, "fetch_factor_values", fake_fetch_factor_values)

    # ── Mock BrokerClient ────────────────────────────────────────────
    class FakeBroker:
        broker_id = "alpaca"
        environment = "paper"
        api_key = "PK_TEST"
        api_secret = "SECRET_TEST"
        def is_trading_day(self, today=None): return True
        def get_account_nav(self): return (100_000.0, 100_000.0)
        def get_current_positions(self): return []

    monkeypatch.setattr(
        "brokers.from_env.build_client_for_account",
        lambda aid: FakeBroker(),
    )

    # ── Mock trader.execute_rebalance (不真下單) ────────────────────
    captured_orders = []
    def fake_execute(client, orders, dry_run, account_id, strategy):
        captured_orders.extend(orders)
        return [f"order_{i}" for i in range(len(orders))]
    monkeypatch.setattr("trader.execute_rebalance", fake_execute)

    # ── Mock _is_first_trading_day_of_month (因為 FakeBroker 沒 _request) ─
    monkeypatch.setattr(runner, "_is_first_trading_day_of_month",
                        lambda client, today: True)

    # ── 跑 runner ────────────────────────────────────────────────────
    rc = runner.run(
        strategy_id="top10",
        account_id="99",
        data_dir=tmp_path,
        dry_run=False,
        date_override="2026-06-01",   # 月初首交易日
    )

    assert rc == 0, "runner 應該成功"

    # ── 驗證：應有 BUY 10 檔 ─────────────────────────────────────────
    assert len(captured_orders) > 0
    buys = [o for o in captured_orders if o.action == "BUY"]
    assert len(buys) >= 10, f"應該至少 BUY 10 檔，實際 {len(buys)}"

    # 都該是 top 10 by mcap = universe[:10]
    top10_symbols = set(universe[:10])
    buy_syms = {o.symbol for o in buys}
    assert buy_syms == top10_symbols, (
        f"BUY 對象應該是 top10 by mcap：\n"
        f"  期望: {sorted(top10_symbols)}\n"
        f"  實際: {sorted(buy_syms)}"
    )

    # ── 驗證 state 已寫出 ────────────────────────────────────────────
    state_file = tmp_path / "portfolio_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["date"] == "2026-06-01"
    assert sorted(state["top10"]) == sorted(top10_symbols)


def test_runner_skips_on_non_trading_day(tmp_path, monkeypatch):
    """非交易日 → runner 應該守門擋下並 record_skip。"""
    import runner

    class FakeBroker:
        broker_id = "alpaca"; environment = "paper"
        api_key = "x"; api_secret = "y"
        def is_trading_day(self, today=None): return False
        def get_account_nav(self): return (0.0, 0.0)
        def get_current_positions(self): return []

    monkeypatch.setattr(
        "brokers.from_env.build_client_for_account",
        lambda aid: FakeBroker(),
    )

    rc = runner.run(
        strategy_id="top10",
        account_id="99",
        data_dir=tmp_path,
        dry_run=False,
        date_override="2026-06-06",   # 週末
    )
    assert rc == 0  # skip 也算成功（exit code 0）


def test_runner_dry_run_bypasses_monthly_guard(tmp_path, monkeypatch):
    """dry_run 模式下，monthly 策略在非月初首日也應該跑（為了測試完整流程）。"""
    import runner

    universe = ["AAPL", "MSFT", "NVDA"]
    prices = {s: 100.0 for s in universe}
    mcaps = {s: 1e9 for s in universe}

    def fake_fetch(needed, all_symbols, api_key, api_secret, market="us"):
        return {"price": prices, "market_cap": mcaps}
    monkeypatch.setattr(runner, "fetch_factor_values", fake_fetch)

    class FakeBroker:
        broker_id = "alpaca"; environment = "paper"
        api_key = "x"; api_secret = "y"
        def is_trading_day(self, today=None): return True
        def get_account_nav(self): return (100_000.0, 100_000.0)
        def get_current_positions(self): return []
    monkeypatch.setattr(
        "brokers.from_env.build_client_for_account",
        lambda aid: FakeBroker(),
    )

    captured = []
    monkeypatch.setattr(
        "trader.execute_rebalance",
        lambda client, orders, dry_run, account_id, strategy: captured.extend(orders),
    )

    rc = runner.run(
        strategy_id="top10",
        account_id="99",
        data_dir=tmp_path,
        dry_run=True,
        date_override="2026-06-15",   # 月中（不是月初）
    )
    assert rc == 0
    # dry_run 應該跑完並產出 state（不論有沒有 orders）
    assert (tmp_path / "portfolio_state.json").exists()
