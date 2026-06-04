"""
scripts/migrate_to_mvp.py — 將現有資料遷移到新 MVP 架構

遷移步驟：
  1. 讀現有 data/1/portfolio_state.json → 建立 1/data.json（TOP10）
  2. 讀現有 d2p2t6/data/1/portfolio_state.json → 建立 2/data.json（D2P2T6）
  3. 建立 accounts.json（若不存在）
  4. 驗證所有產出通過 data-schema-v1.json

用法：
  python scripts/migrate_to_mvp.py [--output-dir OUTPUT_DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.accounts import Account
from engine.data_validator import validate_data_json
from engine.data_writer import write_data_json
from engine.strategy_loader import load_and_validate

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate")

ACCOUNTS_JSON = ROOT / "accounts.json"


# ── 輔助函式 ──────────────────────────────────────────────────────────────────

BENCHMARK_CACHE = ROOT / "data" / "benchmark_365_cache.json"


def _save_dated_snapshot(
    data: dict,
    output_dir: Path,
    account_id: str,
    trading_date: str,
    existing_index_dates: list[str] | None = None,
) -> None:
    """儲存每日快照 {account_id}/{trading_date}.json 並更新 index.json。

    index.json 格式：
      {"dates": ["2026-05-16", "2026-05-15", ...], "latest": "2026-05-16"}
    dates 由新到舊排列。
    """
    acct_dir = output_dir / account_id
    acct_dir.mkdir(parents=True, exist_ok=True)

    # 寫出 dated snapshot
    dated_path = acct_dir / f"{trading_date}.json"
    dated_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("  ↳ 日期快照：%s", dated_path)

    # 更新 index.json（合併傳入的歷史清單）
    index_path = acct_dir / "index.json"
    dates: list[str] = list(existing_index_dates or [])
    # 也嘗試讀取本地已有的 index（多次執行時合併）
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text(encoding="utf-8"))
            for d in existing.get("dates", []):
                if d not in dates:
                    dates.append(d)
        except Exception:
            pass
    if trading_date not in dates:
        dates.append(trading_date)
    dates.sort(reverse=True)  # 新到舊
    index = {"dates": dates, "latest": dates[0]}
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    logger.info("  ↳ index.json 更新：共 %d 筆，最新 %s", len(dates), dates[0])


def _load_benchmark_drawdown() -> dict:
    """讀取 benchmark_365_cache.json，回傳 {date: {sp500: float, nasdaq: float}}。

    cache 格式：{"labels": [...dates], "sp500": [...dd%], "nasdaq": [...dd%]}
    dd% 已是回撤百分比（負值或0），可直接使用。
    """
    raw = _load_json(BENCHMARK_CACHE)
    if not raw or "labels" not in raw:
        return {}
    labels = raw["labels"]
    sp500  = raw.get("sp500",  [None] * len(labels))
    nasdaq = raw.get("nasdaq", [None] * len(labels))
    result = {}
    for i, date in enumerate(labels):
        result[date] = {
            "sp500":  sp500[i]  if i < len(sp500)  else None,
            "nasdaq": nasdaq[i] if i < len(nasdaq) else None,
        }
    return result


def _align_benchmark(nav_history: list[dict], bench_by_date: dict) -> tuple[list, list]:
    """按 nav_history 的日期對齊 benchmark，缺失日期補 None。"""
    sp500_dd  = []
    nasdaq_dd = []
    for entry in nav_history:
        day = entry["date"]
        bm  = bench_by_date.get(day, {})
        sp500_dd.append(bm.get("sp500"))
        nasdaq_dd.append(bm.get("nasdaq"))
    return sp500_dd, nasdaq_dd


def _compute_benchmark_nav(nav_history: list[dict], initial_nav: float) -> dict:
    """
    計算 S&P500 與 NASDAQ 的 normalized NAV，與 nav_history 日期對齊。
      normalized_nav[t] = initial_nav × (price[t] / price[inception])

    回傳 {"sp500": [...], "nasdaq": [...]}，與 nav_history 等長；
    失敗時回傳 {}。
    """
    if not nav_history or len(nav_history) < 2:
        return {}

    inception_date = nav_history[0]["date"]
    end_date       = nav_history[-1]["date"]

    try:
        import yfinance as yf
        import pandas as pd
        from datetime import datetime, timedelta

        start_dt = (datetime.fromisoformat(inception_date) - timedelta(days=7)).strftime("%Y-%m-%d")
        end_dt   = (datetime.fromisoformat(end_date)       + timedelta(days=2)).strftime("%Y-%m-%d")

        raw = yf.download(
            ["^IXIC", "^GSPC"],
            start=start_dt, end=end_dt,
            auto_adjust=True, progress=False, threads=True,
        )
        if raw.empty:
            logger.warning("benchmark_nav：yfinance 回傳空資料")
            return {}

        closes = raw["Close"].copy()
        try:
            closes.index = closes.index.tz_localize(None)
        except TypeError:
            pass
        closes = closes.dropna(how="all")

        # date_str → {sym: price}
        bench_by_date: dict[str, dict] = {}
        for dt, row in closes.iterrows():
            ds = dt.strftime("%Y-%m-%d")
            bench_by_date[ds] = {}
            for sym in ["^IXIC", "^GSPC"]:
                try:
                    v = float(row[sym])
                    bench_by_date[ds][sym] = v if v == v else None   # NaN → None
                except (KeyError, TypeError):
                    bench_by_date[ds][sym] = None

        # 找 inception 日（或最近後一個交易日）的基準價
        sorted_dates = sorted(bench_by_date.keys())
        inception_prices: dict[str, float] = {}
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

        # 對齊 nav_history：每個日期取 ≤ 當日的最近交易日
        def _nearest(day: str) -> dict:
            prev = [d for d in sorted_dates if d <= day]
            return bench_by_date[prev[-1]] if prev else {}

        sp500_navs: list = []
        nasdaq_navs: list = []

        for entry in nav_history:
            bm = _nearest(entry["date"])
            sp_price = bm.get("^GSPC")
            nd_price = bm.get("^IXIC")
            sp500_navs.append(
                round(initial_nav * sp_price / inception_prices["^GSPC"], 2)
                if sp_price is not None else None
            )
            nasdaq_navs.append(
                round(initial_nav * nd_price / inception_prices["^IXIC"], 2)
                if nd_price is not None else None
            )

        logger.info("benchmark_nav：計算完成（%d 筆）", len(sp500_navs))
        return {"sp500": sp500_navs, "nasdaq": nasdaq_navs}

    except Exception as exc:
        logger.warning("無法取得 benchmark NAV 資料：%s", exc)
        return {}


def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        logger.warning("檔案不存在，跳過：%s", path)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_history_list(raw: dict | list | None) -> list[dict]:
    """從 portfolio_state_history.json 取出歷史條目清單。

    支援兩種格式：
      - 舊格式（list）：直接是 list of entries
      - 新格式（dict）：{"initial_nav": ..., "start_date": ..., "history": [...]}
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("history", [])
    return []


def _extract_nav_history(history: list[dict]) -> list[dict]:
    """從 portfolio_state_history.json 轉換 nav_history 格式。"""
    result = []
    for entry in history:
        result.append({"date": entry["date"], "nav": entry["nav"]})
    # 去重、排序
    seen = set()
    deduped = []
    for p in sorted(result, key=lambda x: x["date"]):
        if p["date"] not in seen:
            seen.add(p["date"])
            deduped.append(p)
    return deduped


def _extract_trade_log(history: list[dict]) -> list[dict]:
    """從 portfolio_state_history.json 轉換 trade_log 格式。"""
    log = []
    for entry in history:
        orders = []
        for o in entry.get("orders_executed", []):
            orders.append({
                "symbol": o.get("symbol", ""),
                "side":   o.get("side", "buy"),
                "qty":    float(o.get("qty", 0)),
                "price":  float(o.get("price", o.get("filled_avg_price", 0))),
            })
        log.append({
            "date":         entry["date"],
            "nav":          entry["nav"],
            "trades_count": len(orders),
            "portfolio":    entry.get("top10", []),
            "orders":       orders,
        })
    # 降序
    log.sort(key=lambda x: x["date"], reverse=True)
    return log


# ── TOP10 遷移 ────────────────────────────────────────────────────────────────

def migrate_top10(output_dir: Path, dry_run: bool = False) -> bool:
    logger.info("── TOP10 遷移開始 ──")
    strategy = load_and_validate("top10")

    state_path   = ROOT / "data" / "1" / "portfolio_state.json"
    history_path = ROOT / "data" / "1" / "portfolio_state_history.json"

    state = _load_json(state_path)
    if not state:
        logger.error("找不到 TOP10 狀態檔，跳過")
        return False

    history = _extract_history_list(_load_json(history_path))
    nav_history = _extract_nav_history(history)
    trade_log   = _extract_trade_log(history)

    # 補足今日（若歷史沒有今日）
    today = state["date"]
    if not any(p["date"] == today for p in nav_history):
        nav_history.append({"date": today, "nav": state["nav"]})
        nav_history.sort(key=lambda x: x["date"])

    # 取 TOP10 選股
    top10 = state.get("top10", [])
    if not top10:
        top10 = [p["symbol"] for p in state.get("positions", [])][:10]

    # 取排名（從 ranked_stocks）
    ranked_stocks = state.get("ranked_stocks", [])
    if not ranked_stocks:
        ranked_stocks = [
            {"rank": i+1, "symbol": s, "close_price": 100.0,
             "market_cap": 1e11, "chg_pct": 0.0}
            for i, s in enumerate(top10)
        ]

    account = Account(id="1", strategy="top10", label="帳戶 #1 (TOP10)")
    output_path = output_dir / "1" / "data.json"

    # 建立偽 existing_data（含 nav_history 和 trade_log）
    existing_data = {
        "summary": {
            "initial_nav":   nav_history[0]["nav"] if nav_history else state["nav"],
            "inception_date": nav_history[0]["date"] if nav_history else today,
        },
        "meta": {"strategy_start_date": nav_history[0]["date"] if nav_history else today},
        "nav_history": nav_history[:-1] if len(nav_history) > 1 else [],
        "trade_log":   trade_log,
        "events":      [],
    }

    if not dry_run:
        data = write_data_json(
            output_path           = output_path,
            strategy_cfg          = strategy,
            account               = account,
            same_strategy_accounts= [account],
            nav                   = state["nav"],
            cash                  = state["cash"],
            positions             = state.get("positions", []),
            top_n_symbols         = top10,
            executed_orders       = [],
            rankings_raw          = ranked_stocks,
            trading_date          = today,
            dry_run               = False,
            existing_data         = existing_data,
        )
        # 注入 benchmark 回撤（對齊日期）
        bench = _load_benchmark_drawdown()
        if bench:
            all_nav = data.get("nav_history", [])
            sp500_dd, nasdaq_dd = _align_benchmark(all_nav, bench)
            data["drawdown"]["sp500"]  = [round(v, 4) if v is not None else None for v in sp500_dd]
            data["drawdown"]["nasdaq"] = [round(v, 4) if v is not None else None for v in nasdaq_dd]
        # 注入 benchmark NAV（normalized，供 NAV 走勢圖疊加）
        init_nav = nav_history[0]["nav"] if nav_history else state["nav"]
        bench_nav = _compute_benchmark_nav(data.get("nav_history", []), init_nav)
        if bench_nav:
            data["benchmark_nav"] = bench_nav
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("  ↳ benchmark 注入完成（回撤 + NAV）")
        validate_data_json(data)
        _save_dated_snapshot(data, output_dir, "1", today)
        logger.info("✅ TOP10 遷移完成：%s", output_path)
    else:
        logger.info("DRY RUN：跳過寫出 %s", output_path)
    return True


def migrate_d2p2t6(output_dir: Path, dry_run: bool = False) -> bool:
    logger.info("── D2P2T6 遷移開始 ──")
    strategy = load_and_validate("d2p2t6")

    state_path    = ROOT / "d2p2t6" / "data" / "1" / "portfolio_state.json"
    history_path  = ROOT / "d2p2t6" / "data" / "1" / "portfolio_state_history.json"
    rankings_path = ROOT / "d2p2t6" / "data" / "1" / "latest_rankings.json"

    state = _load_json(state_path)
    if not state:
        logger.error("找不到 D2P2T6 狀態檔，跳過")
        return False

    history      = _extract_history_list(_load_json(history_path))
    nav_history  = _extract_nav_history(history)
    trade_log    = _extract_trade_log(history)
    rankings_raw = _load_json(rankings_path) or {}

    today    = state["date"]
    top10    = state.get("top10", [])
    if not top10:
        top10 = [p["symbol"] for p in state.get("positions", [])][:10]

    # 轉換 rankings_raw 格式（legacy → new）
    group_rankings = {}
    for group_id in ["defense", "pharma", "tech"]:
        raw = rankings_raw.get(group_id, [])
        group_rankings[group_id] = [
            {"sym": r.get("sym", r.get("symbol", "")),
             "rank": r.get("rank", 0),
             "price": r.get("price", 0),
             "chg_pct": r.get("chg_pct", r.get("change_pct", 0)),
             "mcap_b": r.get("mcap_b", r.get("market_cap_b", 0))}
            for r in raw
        ]

    if not any(group_rankings.values()):
        group_rankings = {
            "defense": [{"sym": s, "rank": i+1, "price": 100.0, "chg_pct": 0.0, "mcap_b": 100.0}
                        for i, s in enumerate(["RTX", "LMT"])],
            "pharma":  [{"sym": s, "rank": i+1, "price": 100.0, "chg_pct": 0.0, "mcap_b": 100.0}
                        for i, s in enumerate(["LLY", "JNJ"])],
            "tech":    [{"sym": s, "rank": i+1, "price": 100.0, "chg_pct": 0.0, "mcap_b": 100.0}
                        for i, s in enumerate(["NVDA","MSFT","AAPL","AMZN","GOOGL","AVGO"])],
        }

    account = Account(id="2", strategy="d2p2t6", label="帳戶 #2 (D2P2T6)")
    output_path = output_dir / "2" / "data.json"

    if not any(p["date"] == today for p in nav_history):
        nav_history.append({"date": today, "nav": state["nav"]})
        nav_history.sort(key=lambda x: x["date"])

    existing_data = {
        "summary": {
            "initial_nav":    nav_history[0]["nav"] if nav_history else state["nav"],
            "inception_date": nav_history[0]["date"] if nav_history else today,
        },
        "meta": {"strategy_start_date": nav_history[0]["date"] if nav_history else today},
        "nav_history": nav_history[:-1] if len(nav_history) > 1 else [],
        "trade_log":   trade_log,
        "events":      [],
    }

    if not dry_run:
        data = write_data_json(
            output_path           = output_path,
            strategy_cfg          = strategy,
            account               = account,
            same_strategy_accounts= [account],
            nav                   = state["nav"],
            cash                  = state["cash"],
            positions             = state.get("positions", []),
            top_n_symbols         = top10,
            executed_orders       = [],
            rankings_raw          = group_rankings,
            trading_date          = today,
            dry_run               = False,
            existing_data         = existing_data,
        )
        # 注入 benchmark 回撤（對齊日期）
        bench = _load_benchmark_drawdown()
        if bench:
            all_nav = data.get("nav_history", [])
            sp500_dd, nasdaq_dd = _align_benchmark(all_nav, bench)
            data["drawdown"]["sp500"]  = [round(v, 4) if v is not None else None for v in sp500_dd]
            data["drawdown"]["nasdaq"] = [round(v, 4) if v is not None else None for v in nasdaq_dd]
        # 注入 benchmark NAV（normalized，供 NAV 走勢圖疊加）
        init_nav = nav_history[0]["nav"] if nav_history else state["nav"]
        bench_nav = _compute_benchmark_nav(data.get("nav_history", []), init_nav)
        if bench_nav:
            data["benchmark_nav"] = bench_nav
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("  ↳ benchmark 注入完成（回撤 + NAV）")
        validate_data_json(data)
        _save_dated_snapshot(data, output_dir, "2", today)
        logger.info("✅ D2P2T6 遷移完成：%s", output_path)
    else:
        logger.info("DRY RUN：跳過寫出 %s", output_path)
    return True


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="遷移資料到 MVP 架構")
    parser.add_argument("--output-dir", default=str(ROOT / "mvp_data"),
                        help="輸出目錄（預設：mvp_data/）")
    parser.add_argument("--dry-run", action="store_true", help="只驗證，不寫出檔案")
    parser.add_argument(
        "--strategy",
        choices=["top10", "d2p2t6", "all"],
        default="all",
        help="只遷移指定策略（預設：all；單跑時 d2p2t6 走分組 migrator、其餘走泛用產生器）",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── "all"：資料驅動的單一產生器（迴圈 accounts.json，不再每策略一函式）──────
    if args.strategy == "all":
        from engine.report_generator import generate_all
        # 分組排名（universe_groups，如 d2p2t6）暫由既有 migrator 處理；其餘全走泛用
        results = generate_all(output_dir, dry_run=args.dry_run,
                               legacy={"d2p2t6": migrate_d2p2t6})
        for aid, st in results.items():
            logger.info("  帳戶 #%s：%s", aid, st)
        # 註：不再呼叫 migrate_top9psq_live / migrate_d2p2t6_live —— 它們輸出到 id 3/2，
        #     會覆蓋 generate_all 對帳戶 #3/#2 的正確輸出（那些舊策略已由 strategy_history 縫合）。
        if any(v == "fail" for v in results.values()):
            logger.error("部分帳戶報告產生失敗")
            sys.exit(1)
        logger.info("✅ 報告產生完成（資料驅動）！輸出目錄：%s", output_dir)
        return

    # ── 單一策略（手動單跑用）──────────────────────────────────────────────
    if args.strategy == "d2p2t6":
        if not migrate_d2p2t6(output_dir, dry_run=args.dry_run):  # 分組排名 adapter
            sys.exit(1)
    else:  # top10 → 泛用產生器
        from engine.report_generator import generate_for_account
        from engine.accounts import get_account
        generate_for_account(get_account("1"), output_dir, dry_run=args.dry_run)
    logger.info("✅ 完成：%s", args.strategy)


if __name__ == "__main__":
    main()
