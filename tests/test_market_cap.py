"""tests/test_market_cap.py — 市值計算與排名測試"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from market_cap import (
    calculate_market_caps,
    rank_by_market_cap,
    get_top_n,
    build_ranked_stocks,
)


class TestCalculateMarketCaps:
    def test_basic_calculation(self):
        prices = {"AAPL": 190.0}
        shares = {"AAPL": 15_000_000_000}
        result = calculate_market_caps(prices, shares)
        assert result["AAPL"] == pytest.approx(2_850_000_000_000.0)

    def test_multiple_stocks(self):
        prices = {"AAPL": 190.0, "MSFT": 400.0}
        shares = {"AAPL": 15_000_000_000, "MSFT": 7_000_000_000}
        result = calculate_market_caps(prices, shares)
        assert len(result) == 2
        assert result["MSFT"] == pytest.approx(2_800_000_000_000.0)

    def test_missing_price_excluded(self):
        """價格缺失的股票不應出現在結果中"""
        prices = {"AAPL": 190.0}
        shares = {"AAPL": 15_000_000_000, "MSFT": 7_000_000_000}
        result = calculate_market_caps(prices, shares)
        assert "MSFT" not in result
        assert "AAPL" in result

    def test_missing_shares_excluded(self):
        """流通股數缺失的股票不應出現在結果中"""
        prices = {"AAPL": 190.0, "MSFT": 400.0}
        shares = {"AAPL": 15_000_000_000}
        result = calculate_market_caps(prices, shares)
        assert "MSFT" not in result

    def test_zero_shares_excluded(self):
        prices = {"AAPL": 190.0}
        shares = {"AAPL": 0}
        result = calculate_market_caps(prices, shares)
        assert "AAPL" not in result


class TestRankByMarketCap:
    def test_ranking_order(self):
        """市值由大至小排序"""
        mcaps = {"AAPL": 3e12, "MSFT": 2e12, "NVDA": 1e12}
        ranked = rank_by_market_cap(mcaps)
        symbols = [s.symbol for s in ranked]
        assert symbols == ["AAPL", "MSFT", "NVDA"]

    def test_ranking_with_correct_rank_numbers(self):
        mcaps = {"AAPL": 3e12, "MSFT": 2e12}
        ranked = rank_by_market_cap(mcaps)
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2

    def test_tie_breaking_alphabetical(self):
        """相同市值時以 symbol 字母順序排序"""
        mcaps = {"MSFT": 3e12, "AAPL": 3e12}
        ranked = rank_by_market_cap(mcaps)
        # AAPL 字母在前，排名應較高
        assert ranked[0].symbol == "AAPL"
        assert ranked[1].symbol == "MSFT"

    def test_single_stock(self):
        mcaps = {"NVDA": 3e12}
        ranked = rank_by_market_cap(mcaps)
        assert len(ranked) == 1
        assert ranked[0].rank == 1

    def test_market_cap_stored(self):
        mcaps = {"AAPL": 3e12}
        ranked = rank_by_market_cap(mcaps)
        assert ranked[0].market_cap == pytest.approx(3e12)


class TestGetTopN:
    def test_returns_top_n(self):
        mcaps = {f"S{i}": float(10 - i) for i in range(10)}  # S0 最大
        ranked = rank_by_market_cap(mcaps)
        top5 = get_top_n(ranked, 5)
        assert len(top5) == 5
        assert top5[0] == "S0"

    def test_default_top_10(self):
        mcaps = {f"S{i}": float(20 - i) for i in range(20)}
        ranked = rank_by_market_cap(mcaps)
        top = get_top_n(ranked)
        assert len(top) == 10

    def test_n_larger_than_list(self):
        """請求的 N 超過股票數量，回傳全部"""
        mcaps = {"AAPL": 3e12, "MSFT": 2e12}
        ranked = rank_by_market_cap(mcaps)
        top = get_top_n(ranked, 10)
        assert len(top) == 2


class TestBuildRankedStocks:
    def test_integration(self):
        symbols = ["AAPL", "MSFT", "NVDA"]
        prices  = {"AAPL": 190.0, "MSFT": 400.0, "NVDA": 800.0}
        shares  = {"AAPL": 15_000_000_000, "MSFT": 7_000_000_000, "NVDA": 24_000_000_000}
        ranked, top3 = build_ranked_stocks(symbols, prices, shares, n=3)
        # NVDA: 800 × 24B = 19.2T（最大）
        assert top3[0] == "NVDA"
        assert len(top3) == 3

    def test_close_price_filled(self):
        symbols = ["AAPL"]
        prices  = {"AAPL": 190.0}
        shares  = {"AAPL": 15_000_000_000}
        ranked, _ = build_ranked_stocks(symbols, prices, shares)
        assert ranked[0].close_price == pytest.approx(190.0)
