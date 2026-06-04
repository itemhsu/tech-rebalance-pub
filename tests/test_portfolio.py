"""tests/test_portfolio.py — 持倉管理與再平衡演算法測試"""
from __future__ import annotations

import sys
import json
import tempfile
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from portfolio import (
    Position, RebalanceOrder, PortfolioState,
    calculate_rebalance, calculate_nav,
    save_state, load_state, append_history,
    TARGET_WEIGHT, WEIGHT_TOLERANCE, MIN_ORDER_VALUE,
)


# ── 工具函式 ──────────────────────────────────────────────────────────────────
def make_pos(symbol: str, qty: float, px: float, avg_px: Optional[float] = None) -> Position:
    avg_px   = avg_px or px
    mkt_val  = qty * px
    cost     = qty * avg_px
    unreal   = mkt_val - cost
    return Position(
        symbol=symbol, qty=qty, avg_entry_price=avg_px,
        current_price=px, market_value=mkt_val,
        unrealized_pl=unreal, unrealized_plpc=unreal/cost if cost>0 else 0,
    )

def nav_100k():
    return 100_000.0

def prices_standard():
    return {
        "AAPL": 190.0, "MSFT": 400.0, "NVDA": 800.0, "GOOGL": 170.0,
        "AMZN": 185.0, "META": 500.0, "TSM": 180.0, "AVGO": 1200.0,
        "ORCL": 130.0, "V": 270.0,
        "INTC": 25.0,  # 非前10，用來測試 exit
    }

def top10_standard():
    return ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSM","AVGO","ORCL","V"]


# ── 測試：無異動 ──────────────────────────────────────────────────────────────
class TestNoChangeNeeded:
    def test_all_within_tolerance(self):
        """所有持股偏差在容忍帶內 → orders 應為空"""
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # 每檔配置剛好 10%
        positions = [make_pos(s, nav * 0.10 / prices[s], prices[s]) for s in top10]
        orders = calculate_rebalance(positions, top10, prices, nav, 0.0)
        assert orders == []

    def test_slight_deviation_within_tolerance(self):
        """偏差 < 2% → 不觸發"""
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # 給每檔 ±1% 的偏差
        positions = [make_pos(s, nav * 0.10 / prices[s] * 1.005, prices[s]) for s in top10[:5]]
        positions += [make_pos(s, nav * 0.10 / prices[s] * 0.995, prices[s]) for s in top10[5:]]
        orders = calculate_rebalance(positions, top10, prices, nav, 0.0)
        assert orders == []


# ── 測試：賣出跌出前10的股票 ─────────────────────────────────────────────────
class TestExitTop10:
    def test_generates_sell_order(self):
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # 持有 INTC（不在 top10）
        positions = [
            make_pos(s, nav * 0.09 / prices[s], prices[s]) for s in top10
        ] + [make_pos("INTC", 100.0, 25.0)]
        orders = calculate_rebalance(positions, top10, prices, nav, 0.0)
        sells = [o for o in orders if o.action == "SELL" and o.symbol == "INTC"]
        assert len(sells) == 1
        assert sells[0].reason == "exit_top10"
        assert sells[0].qty == pytest.approx(100.0)

    def test_sell_full_quantity(self):
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        positions = [make_pos("INTC", 400.0, 25.0)]  # 只持有 INTC
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=10000.0)
        sells = [o for o in orders if o.action == "SELL" and o.symbol == "INTC"]
        assert sells[0].qty == pytest.approx(400.0)


# ── 測試：買入新進前10的股票 ─────────────────────────────────────────────────
class TestNewEntrant:
    def test_generates_buy_order(self):
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # 只持有前9（缺少 "V"）
        positions = [make_pos(s, nav * 0.10 / prices[s], prices[s]) for s in top10[:9]]
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=10000.0)
        buys = [o for o in orders if o.action == "BUY" and o.symbol == "V"]
        assert len(buys) == 1
        assert buys[0].reason == "new_entrant"
        assert buys[0].qty > 0

    def test_buy_with_proceeds_from_sell(self):
        """賣出舊股的收益應用於買入新進股"""
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # 持有 INTC 替代 V
        positions = [make_pos(s, nav * 0.10 / prices[s], prices[s]) for s in top10[:9]]
        positions.append(make_pos("INTC", 400.0, 25.0))  # INTC = $10,000
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=0.0)
        sell_syms = [o.symbol for o in orders if o.action == "SELL"]
        buy_syms  = [o.symbol for o in orders if o.action == "BUY"]
        assert "INTC" in sell_syms
        assert "V" in buy_syms


# ── 測試：現金部署 ───────────────────────────────────────────────────────────
class TestCashDeployment:
    def test_deploys_idle_cash_to_existing_holdings(self):
        """帳戶有閒置現金且持倉齊全 → 應生成 cash_deployment 買單加碼現有持股"""
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # 持有前10，但每檔只配置 9%（剩下 10% 現金），現金 > NAV 1% 應觸發部署
        positions = [make_pos(s, nav * 0.09 / prices[s], prices[s]) for s in top10]
        extra_cash = nav * 0.10  # 10% 閒置現金
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=extra_cash)
        buys = [o for o in orders if o.action == "BUY"]
        assert len(buys) > 0
        # 無 new_entrant（持股齊全），全部應為 cash_deployment 或 weight_adjust
        assert all(o.reason in ("cash_deployment", "weight_adjust") for o in buys)

    def test_first_run_all_cash_buys_as_new_entrant(self):
        """無持倉、全現金 → 所有買入以 new_entrant 身份執行（非 cash_deployment）"""
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        orders = calculate_rebalance([], top10, prices, nav, available_cash=nav)
        buys = [o for o in orders if o.action == "BUY"]
        assert len(buys) == len(top10)
        assert all(o.reason == "new_entrant" for o in buys)

    def test_cash_below_threshold_no_deploy(self):
        """現金低於 NAV 1% → 不觸發 cash_deployment"""
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        positions = [make_pos(s, nav * 0.10 / prices[s], prices[s]) for s in top10]
        tiny_cash = nav * 0.005   # 0.5%，低於門檻
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=tiny_cash)
        assert orders == []


# ── 測試：訂單排序（SELL 優先）───────────────────────────────────────────────
class TestOrderSorting:
    def test_sell_before_buy(self):
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        positions = [make_pos("INTC", 400.0, 25.0)]  # 只持有 INTC，需要賣
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=nav)
        actions = [o.action for o in orders]
        last_sell = max((i for i, a in enumerate(actions) if a == "SELL"), default=-1)
        first_buy = min((i for i, a in enumerate(actions) if a == "BUY"),  default=999)
        assert last_sell < first_buy, "所有 SELL 訂單應排在 BUY 訂單前"


# ── 測試：最小訂單金額 ───────────────────────────────────────────────────────
class TestMinimumOrderValue:
    def test_tiny_order_skipped(self):
        """計算出的訂單金額 < $1 → 不生成訂單"""
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # 給每檔配置剛好 10% 但加上非常小的偏差（遠低於 $1）
        positions = [make_pos(s, nav * 0.10 / prices[s], prices[s]) for s in top10]
        # 以超小現金觸發，但每股只能買非常少
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=0.001)
        deploy_orders = [o for o in orders if o.reason == "cash_deployment"]
        assert all(o.estimated_value >= MIN_ORDER_VALUE for o in deploy_orders)


# ── 測試：首次建倉（全現金）──────────────────────────────────────────────────
class TestFirstRun:
    def test_all_cash_generates_10_buys(self):
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        orders = calculate_rebalance([], top10, prices, nav, available_cash=nav)
        buys = [o for o in orders if o.action == "BUY"]
        assert len(buys) == 10
        symbols_bought = {o.symbol for o in buys}
        assert symbols_bought == set(top10)


# ── 測試：容忍帶外觸發調整 ───────────────────────────────────────────────────
class TestWeightAdjustment:
    def test_deviation_within_tolerance_no_order(self):
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # AAPL 偏差 1.5%（小於 2% 容忍帶）
        positions = [make_pos("AAPL", nav * 0.115 / prices["AAPL"], prices["AAPL"])]
        positions += [make_pos(s, nav * 0.10 / prices[s], prices[s]) for s in top10[1:]]
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=0.0)
        adjust = [o for o in orders if o.reason == "weight_adjust" and o.symbol == "AAPL"]
        assert adjust == []

    def test_deviation_outside_tolerance_generates_order(self):
        nav    = nav_100k()
        top10  = top10_standard()
        prices = prices_standard()
        # AAPL 比重高達 15%（超出 2% 容忍帶）
        positions = [make_pos("AAPL", nav * 0.15 / prices["AAPL"], prices["AAPL"])]
        positions += [make_pos(s, nav * 0.094 / prices[s], prices[s]) for s in top10[1:]]
        orders = calculate_rebalance(positions, top10, prices, nav, available_cash=0.0)
        adjust = [o for o in orders if o.reason == "weight_adjust" and o.symbol == "AAPL"]
        assert len(adjust) == 1
        assert adjust[0].action == "SELL"   # 15% > 10%，應減碼


# ── 測試：NAV 計算 ───────────────────────────────────────────────────────────
class TestCalculateNav:
    def test_nav_equals_cash_plus_positions(self):
        positions = [make_pos("AAPL", 10, 190.0), make_pos("MSFT", 5, 400.0)]
        cash = 1000.0
        nav  = calculate_nav(positions, cash)
        assert nav == pytest.approx(10 * 190 + 5 * 400 + 1000)

    def test_nav_no_positions(self):
        assert calculate_nav([], 5000.0) == pytest.approx(5000.0)


# ── 測試：持倉序列化/反序列化 ────────────────────────────────────────────────
class TestStateSerialization:
    def test_save_and_load(self):
        state = PortfolioState(
            date  = "2026-05-05",
            nav   = 100_000.0,
            cash  = 1_000.0,
            positions = [make_pos("AAPL", 10, 190.0)],
            top10 = ["AAPL"],
            orders_executed = [
                RebalanceOrder("AAPL", "BUY", 10.0, "new_entrant", 1900.0)
            ],
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = Path(f.name)

        save_state(state, path=tmp_path)
        loaded = load_state(path=tmp_path)
        tmp_path.unlink()

        assert loaded is not None
        assert loaded.date  == "2026-05-05"
        assert loaded.nav   == pytest.approx(100_000.0)
        assert loaded.cash  == pytest.approx(1_000.0)
        assert len(loaded.positions) == 1
        assert loaded.positions[0].symbol == "AAPL"
        assert len(loaded.orders_executed) == 1

    def test_load_nonexistent_returns_none(self):
        result = load_state(path=Path("/tmp/nonexistent_xyz_12345.json"))
        assert result is None
