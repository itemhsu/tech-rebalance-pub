"""回撤對比圖的基準線：改用每日新抓的 benchmark_nav 算回撤，不再依賴過期的
data/benchmark_365_cache.json（最後更新 2026-05-28、nasdaq 全空 → 圖上 S&P500 只到 5/27、NASDAQ 全缺）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.data_writer import _drawdown_series   # noqa: E402
from engine import report_generator as rg          # noqa: E402
from engine.accounts import Account                # noqa: E402

_DATES = ["2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
_NAVS  = [20000.0, 19800.0, 20200.0, 20100.0]


def test_drawdown_series_tolerates_none():
    assert _drawdown_series([100.0, None, 90.0]) == [0.0, None, pytest.approx(-10.0)]


def _seed(tmp_path: Path):
    d = tmp_path / "data" / "3"; d.mkdir(parents=True)
    hist = [{"date": dt, "nav": nv, "cash": 10.0, "top10": ["NVDA"], "orders_executed": [], "trades_count": 0}
            for dt, nv in zip(_DATES, _NAVS)]
    (d / "portfolio_state_history.json").write_text(json.dumps({"history": hist}))
    (d / "portfolio_state.json").write_text(json.dumps({
        "date": _DATES[-1], "nav": _NAVS[-1], "cash": 10.0, "positions": [],
        "top10": ["NVDA"], "orders_executed": [], "ranked_stocks": []}))
    return Account(id="3", strategy="tech_top10", label="t", data_dir="data/3")


def _fake_bench_nav(nav_history, initial_nav):
    # 與 nav_history 等長、已依 initial_nav 正規化的基準 NAV
    return {"sp500":  [20000.0, 19600.0, 19900.0, 20300.0],
            "nasdaq": [20000.0, 19000.0, 19500.0, 19800.0]}


def test_generator_benchmark_drawdown_from_fresh_benchmark_nav(tmp_path, monkeypatch):
    acct = _seed(tmp_path)
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "_compute_benchmark_nav", _fake_bench_nav)
    monkeypatch.setattr(rg, "_load_benchmark_drawdown", lambda: {})        # 無快取
    assert rg.generate_for_account(acct, tmp_path / "out") == "ok"
    d = json.loads((tmp_path / "out" / "3" / "data.json").read_text())
    dd = d["drawdown"]
    assert dd["dates"] == _DATES
    assert None not in dd["sp500"] and None not in dd["nasdaq"], "基準回撤不得缺漏"
    assert dd["sp500"]  == [pytest.approx(v) for v in _drawdown_series(_fake_bench_nav(None, None)["sp500"])]
    assert dd["nasdaq"][1] == pytest.approx(-5.0)
    assert d["benchmark_nav"]["sp500"][-1] == 20300.0


def test_stale_cache_does_not_override_fresh_benchmark(tmp_path, monkeypatch):
    acct = _seed(tmp_path)
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "_compute_benchmark_nav", _fake_bench_nav)
    stale = {_DATES[0]: {"sp500": -9.9, "nasdaq": None}}                   # 只有第一天、nasdaq 空
    monkeypatch.setattr(rg, "_load_benchmark_drawdown", lambda: stale)
    rg.generate_for_account(acct, tmp_path / "out")
    dd = json.loads((tmp_path / "out" / "3" / "data.json").read_text())["drawdown"]
    assert None not in dd["nasdaq"]
    assert dd["sp500"][0] == 0.0, "不得被過期快取覆蓋"


def test_generator_falls_back_to_cache_when_benchmark_nav_unavailable(tmp_path, monkeypatch):
    acct = _seed(tmp_path)
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "_compute_benchmark_nav", lambda nh, i: {})  # yfinance 失敗
    cache = {dt: {"sp500": -1.0 * i, "nasdaq": -2.0 * i} for i, dt in enumerate(_DATES)}
    monkeypatch.setattr(rg, "_load_benchmark_drawdown", lambda: cache)
    rg.generate_for_account(acct, tmp_path / "out")
    dd = json.loads((tmp_path / "out" / "3" / "data.json").read_text())["drawdown"]
    assert dd["sp500"] == [0.0, -1.0, -2.0, -3.0]
