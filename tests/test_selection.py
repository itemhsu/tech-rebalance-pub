"""engine/selection.py 單元測試（P1 Day 1 — T-01~T-07）

純函式測試，不依賴網路或檔案系統。
"""
import pytest

from engine.selection import (
    _percentile_score,
    _all_symbols,
    _filter_universe,
    required_factors,
    select_portfolio,
)


# ══════════════════════════════════════════════════════════════════════
# T-01 ~ T-02: helpers
# ══════════════════════════════════════════════════════════════════════

class TestHelpers:
    def test_all_symbols_dedupes(self):
        groups = {"a": ["X", "Y"], "b": ["Y", "Z"]}
        assert _all_symbols(groups) == ["X", "Y", "Z"]

    def test_percentile_score_desc(self):
        vals = {"A": 10, "B": 20, "C": 30}
        ps = _percentile_score(vals, ["A", "B", "C"], desc=True)
        # 30 最高分 = 1.0；10 最低 = 0.0
        assert ps["C"] == 1.0
        assert ps["A"] == 0.0
        assert 0.4 <= ps["B"] <= 0.6

    def test_percentile_score_asc(self):
        vals = {"A": 10, "B": 20, "C": 30}
        ps = _percentile_score(vals, ["A", "B", "C"], desc=False)
        assert ps["A"] == 1.0
        assert ps["C"] == 0.0

    def test_percentile_score_missing_symbol(self):
        """有 symbol 沒在 values 內 → 預設 0。"""
        vals = {"A": 10}
        ps = _percentile_score(vals, ["A", "MISSING"], desc=True)
        assert ps["A"] == 0.5  # 只有 1 個 symbol 有值 → 0.5
        assert ps["MISSING"] == 0.0

    def test_filter_universe_excludes(self):
        sel = {"exclude_symbols": ["X", "Y"]}
        out = _filter_universe(sel, ["X", "Y", "Z"], {})
        assert out == ["Z"]

    def test_filter_universe_min_price(self):
        sel = {"min_price": 5.0}
        factor_values = {"price": {"A": 10, "B": 3, "C": 5}}
        out = _filter_universe(sel, ["A", "B", "C"], factor_values)
        assert out == ["A", "C"]   # B 不到 5

    def test_filter_universe_valid_set(self):
        sel = {}
        out = _filter_universe(sel, ["X", "Y", "Z"], {}, valid_symbols={"X", "Z"})
        assert out == ["X", "Z"]


# ══════════════════════════════════════════════════════════════════════
# T-01: top_n_by_metric
# ══════════════════════════════════════════════════════════════════════

class TestTopNByMetric:
    def _spec(self, **overrides):
        s = {
            "selection": {
                "method": "top_n_by_metric",
                "metric": "market_cap",
                "n": 3,
            }
        }
        s["selection"].update(overrides)
        return s

    def test_basic_ranking(self):
        spec = self._spec()
        groups = {"__all__": ["A", "B", "C", "D", "E"]}
        fv = {"market_cap": {"A": 100, "B": 500, "C": 300, "D": 200, "E": 50}}
        result = select_portfolio(spec, groups, fv)
        assert result == ["B", "C", "D"]   # top 3 by market_cap

    def test_min_price_filter(self):
        spec = self._spec(min_price=10.0, n=2)
        groups = {"__all__": ["A", "B", "C"]}
        fv = {
            "market_cap": {"A": 100, "B": 500, "C": 300},
            "price":      {"A":  20, "B":   5, "C":  15},  # B 被 min_price 擋
        }
        result = select_portfolio(spec, groups, fv)
        assert result == ["C", "A"]  # B 出局，剩下按 mcap 排

    def test_exclude_symbols(self):
        spec = self._spec(exclude_symbols=["B", "C"], n=2)
        groups = {"__all__": ["A", "B", "C", "D"]}
        fv = {"market_cap": {"A": 100, "B": 500, "C": 300, "D": 200}}
        result = select_portfolio(spec, groups, fv)
        assert result == ["D", "A"]

    def test_valid_symbols_filter(self):
        spec = self._spec(n=2)
        groups = {"__all__": ["A", "B", "C", "D"]}
        fv = {"market_cap": {"A": 100, "B": 500, "C": 300, "D": 200}}
        result = select_portfolio(spec, groups, fv, valid_symbols={"A", "C"})
        assert result == ["C", "A"]

    def test_missing_values_get_zero(self):
        spec = self._spec(n=3)
        groups = {"__all__": ["A", "B", "C"]}
        fv = {"market_cap": {"A": 100}}  # B/C 沒值
        result = select_portfolio(spec, groups, fv)
        assert result[0] == "A"
        assert len(result) == 3   # 仍會回 3 個（其他依字母序）


# ══════════════════════════════════════════════════════════════════════
# T-02: top_n_per_group
# ══════════════════════════════════════════════════════════════════════

class TestTopNPerGroup:
    def test_d2p2t6_quotas(self):
        """D2P2T6 經典場景：軍火 2 + 醫藥 2 + 科技 6 = 10。"""
        spec = {
            "selection": {
                "method": "top_n_per_group",
                "metric": "market_cap",
                "group_quotas": {"defense": 2, "pharma": 2, "tech": 6},
            }
        }
        groups = {
            "defense": ["LMT", "RTX", "NOC", "GD"],
            "pharma":  ["JNJ", "PFE", "MRK", "LLY"],
            "tech":    ["AAPL", "MSFT", "NVDA", "GOOG", "META", "AMZN", "TSLA"],
        }
        fv = {"market_cap": {
            "LMT": 100, "RTX": 80, "NOC": 60, "GD": 40,
            "JNJ": 400, "PFE": 300, "MRK": 200, "LLY": 500,
            "AAPL": 3000, "MSFT": 2500, "NVDA": 2000, "GOOG": 1500,
            "META": 1200, "AMZN": 1100, "TSLA": 800,
        }}
        result = select_portfolio(spec, groups, fv)
        assert sorted(result) == sorted([
            "LMT", "RTX",        # defense top 2
            "LLY", "JNJ",        # pharma top 2
            "AAPL", "MSFT", "NVDA", "GOOG", "META", "AMZN",  # tech top 6
        ])

    def test_zero_quota_group_skipped(self):
        spec = {
            "selection": {
                "method": "top_n_per_group",
                "metric": "market_cap",
                "group_quotas": {"a": 0, "b": 2},
            }
        }
        groups = {"a": ["X1", "X2"], "b": ["Y1", "Y2"]}
        fv = {"market_cap": {"X1": 100, "X2": 50, "Y1": 200, "Y2": 100}}
        result = select_portfolio(spec, groups, fv)
        assert sorted(result) == ["Y1", "Y2"]


# ══════════════════════════════════════════════════════════════════════
# T-03: factor_score
# ══════════════════════════════════════════════════════════════════════

class TestFactorScore:
    def test_multi_factor_weighted(self):
        spec = {
            "selection": {
                "method": "factor_score",
                "n": 2,
                "factors": [
                    {"metric": "price_momentum_3m", "weight": 0.7},
                    {"metric": "market_cap",        "weight": 0.3},
                ],
            }
        }
        groups = {"__all__": ["A", "B", "C"]}
        # A: 高動能 + 小市值；B: 中動能 + 大市值；C: 低動能 + 中市值
        fv = {
            "price_momentum_3m": {"A": 0.50, "B": 0.20, "C": 0.05},
            "market_cap":        {"A": 100,  "B": 1000, "C": 500},
        }
        result = select_portfolio(spec, groups, fv)
        # 動能權重高 → A 第一名
        assert result[0] == "A"
        assert len(result) == 2

    def test_factor_score_picks_top_n(self):
        spec = {
            "selection": {
                "method": "factor_score",
                "n": 1,
                "factors": [{"metric": "x", "weight": 1.0}],
            }
        }
        groups = {"__all__": ["A", "B", "C"]}
        fv = {"x": {"A": 1, "B": 3, "C": 2}}
        result = select_portfolio(spec, groups, fv)
        assert result == ["B"]


# ══════════════════════════════════════════════════════════════════════
# T-04: weighted_percentile（mom_6m_t20 經典場景）
# ══════════════════════════════════════════════════════════════════════

class TestWeightedPercentile:
    def test_watchlist_filter_then_momentum(self):
        """先取市值前 5（watchlist），再從中按動能取前 2。"""
        spec = {
            "selection": {
                "method": "weighted_percentile",
                "n": 2,
                "watchlist_top_n": 5,
                "watchlist_metric": "market_cap",
            },
            "ranking": {
                "factors": [
                    {"field": "price_momentum_6m", "weight": 1.0, "direction": "desc"}
                ]
            }
        }
        groups = {"__all__": ["A", "B", "C", "D", "E", "F", "G"]}
        fv = {
            "market_cap": {
                "A": 1000, "B": 900, "C": 800, "D": 700, "E": 600, "F": 500, "G": 400,
            },
            "price_momentum_6m": {
                # F、G 動能高但市值小 → 不在 watchlist
                "F": 1.0, "G": 0.9,
                # watchlist 內：A < B < C < D < E（mcap）；動能 D 最高、E 次高
                "A": 0.10, "B": 0.20, "C": 0.30, "D": 0.80, "E": 0.50,
            }
        }
        result = select_portfolio(spec, groups, fv)
        assert sorted(result) == ["D", "E"]   # watchlist [A,B,C,D,E] → mom 前 2

    def test_default_watchlist_n_is_2n(self):
        """watchlist_top_n 未指定時預設 n × 2。"""
        spec = {
            "selection": {
                "method": "weighted_percentile",
                "n": 1,
                "watchlist_metric": "market_cap",
            },
            "ranking": {"factors": [{"field": "x", "weight": 1.0}]}
        }
        groups = {"__all__": ["A", "B", "C"]}
        fv = {
            "market_cap": {"A": 100, "B": 200, "C": 300},
            "x":          {"A": 1, "B": 2, "C": 3},
        }
        # watchlist = top 2 by mcap = [C, B]；x 排序 C > B；取 1 → C
        result = select_portfolio(spec, groups, fv)
        assert result == ["C"]


# ══════════════════════════════════════════════════════════════════════
# T-05: weighted_percentile_per_group（d2p2t6_mom6m）
# ══════════════════════════════════════════════════════════════════════

class TestWeightedPercentilePerGroup:
    def test_two_stage_filter(self):
        """軍火 4→2、醫藥 4→2、科技 12→6（依市值取候選，依動能取最終）。"""
        spec = {
            "selection": {
                "method": "weighted_percentile_per_group",
                "watchlist_metric": "market_cap",
                "group_watchlist": {"defense": 2, "pharma": 2, "tech": 3},
                "group_quotas":    {"defense": 1, "pharma": 1, "tech": 2},
            },
            "ranking": {
                "factors": [{"field": "price_momentum_6m", "weight": 1.0}]
            }
        }
        groups = {
            "defense": ["D1", "D2", "D3"],
            "pharma":  ["P1", "P2", "P3"],
            "tech":    ["T1", "T2", "T3", "T4"],
        }
        fv = {
            "market_cap": {
                "D1": 100, "D2": 80,  "D3": 60,
                "P1": 200, "P2": 150, "P3": 90,
                "T1": 1000,"T2": 900, "T3": 800, "T4": 500,
            },
            "price_momentum_6m": {
                # defense watchlist [D1, D2]；mom D2 > D1 → quota=1 → D2
                "D1": 0.1, "D2": 0.5, "D3": 0.9,
                # pharma watchlist [P1, P2]；mom P1 > P2 → P1
                "P1": 0.3, "P2": 0.2, "P3": 0.9,
                # tech watchlist [T1, T2, T3]；mom T3 > T2 > T1 → top 2 = T3, T2
                "T1": 0.1, "T2": 0.5, "T3": 0.6, "T4": 0.9,
            }
        }
        result = select_portfolio(spec, groups, fv)
        assert sorted(result) == sorted(["D2", "P1", "T2", "T3"])


# ══════════════════════════════════════════════════════════════════════
# T-06: buy_and_hold
# ══════════════════════════════════════════════════════════════════════

class TestBuyAndHold:
    def test_returns_all_symbols(self):
        spec = {"selection": {"method": "buy_and_hold"}}
        groups = {"__all__": ["SPY"]}
        result = select_portfolio(spec, groups, {})
        assert result == ["SPY"]


# ══════════════════════════════════════════════════════════════════════
# T-07: dispatcher 錯誤處理
# ══════════════════════════════════════════════════════════════════════

class TestDispatcher:
    def test_unknown_method_raises(self):
        spec = {"selection": {"method": "no_such_method"}}
        with pytest.raises(ValueError, match="no_such_method"):
            select_portfolio(spec, {"__all__": ["X"]}, {})


# ══════════════════════════════════════════════════════════════════════
# required_factors
# ══════════════════════════════════════════════════════════════════════

class TestRequiredFactors:
    def test_top_n_by_metric(self):
        spec = {"selection": {"method": "top_n_by_metric", "metric": "market_cap"}}
        assert required_factors(spec) == ["market_cap"]

    def test_factor_score(self):
        spec = {"selection": {
            "method": "factor_score",
            "factors": [
                {"metric": "price_momentum_3m"},
                {"metric": "market_cap"},
            ]
        }}
        assert sorted(required_factors(spec)) == ["market_cap", "price_momentum_3m"]

    def test_weighted_percentile(self):
        spec = {
            "selection": {"method": "weighted_percentile",
                          "watchlist_metric": "market_cap"},
            "ranking":   {"factors": [{"field": "price_momentum_6m"}]}
        }
        assert sorted(required_factors(spec)) == ["market_cap", "price_momentum_6m"]

    def test_min_price_adds_price_factor(self):
        spec = {"selection": {"method": "top_n_by_metric",
                              "metric": "market_cap", "min_price": 5.0}}
        assert "price" in required_factors(spec)

    def test_buy_and_hold_no_factors(self):
        spec = {"selection": {"method": "buy_and_hold"}}
        assert required_factors(spec) == []


# ══════════════════════════════════════════════════════════════════════
# 對齊 backtest SpecEngine：用真實策略 spec 跑一次
# ══════════════════════════════════════════════════════════════════════

class TestRealStrategySpecs:
    """用 strategies/ 內的真實 spec 驗證 selection 不爆炸。"""

    def test_top10_v3_runs(self):
        import json, pathlib
        spec = json.loads(
            (pathlib.Path(__file__).parent.parent
             / "strategies" / "top10_v3.json").read_text(encoding="utf-8")
        )
        # 模擬 25 個 universe symbol 全有市值；price > min_price (5)
        groups = {"__all__": [f"S{i}" for i in range(25)]}
        fv = {
            "market_cap": {f"S{i}": 100.0 - i for i in range(25)},
            "price":      {f"S{i}": 50.0 for i in range(25)},  # 滿足 min_price=5
        }
        result = select_portfolio(spec, groups, fv)
        assert len(result) == 10
        assert result[0] == "S0"  # market_cap 最大

    def test_d2p2t6_v3_runs(self):
        import json, pathlib
        spec = json.loads(
            (pathlib.Path(__file__).parent.parent
             / "strategies" / "d2p2t6_v3.json").read_text(encoding="utf-8")
        )
        groups = {
            "defense": [f"D{i}" for i in range(8)],
            "pharma":  [f"P{i}" for i in range(8)],
            "tech":    [f"T{i}" for i in range(15)],
        }
        all_syms = [s for g in groups.values() for s in g]
        fv = {"market_cap": {s: float(100 - i) for i, s in enumerate(all_syms)}}
        result = select_portfolio(spec, groups, fv)
        # d2p2t6: 2 + 2 + 6 = 10
        assert len(result) == 10


# ── universe_ranking：候選池排名（給 dashboard 真實股價）──────────────────────
def test_universe_ranking_watchlist_then_score():
    from engine.selection import universe_ranking
    spec = {"selection": {"method": "weighted_percentile",
                          "watchlist_metric": "market_cap", "watchlist_top_n": 3},
            "ranking": {"factors": [{"field": "mom", "weight": 1.0, "direction": "desc"}]}}
    groups = {"all": ["A", "B", "C", "D", "E"]}
    fv = {"price": {s: 100 for s in ["A","B","C","D","E"]},
          "market_cap": {"A": 3, "B": 5, "C": 9, "D": 2, "E": 1},
          "mom": {"A": .1, "B": .2, "C": .5, "D": .9, "E": .0}}
    # watchlist = top3 by mcap {C,B,A}; 再依 mom 排序 → C(.5) > B(.2) > A(.1)
    assert universe_ranking(spec, groups, fv) == ["C", "B", "A"]


def test_universe_ranking_by_metric_fallback():
    from engine.selection import universe_ranking
    spec = {"selection": {"method": "top_n_by_metric", "metric": "market_cap"}}
    groups = {"all": ["A", "B", "C"]}
    fv = {"price": {}, "market_cap": {"A": 1, "B": 3, "C": 2}}
    assert universe_ranking(spec, groups, fv) == ["B", "C", "A"]
