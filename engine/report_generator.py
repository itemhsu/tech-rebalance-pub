"""engine/report_generator.py — 資料驅動的單一報告產生器。

取代 scripts/migrate_to_mvp.py 內「每個策略硬寫一個 migrate_* 函式」的設計。
對任何帳戶：讀 accounts.json 的 data_dir → portfolio_state.json，依策略 JSON
產出 mvp_data/{id}/data.json。新增策略（常見形狀）= 只改 JSON、0 行 Python。

變異點（只有兩個）以宣告式 resolver 處理：
  - resolve_holdings：持股清單（top10 / target_weights / positions 的 fallback）
  - resolve_rankings：排名形狀（ranked_stocks / scorecard / 由持股推導；
                       universe_groups 這類分組形狀仍由既有 migrator 處理）
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

# 通用 helper 已搬進 engine（進 wheel），薄殼也能 import
from engine.mvp_helpers import (
    _load_json, _extract_history_list, _extract_nav_history, _extract_trade_log,
    _load_benchmark_drawdown, _align_benchmark, _compute_benchmark_nav,
    _save_dated_snapshot,
)
from engine.accounts import Account, load_accounts
from engine.data_writer import write_data_json
from engine.data_validator import validate_data_json
from engine.strategy_loader import load_and_validate

import json
import logging
import os

from engine.paths import workdir

logger = logging.getLogger("report_generator")
# 報告讀的是使用者資料目錄（account.data_dir）→ workdir()
ROOT = workdir()

# 分組排名（universe_groups）等特殊形狀暫由既有 migrator 負責，generate_all 會略過。
GROUPED = {"universe_groups"}


# ── 變異點 ① 持股 ─────────────────────────────────────────────────────────
def resolve_holdings(state: dict, n: int = 10) -> List[str]:
    if state.get("top10"):
        return list(state["top10"])
    tw = state.get("target_weights") or {}
    if tw:
        return list(tw.keys())
    return [p["symbol"] for p in state.get("positions", [])][:n]


# ── 變異點 ② 排名 ─────────────────────────────────────────────────────────
def _rankings_cfg(strat: dict) -> dict:
    return (strat.get("dashboard") or {}).get("rankings") or {}


def is_grouped(strat: dict) -> bool:
    """分組排名（universe_groups）—— 由 type 或 source 任一宣告。"""
    r = _rankings_cfg(strat)
    return (r.get("type") or r.get("source")) in GROUPED


def _group_ids(strat: dict) -> list:
    """從策略 JSON 取分組排名的 group 名稱（純宣告式，不寫死 defense/pharma/tech）。
    優先 dashboard.rankings.group_labels 的鍵；後援 universe_groups.groups 的鍵。"""
    ids = list((_rankings_cfg(strat).get("group_labels") or {}).keys())
    if ids:
        return ids
    ug = (strat.get("universe_groups") or {}).get("groups") or {}
    return list(ug.keys()) if isinstance(ug, dict) else []


def _grouped_rankings(strat: dict, data_dir: str):
    """分組排名（universe_groups，如 d2p2t6）→ 讀帳戶 data_dir 的 latest_rankings.json，
    只取「策略宣告的 group」（略過 top_def 等輔助鍵），正規化成 group_rankings dict。
    檔案缺或無宣告 group → 回 None。"""
    raw = _load_json(ROOT / data_dir / "latest_rankings.json")
    if not isinstance(raw, dict):
        return None
    groups = {}
    for gid in _group_ids(strat):
        lst = raw.get(gid)
        if not isinstance(lst, list):
            continue
        groups[gid] = [{
            "sym":     r.get("sym", r.get("symbol", "")),
            "rank":    r.get("rank", i + 1),
            "price":   r.get("price", r.get("close_price", 0)),
            "chg_pct": r.get("chg_pct", r.get("change_pct", 0)),
            "mcap_b":  r.get("mcap_b", r.get("market_cap_b", 0)),
        } for i, r in enumerate(lst) if isinstance(r, dict)]
    return groups or None


def resolve_rankings(state: dict, strat: dict, data_dir: str = ""):
    """回傳 write_data_json 用的 rankings_raw。

    宣告式：strategy.dashboard.rankings.source 指定來源；未指定則自動偵測。
    universe_groups 分組形狀 → 通用地讀 latest_rankings.json（不再靠寫死 migrator）。
    """
    source = _rankings_cfg(strat).get("source", "")
    if is_grouped(strat):
        return _grouped_rankings(strat, data_dir)
    if source != "scorecard" and state.get("ranked_stocks"):
        return state["ranked_stocks"]
    if source == "scorecard" or state.get("scorecard"):
        ranked = sorted(state.get("scorecard", []),
                        key=lambda x: x.get("score", 0), reverse=True)
        return [
            {"sym": s["symbol"], "rank": i + 1, "price": 100.0,
             "chg_pct": (s.get("ret_3m") or 0) * 100, "mcap_b": (s.get("score", 0)) * 25.0}
            for i, s in enumerate(ranked)
        ]
    # 由持股推導：用 positions 的真實股價（避免候選池全是 $100 placeholder）
    price = {p.get("symbol"): p for p in state.get("positions", [])}
    out = []
    for i, s in enumerate(resolve_holdings(state)):
        p = price.get(s, {})
        cur, avg = p.get("current_price"), p.get("avg_entry_price")
        chg = ((cur / avg - 1) * 100) if (cur and avg) else 0.0
        out.append({"rank": i + 1, "symbol": s,
                    "close_price": float(cur) if cur else 0.0,
                    "market_cap": 1e11, "chg_pct": round(chg, 2)})
    return out


# ── 帳戶生命週期：縫合多策略段的 NAV 歷史 + 策略時間軸 ─────────────────────
def _periods(account: Account) -> List[dict]:
    """帳戶歷經的策略段；無 strategy_history 則只有當前一段。"""
    hist = getattr(account, "strategy_history", None)
    if hist:
        return list(hist)
    return [{"strategy": account.strategy, "label": account.label,
             "data_dir": account.data_dir or f"data/{account.id}"}]


def _period_nav(period: dict) -> List[dict]:
    raw = _load_json(ROOT / period["data_dir"] / "portfolio_state_history.json")
    return _extract_nav_history(_extract_history_list(raw))


def stitched_nav_history(account: Account, today: str, today_nav: float) -> List[dict]:
    """所有策略段的 NAV 歷史依日期串接、去重，補上今日。"""
    merged: dict = {}
    for p in _periods(account):
        for e in _period_nav(p):
            if e.get("date"):
                merged[e["date"]] = e["nav"]
    merged[today] = today_nav
    return [{"date": d, "nav": merged[d]} for d in sorted(merged)]


def strategy_timeline(account: Account) -> List[dict]:
    """每段策略的起訖（from=該段首筆日期；最後一段 to=null 表示至今）。"""
    periods = _periods(account)
    out = []
    for i, p in enumerate(periods):
        navs = _period_nav(p)
        out.append({
            "strategy": p.get("strategy", ""),
            "label":    p.get("label", p.get("strategy", "")),
            "from":     navs[0]["date"] if navs else None,
            "to":       (navs[-1]["date"] if navs else None) if i < len(periods) - 1 else None,
        })
    return out


def order_alerts(data_dir: str, days: int = 3) -> list:
    """近 N 天的訂單異常（ORDER_REJECTED / ORDER_STALE）→ 給 email 報告告警。"""
    import datetime as _dt
    # trade_events.jsonl 是 NDJSON（每行一個 JSON），不能用 _load_json 整檔解析
    p = ROOT / data_dir / "trade_events.jsonl"
    events = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days))
    out = []
    for e in events:
        if e.get("type") not in ("ORDER_REJECTED", "ORDER_STALE"):
            continue
        try:
            ts = _dt.datetime.fromisoformat((e.get("ts") or "").replace("Z", "+00:00"))
            if ts < cutoff:
                continue
        except ValueError:
            pass
        out.append({
            "kind": "rejected" if e["type"] == "ORDER_REJECTED" else "stale",
            "symbol": e.get("symbol", ""), "action": e.get("action", ""),
            "detail": e.get("error") or (f"已 {e.get('age_days','?')} 天未成交"),
        })
    return out[-10:]


def can_generate(account: Account) -> bool:
    """此帳戶能否走泛用產生器。分組排名已通用化（讀 latest_rankings.json），
    故只要策略 JSON 載得起來即可——不再有「分組要靠 migrator」的例外。"""
    try:
        load_and_validate(account.strategy)
        return True
    except Exception:  # noqa: BLE001
        return False


# ── 單一帳戶產生器 ─────────────────────────────────────────────────────────
def account_state_date(account: Account) -> Optional[str]:
    """讀帳戶 portfolio_state.json 的 date（用於跨帳戶過時偵測）。"""
    data_dir = account.data_dir or f"data/{account.id}"
    state = _load_json(ROOT / data_dir / "portfolio_state.json")
    return state.get("date") if isinstance(state, dict) else None


def generate_for_account(account: Account, output_dir: Path,
                         dry_run: bool = False,
                         peer_max_date: Optional[str] = None) -> str:
    """產出 mvp_data/{id}/data.json。回 "ok" / "skip"（無資料）/ "fail"。"""
    data_dir = account.data_dir or f"data/{account.id}"
    state = _load_json(ROOT / data_dir / "portfolio_state.json")
    if not state:
        logger.warning("帳戶 #%s 無 state（%s），略過", account.id, data_dir)
        return "skip"

    strat = load_and_validate(account.strategy)
    history     = _extract_history_list(_load_json(ROOT / data_dir / "portfolio_state_history.json"))
    trade_log   = _extract_trade_log(history)

    today = state["date"]
    # 帳戶生命週期：縫合所有策略段的 NAV 歷史（inception=最早一段、TWR 連續）
    nav_history = stitched_nav_history(account, today, state["nav"])

    holdings = resolve_holdings(state)
    rankings = resolve_rankings(state, strat, data_dir)

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

    output_path = output_dir / account.id / "data.json"
    if dry_run:
        logger.info("DRY RUN：略過 #%s", account.id)
        return "ok"

    data = write_data_json(
        output_path           = output_path,
        strategy_cfg          = strat,
        account               = account,
        same_strategy_accounts= [account],
        nav                   = state["nav"],
        cash                  = state["cash"],
        positions             = state.get("positions", []),
        top_n_symbols         = holdings,
        executed_orders       = [],
        rankings_raw          = rankings,
        trading_date          = today,
        dry_run               = False,
        existing_data         = existing_data,
    )
    bench = _load_benchmark_drawdown()
    if bench:
        all_nav = data.get("nav_history", [])
        sp500_dd, nasdaq_dd = _align_benchmark(all_nav, bench)
        data["drawdown"]["sp500"]  = [round(v, 4) if v is not None else None for v in sp500_dd]
        data["drawdown"]["nasdaq"] = [round(v, 4) if v is not None else None for v in nasdaq_dd]
    init_nav = nav_history[0]["nav"] if nav_history else state["nav"]
    bench_nav = _compute_benchmark_nav(data.get("nav_history", []), init_nav)
    if bench_nav:
        data["benchmark_nav"] = bench_nav
    # 帳戶生命週期：歷經多策略 → 附策略歷史時間軸（報告渲染「策略歷史」表）
    timeline = strategy_timeline(account)
    if len(timeline) > 1:
        data["strategy_history"] = timeline
    # 訂單異常告警（近 N 天 REJECTED / STALE）→ email 報告紅色橫幅
    alerts = order_alerts(data_dir)
    if alerts:
        data["order_alerts"] = alerts
    # 過時偵測：此帳戶日期落後其他帳戶 → 今日未更新（執行失敗/金鑰問題），紅字標示
    if peer_max_date and today < peer_max_date:
        data["stale_warning"] = (
            f"⚠️ 今日未更新（資料停在 {today}，其他帳戶已更新到 {peer_max_date}）。"
            "可能執行失敗或券商金鑰問題——請查當日 Actions 執行紀錄。")
    # 落後上游提示（僅在 GitHub Actions 內計算；本地/測試不觸發網路）
    if os.environ.get("GITHUB_ACTIONS") == "true":
        from engine.upstream_check import cached_behind_notice
        notice = cached_behind_notice()
        if notice:
            data["upstream_notice"] = notice
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    validate_data_json(data)
    _save_dated_snapshot(data, output_dir, account.id, today)
    logger.info("✅ #%s（%s）報告產生完成：%s", account.id, account.strategy, output_path)
    return "ok"


def generate_all(output_dir: Path, dry_run: bool = False,
                 legacy=None) -> dict:
    """對 accounts.json 每個 enabled 帳戶產生報告（純資料驅動，無寫死策略）。

    legacy 參數已棄用（分組排名已通用化）；保留簽名僅為向後相容，忽略其值。
    """
    accounts = [a for a in load_accounts() if a.enabled]
    # 過時偵測基準：所有帳戶中最新的 state 日期（休市日大家相同→不誤報）
    dates = [d for d in (account_state_date(a) for a in accounts) if d]
    peer_max_date = max(dates) if dates else None
    results = {}
    for acct in accounts:
        try:
            if not can_generate(acct):                   # 策略 JSON 載不起來
                logger.error("#%s 策略 %s 載入失敗", acct.id, acct.strategy)
                results[acct.id] = "fail"
                continue
            results[acct.id] = generate_for_account(acct, output_dir, dry_run,
                                                    peer_max_date=peer_max_date)
        except Exception as exc:  # noqa: BLE001
            logger.error("產生 #%s 失敗：%s", acct.id, exc)
            results[acct.id] = "fail"
    return results
