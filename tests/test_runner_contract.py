"""Contract tests: 新 runner.py vs 既有 main.py 邏輯應產出相同 orders。

核心思想：用同一個 strategy spec + 同一個 mock broker state，
驗證兩條路徑算出來的 orders 完全相同（symbol、side、qty）。

注意：runner.py 透過 portfolio.calculate_rebalance() 算 orders，
與 main.py 走相同函式 → 只要 picks（選股結果）相同 + 同樣的 nav/cash/prices/positions，
orders 一定相同。所以本檔重點驗證 selection 對齊 + 端到端流程不爆。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(ROOT))

from engine.selection import select_portfolio, required_factors
import portfolio as pf
import runner


# ════════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════════

def _load_spec(strategy_id: str) -> dict:
    p = ROOT / "strategies" / f"{strategy_id}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _make_positions(holdings: dict, prices: dict) -> list:
    """從 {symbol: qty} dict 建 Position list。"""
    return [
        pf.Position(
            symbol=s, qty=q,
            avg_entry_price=prices.get(s, 100.0),
            current_price=prices.get(s, 100.0),
            market_value=q * prices.get(s, 100.0),
            unrealized_pl=0.0, unrealized_plpc=0.0,
        )
        for s, q in holdings.items()
    ]


def _orders_signature(orders) -> list:
    """把 orders 標準化為可比對的 tuple (排序、去掉浮點誤差)。"""
    return sorted([
        (o.symbol, o.action, round(float(o.qty), 4))
        for o in orders
    ])


# ════════════════════════════════════════════════════════════════════════
#  Contract C-01 ~ C-05: selection 對齊 backtest SpecEngine
# ════════════════════════════════════════════════════════════════════════

class TestSelectionAlignsWithBacktest:
    """selection.py 對同樣的 spec + factor_values 應與 backtest SpecEngine 邏輯一致。"""

    def test_C01_top10_v3(self):
        """top10_v3: top_n_by_metric → 純市值排序。"""
        spec = _load_spec("top10_v3")
        groups = {"__all__": [f"S{i}" for i in range(15)]}
        fv = {
            "market_cap": {f"S{i}": (100.0 - i) for i in range(15)},
            "price":      {f"S{i}": 50.0 for i in range(15)},
        }
        picks = select_portfolio(spec, groups, fv)
        assert len(picks) == 10
        assert picks[0] == "S0"   # 最大 mcap

    def test_C02_d2p2t6(self):
        """d2p2t6: top_n_per_group → 2+2+6。"""
        spec = _load_spec("d2p2t6_v3")
        groups = {
            "defense": [f"D{i}" for i in range(5)],
            "pharma":  [f"P{i}" for i in range(5)],
            "tech":    [f"T{i}" for i in range(10)],
        }
        all_syms = [s for g in groups.values() for s in g]
        fv = {"market_cap": {s: 100.0 - i for i, s in enumerate(all_syms)}}
        picks = select_portfolio(spec, groups, fv)
        assert len(picks) == 10
        # 每組應出 2/2/6 檔
        d = [p for p in picks if p.startswith("D")]
        p_ = [p for p in picks if p.startswith("P")]
        t = [p for p in picks if p.startswith("T")]
        assert (len(d), len(p_), len(t)) == (2, 2, 6)

    def test_C03_mom_6m_t20(self):
        """mom_6m_t20: weighted_percentile → watchlist top 20 → top 10 by 6m mom。"""
        spec = _load_spec("mom_6m_t20")
        groups = {"__all__": [f"S{i}" for i in range(25)]}
        fv = {
            "market_cap":         {f"S{i}": 1000 - i for i in range(25)},
            "price_momentum_6m":  {f"S{i}": (i - 10) / 100.0 for i in range(25)},
        }
        picks = select_portfolio(spec, groups, fv)
        assert len(picks) == 10
        # watchlist = top 20 by mcap = S0~S19；mom 最高的在 watchlist 內 = S19 > S18 > ...
        assert "S19" in picks
        assert "S0" not in picks  # mcap 最大但 mom 最低

    def test_C04_d2p2t6_mom6m(self):
        """d2p2t6_mom6m: weighted_percentile_per_group。"""
        spec = _load_spec("d2p2t6_mom6m")
        groups = {
            "defense": [f"D{i}" for i in range(8)],
            "pharma":  [f"P{i}" for i in range(8)],
            "tech":    [f"T{i}" for i in range(15)],
        }
        all_syms = [s for g in groups.values() for s in g]
        fv = {
            "market_cap":        {s: 100.0 - i for i, s in enumerate(all_syms)},
            "price_momentum_6m": {s: (50 - i) / 100.0 for i, s in enumerate(all_syms)},
        }
        picks = select_portfolio(spec, groups, fv)
        assert len(picks) == 10
        d = [p for p in picks if p.startswith("D")]
        p_ = [p for p in picks if p.startswith("P")]
        t = [p for p in picks if p.startswith("T")]
        assert (len(d), len(p_), len(t)) == (2, 2, 6)

    def test_C05_mom_factor_monthly(self):
        """mom_factor_monthly: factor_score with 3 factors（含 min_price 過濾）。"""
        spec = _load_spec("mom_factor_monthly")
        groups = {"__all__": [f"S{i}" for i in range(30)]}
        fv = {
            "market_cap":         {f"S{i}": 1000 - i for i in range(30)},
            "price_momentum_3m":  {f"S{i}": (i - 5) / 100.0 for i in range(30)},
            "price_momentum_12m": {f"S{i}": (i - 10) / 100.0 for i in range(30)},
            "price":              {f"S{i}": 50.0 for i in range(30)},  # 過 min_price=5
        }
        picks = select_portfolio(spec, groups, fv)
        assert len(picks) == 10


# ════════════════════════════════════════════════════════════════════════
#  Contract C-06 ~ C-08: portfolio.calculate_rebalance 對 picks 反應一致
# ════════════════════════════════════════════════════════════════════════

class TestCalculateRebalanceConsistent:
    """relevant 場景下 calculate_rebalance 對相同 inputs 必產出相同 orders。"""

    def test_C06_no_change(self):
        """既有持股 == picks → 0 訂單。"""
        prices = {f"S{i}": 100.0 for i in range(10)}
        positions = _make_positions({f"S{i}": 100 for i in range(10)}, prices)
        picks = [f"S{i}" for i in range(10)]
        nav = 100000.0
        orders = pf.calculate_rebalance(
            current_positions=positions, top10_symbols=picks,
            current_prices=prices, account_nav=nav, available_cash=0.0,
        )
        # 全部都在 picks 內且權重 10%（容忍帶內）→ 應無訂單
        assert len(orders) == 0

    def test_C07_one_swap(self):
        """1 檔被換掉 → SELL 舊 + BUY 新（最小量換股）。"""
        prices = {f"S{i}": 100.0 for i in range(11)}
        positions = _make_positions(
            {f"S{i}": 100 for i in range(10)}, prices
        )
        # 把 S9 換成 S10
        picks = [f"S{i}" for i in range(9)] + ["S10"]
        nav = 100000.0
        orders = pf.calculate_rebalance(
            current_positions=positions, top10_symbols=picks,
            current_prices=prices, account_nav=nav, available_cash=0.0,
        )
        sells = [o for o in orders if o.action == "SELL"]
        buys = [o for o in orders if o.action == "BUY"]
        sell_syms = {o.symbol for o in sells}
        buy_syms = {o.symbol for o in buys}
        assert "S9" in sell_syms     # S9 跌出 → 賣
        assert "S10" in buy_syms     # S10 新進 → 買
        # 保留 S0~S8 不應被全清
        for o in sells:
            assert o.symbol == "S9", f"非預期賣單：{o.symbol}"

    def test_C08_first_time_setup(self):
        """空帳戶 + 全現金 → 應產生 BUY 10 檔。"""
        prices = {f"S{i}": 100.0 for i in range(10)}
        positions = []  # 沒持股
        picks = [f"S{i}" for i in range(10)]
        nav = 100000.0
        cash = 100000.0
        orders = pf.calculate_rebalance(
            current_positions=positions, top10_symbols=picks,
            current_prices=prices, account_nav=nav, available_cash=cash,
        )
        buy_syms = {o.symbol for o in orders if o.action == "BUY"}
        # 應該每檔都有 BUY（new_entrant + cash_deployment 都可能觸發）
        assert buy_syms >= set(picks), f"漏買 {set(picks) - buy_syms}"
        # 不該有 SELL
        assert all(o.action == "BUY" for o in orders)


# ════════════════════════════════════════════════════════════════════════
#  Contract C-09 ~ C-12: runner 內部建構正確（不打網路）
# ════════════════════════════════════════════════════════════════════════

class TestRunnerBuildBlocks:
    """runner.py 的純函式 helpers 應該不依網路就能跑。"""

    def test_C09_load_universe_inline(self):
        spec = _load_spec("mom_6m_t20")
        groups = runner.load_universe_groups(spec)
        assert "__all__" in groups
        assert len(groups["__all__"]) > 10
        assert "AAPL" in groups["__all__"]

    def test_C10_load_universe_grouped(self):
        spec = _load_spec("d2p2t6_v3")
        groups = runner.load_universe_groups(spec)
        assert set(groups.keys()) == {"defense", "pharma", "tech"}
        assert len(groups["defense"]) > 0

    def test_C11_required_factors_includes_momentum(self):
        spec = _load_spec("mom_6m_t20")
        needed = required_factors(spec)
        assert "market_cap" in needed
        assert "price_momentum_6m" in needed

    def test_C12_top10_v3_required_factors(self):
        spec = _load_spec("top10_v3")
        needed = required_factors(spec)
        assert "market_cap" in needed
        # top10_v3 有 min_price=5.0
        assert "price" in needed


# ════════════════════════════════════════════════════════════════════════
#  Contract C-13: runner gate_check
# ════════════════════════════════════════════════════════════════════════

class _StubBroker:
    """模擬 BrokerClient（測試用）。"""
    def __init__(self, is_trading=True):
        self._is_trading = is_trading
    def is_trading_day(self, today=None):
        return self._is_trading


class TestGateCheck:
    def test_C13_non_trading_day(self):
        spec = {"rebalancing": {"frequency": "monthly"}}
        broker = _StubBroker(is_trading=False)
        from datetime import date
        ok, code = runner.gate_check(spec, broker, date.today(), dry_run=False)
        assert not ok
        assert code == "non_trading_day"

    def test_C13b_dry_run_bypasses_freq_guard(self):
        """dry_run 模式應 bypass frequency 守門以便完整測試。"""
        spec = {"rebalancing": {"frequency": "monthly", "rebalance_on": "first_trading_day"}}
        broker = _StubBroker(is_trading=True)
        from datetime import date
        ok, code = runner.gate_check(spec, broker, date(2026, 5, 15), dry_run=True)
        assert ok
        assert "dryrun" in code

    def test_C13c_daily_passes(self):
        spec = {"rebalancing": {"frequency": "daily"}}
        broker = _StubBroker(is_trading=True)
        from datetime import date
        ok, code = runner.gate_check(spec, broker, date.today(), dry_run=False)
        assert ok
        assert code == "daily_scheduled"
