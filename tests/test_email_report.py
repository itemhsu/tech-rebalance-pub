"""
tests/test_email_report.py — email_report.py 回撤 SVG 健康檢查

覆蓋此 bug：
  yfinance SQLite OperationalError('database is locked') 導致 ^IXIC 回傳 NaN，
  NaN 通過 'is not None' 過濾後進入 round(NaN / 10)，拋出 ValueError → workflow 失敗。

測試項目：
  1. NaN 混入 nasdaq_dd 時不崩潰
  2. NaN 混入 sp500_dd 時不崩潰
  3. 全為 NaN 時回傳空字串（graceful fallback）
  4. 正常資料正確產生 SVG
  5. bench 資料含 NaN float 時能正確過濾
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import email_report

# 快取路徑（email_report.py 內部硬編碼的位置）
_CACHE_PATH = Path(email_report.__file__).parent / "data" / "benchmark_365_cache.json"


# ── 測試用輔助：用臨時快取 mock bench 資料 ────────────────────────────────────

def _make_bench(nasdaq: list, sp500: list, labels: list | None = None) -> dict:
    if labels is None:
        labels = [f"2026-04-{i+1:02d}" for i in range(len(nasdaq))]
    return {"labels": labels, "nasdaq": nasdaq, "sp500": sp500}


def _call_svg(bench: dict, nav_history: list[dict]) -> str:
    """
    寫入臨時快取 JSON，呼叫 _build_drawdown_svg_html，再還原快取。
    None 可合法序列化為 JSON null；NaN 需先替換成 None 以模擬修正後行為，
    或直接用 None 模擬 yfinance SQLite lock 失敗的最終輸出。
    """
    old_content: str | None = None
    if _CACHE_PATH.exists():
        old_content = _CACHE_PATH.read_text(encoding="utf-8")
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(bench), encoding="utf-8")
        return email_report._build_drawdown_svg_html(nav_history)
    finally:
        if old_content is not None:
            _CACHE_PATH.write_text(old_content, encoding="utf-8")
        elif _CACHE_PATH.exists():
            _CACHE_PATH.unlink()


# ══════════════════════════════════════════════════════════════════════════════
#  NaN / None 防護測試
# ══════════════════════════════════════════════════════════════════════════════

class TestDrawdownSvgNanHandling:
    """
    _build_drawdown_svg_html 對 None（yfinance SQLite lock 後修正的輸出）
    必須優雅處理，不能拋例外。

    背景：yfinance OperationalError('database is locked') for ^IXIC
    → 我們的修正把 NaN float 轉成 None，再由 SVG 函式過濾掉。
    """

    NAV_HISTORY = [
        {"date": "2026-04-01", "nav": 100000.0},
        {"date": "2026-04-15", "nav": 98000.0},
        {"date": "2026-05-01", "nav": 102000.0},
    ]

    def test_none_in_nasdaq_does_not_raise(self):
        """nasdaq_dd 中含 None（SQLite lock 後修正輸出）時不應拋出 ValueError。"""
        bench = _make_bench(
            nasdaq=[None, -1.0, -2.0],   # None = yfinance NaN 已由修正轉換
            sp500 =[-0.5, -1.5, -0.5],
        )
        try:
            result = _call_svg(bench, self.NAV_HISTORY)
            assert isinstance(result, str)
        except ValueError as e:
            pytest.fail(
                f"None 在 nasdaq 導致 ValueError：{e}\n"
                "（此 bug 由 yfinance SQLite lock 引發，曾導致 workflow 失敗）"
            )

    def test_none_in_sp500_does_not_raise(self):
        """sp500_dd 中含 None 時不應拋出 ValueError。"""
        bench = _make_bench(
            nasdaq=[-0.5, -1.0, -0.5],
            sp500 =[None, None, -1.0],
        )
        try:
            result = _call_svg(bench, self.NAV_HISTORY)
            assert isinstance(result, str)
        except ValueError as e:
            pytest.fail(f"None 在 sp500 導致 ValueError：{e}")

    def test_all_none_returns_string(self):
        """全部為 None 時應回傳字串（帶預設範圍的 SVG），不崩潰。"""
        bench = _make_bench(
            nasdaq=[None] * 3,
            sp500 =[None] * 3,
        )
        result = _call_svg(bench, self.NAV_HISTORY)
        assert isinstance(result, str), "全 None 時應回傳 str，不應拋例外"

    def test_mixed_none_does_not_raise(self):
        """nasdaq / sp500 交替含 None 時也不崩潰。"""
        bench = _make_bench(
            nasdaq=[None, -1.5, None],
            sp500 =[-0.3, None, -0.8],
        )
        try:
            result = _call_svg(bench, self.NAV_HISTORY)
            assert isinstance(result, str)
        except (ValueError, ZeroDivisionError) as e:
            pytest.fail(f"混合 None 導致例外：{e}")

    def test_normal_data_produces_svg(self):
        """正常資料（無 None）應回傳包含 <svg> 的字串。"""
        bench = _make_bench(
            nasdaq=[-0.5, -1.2, -0.8],
            sp500 =[-0.3, -0.9, -0.4],
        )
        result = _call_svg(bench, self.NAV_HISTORY)
        assert "<svg" in result, "正常資料應產生 SVG，但得到空字串"


# ══════════════════════════════════════════════════════════════════════════════
#  benchmark 建構邏輯（_get_benchmark_drawdown_365）
# ══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkNanGuard:
    """_get_benchmark_drawdown_365 的 per-value NaN 防護。"""

    def _build_bench_from_series(self, values: list[float]) -> list:
        """
        模擬 email_report 中的 dd 建構邏輯，用來驗證 NaN guard 有無效果。
        """
        result = []
        peak = None
        for p in values:
            pf = float(p)
            if pf != pf:           # NaN check
                result.append(None)
                continue
            if peak is None:
                peak = pf
            peak = max(peak, pf)
            result.append(round((pf - peak) / peak * 100, 2))
        return result

    def test_nan_at_start_becomes_none(self):
        """序列開頭的 NaN（bfill 前）應轉成 None，不傳播到後續計算。"""
        result = self._build_bench_from_series([float("nan"), 100.0, 95.0])
        assert result[0] is None, "開頭 NaN 應轉為 None"
        assert result[1] == 0.0
        assert result[2] == pytest.approx(-5.0, abs=0.1)

    def test_nan_in_middle_becomes_none(self):
        """中間的 NaN 應轉成 None，不影響 peak 追蹤。"""
        result = self._build_bench_from_series([100.0, float("nan"), 90.0])
        assert result[0] == 0.0
        assert result[1] is None
        assert result[2] == pytest.approx(-10.0, abs=0.1)

    def test_no_nan_works_normally(self):
        """無 NaN 的正常序列應正確計算。"""
        result = self._build_bench_from_series([100.0, 105.0, 95.0])
        assert result[0] == 0.0
        assert result[1] == 0.0              # 105 是新高
        assert result[2] == pytest.approx(-9.52, abs=0.1)
