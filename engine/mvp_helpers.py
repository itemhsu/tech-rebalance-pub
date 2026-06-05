"""engine/mvp_helpers.py — dashboard 資料產生的通用 helper（進 wheel）。

歷史：這些 helper 原本住在 scripts/migrate_to_mvp.py，但 engine.report_generator
從那裡 import，導致「薄殼」（pip 安裝、無 scripts/ 目錄）根本 import 不到 →
無法在雲端產生 dashboard 資料。搬進 engine/ 後，通用產生器完全自包含。

全部與策略無關（純資料轉換）：state/history 解析、benchmark 對齊、每日快照。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from engine.paths import workdir

logger = logging.getLogger("mvp_helpers")

BENCHMARK_CACHE = workdir() / "data" / "benchmark_365_cache.json"


def _load_json(path: Path):
    if not Path(path).exists():
        logger.warning("檔案不存在，跳過：%s", path)
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _extract_history_list(raw) -> list:
    """從 portfolio_state_history.json 取出歷史條目清單（支援 list / dict 兩種格式）。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("history", [])
    return []


def _extract_nav_history(history: list) -> list:
    """轉換 nav_history 格式（去重、由舊到新排序）。"""
    result = [{"date": e["date"], "nav": e["nav"]} for e in history]
    seen, deduped = set(), []
    for p in sorted(result, key=lambda x: x["date"]):
        if p["date"] not in seen:
            seen.add(p["date"])
            deduped.append(p)
    return deduped


def _extract_trade_log(history: list) -> list:
    """轉換 trade_log 格式（降序）。"""
    log = []
    for entry in history:
        orders = [{
            "symbol": o.get("symbol", ""),
            "side":   o.get("side", "buy"),
            "qty":    float(o.get("qty", 0)),
            "price":  float(o.get("price", o.get("filled_avg_price", 0))),
        } for o in entry.get("orders_executed", [])]
        log.append({
            "date":         entry["date"],
            "nav":          entry["nav"],
            "trades_count": len(orders),
            "portfolio":    entry.get("top10", []),
            "orders":       orders,
        })
    log.sort(key=lambda x: x["date"], reverse=True)
    return log


def _save_dated_snapshot(data: dict, output_dir: Path, account_id: str,
                         trading_date: str, existing_index_dates=None) -> None:
    """儲存每日快照 {account_id}/{trading_date}.json 並更新 index.json（新到舊）。"""
    acct_dir = Path(output_dir) / account_id
    acct_dir.mkdir(parents=True, exist_ok=True)
    (acct_dir / f"{trading_date}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("  ↳ 日期快照：%s/%s.json", account_id, trading_date)

    index_path = acct_dir / "index.json"
    dates = list(existing_index_dates or [])
    if index_path.exists():
        try:
            for d in json.loads(index_path.read_text(encoding="utf-8")).get("dates", []):
                if d not in dates:
                    dates.append(d)
        except Exception:   # noqa: BLE001
            pass
    if trading_date not in dates:
        dates.append(trading_date)
    dates.sort(reverse=True)
    index_path.write_text(json.dumps({"dates": dates, "latest": dates[0]},
                                     ensure_ascii=False), encoding="utf-8")
    logger.info("  ↳ index.json 更新：共 %d 筆，最新 %s", len(dates), dates[0])


def _load_benchmark_drawdown() -> dict:
    """讀 benchmark_365_cache.json → {date: {sp500, nasdaq}}。"""
    raw = _load_json(BENCHMARK_CACHE)
    if not raw or "labels" not in raw:
        return {}
    labels = raw["labels"]
    sp500  = raw.get("sp500",  [None] * len(labels))
    nasdaq = raw.get("nasdaq", [None] * len(labels))
    return {d: {"sp500":  sp500[i]  if i < len(sp500)  else None,
                "nasdaq": nasdaq[i] if i < len(nasdaq) else None}
            for i, d in enumerate(labels)}


def _align_benchmark(nav_history: list, bench_by_date: dict):
    """按 nav_history 日期對齊 benchmark，缺失補 None。"""
    sp500_dd, nasdaq_dd = [], []
    for entry in nav_history:
        bm = bench_by_date.get(entry["date"], {})
        sp500_dd.append(bm.get("sp500"))
        nasdaq_dd.append(bm.get("nasdaq"))
    return sp500_dd, nasdaq_dd


def _compute_benchmark_nav(nav_history: list, initial_nav: float) -> dict:
    """計算 S&P500 / NASDAQ 的 normalized NAV（與 nav_history 日期對齊）。失敗回 {}。"""
    if not nav_history or len(nav_history) < 2:
        return {}
    inception_date = nav_history[0]["date"]
    end_date       = nav_history[-1]["date"]
    try:
        import yfinance as yf
        from datetime import datetime, timedelta

        start_dt = (datetime.fromisoformat(inception_date) - timedelta(days=7)).strftime("%Y-%m-%d")
        end_dt   = (datetime.fromisoformat(end_date)       + timedelta(days=2)).strftime("%Y-%m-%d")
        raw = yf.download(["^IXIC", "^GSPC"], start=start_dt, end=end_dt,
                          auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            logger.warning("benchmark_nav：yfinance 回傳空資料")
            return {}
        closes = raw["Close"].copy()
        try:
            closes.index = closes.index.tz_localize(None)
        except TypeError:
            pass
        closes = closes.dropna(how="all")

        bench_by_date: dict = {}
        for dt, row in closes.iterrows():
            ds = dt.strftime("%Y-%m-%d")
            bench_by_date[ds] = {}
            for sym in ["^IXIC", "^GSPC"]:
                try:
                    v = float(row[sym])
                    bench_by_date[ds][sym] = v if v == v else None
                except (KeyError, TypeError):
                    bench_by_date[ds][sym] = None

        sorted_dates = sorted(bench_by_date.keys())
        inception_prices: dict = {}
        for sym in ["^IXIC", "^GSPC"]:
            for d in sorted_dates:
                if d >= inception_date:
                    v = bench_by_date[d].get(sym)
                    if v is not None:
                        inception_prices[sym] = v
                        break
        if len(inception_prices) < 2:
            logger.warning("benchmark_nav：找不到 inception 基準價（%s）", inception_date)
            return {}

        def _nearest(day: str) -> dict:
            prev = [d for d in sorted_dates if d <= day]
            return bench_by_date[prev[-1]] if prev else {}

        sp500_navs, nasdaq_navs = [], []
        for entry in nav_history:
            bm = _nearest(entry["date"])
            sp_price = bm.get("^GSPC")
            nd_price = bm.get("^IXIC")
            sp500_navs.append(round(initial_nav * sp_price / inception_prices["^GSPC"], 2)
                              if sp_price is not None else None)
            nasdaq_navs.append(round(initial_nav * nd_price / inception_prices["^IXIC"], 2)
                               if nd_price is not None else None)
        logger.info("benchmark_nav：計算完成（%d 筆）", len(sp500_navs))
        return {"sp500": sp500_navs, "nasdaq": nasdaq_navs}
    except Exception as exc:   # noqa: BLE001
        logger.warning("無法取得 benchmark NAV 資料：%s", exc)
        return {}
