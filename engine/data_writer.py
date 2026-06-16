"""
engine/data_writer.py — 從策略執行結果產生 data.json

架構：
  build_meta()         → meta section
  build_summary()      → summary section
  build_portfolio()    → portfolio section
  build_positions()    → positions section
  build_nav_history()  → nav_history section（append 模式）
  build_drawdown()     → drawdown section
  build_events()       → events section（append 模式）
  append_event()       → 新增單一事件
  build_rankings_*()   → rankings section（多型）
  build_email_meta()   → email section
  write_data_json()    → 整合入口，寫出 data.json
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from engine.twr import (
    compute_twr, compute_net_contribution,
    compute_totals, compute_investment_gain,
)
from engine.accounts      import Account, get_same_strategy_accounts
from engine.strategy_card import build_strategy_card

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
DASHBOARD_BASE_URL = "https://itemhsu.github.io/tech-rebalance-dashboard"


def _account_currency(account: Account) -> str:
    """依帳戶券商推幣別代碼（與 dashboard resolveCurrency 對齊）。

    來源：broker spec 的 market.currency（單一真相；sinopac→TWD、alpaca/tradier→USD）。
    載入失敗或未設則預設 USD。email_renderer / dashboard 再把 TWD→NT$、其餘→$。
    """
    broker = getattr(account, "broker", None) or "alpaca"
    try:
        from brokers.registry import load_broker_spec
        ccy = (load_broker_spec(broker).get("market") or {}).get("currency")
        if ccy:
            return str(ccy)
    except Exception:   # noqa: BLE001  券商 spec 缺失不應擋住報告
        pass
    return "USD"


# ══════════════════════════════════════════════════════════════════════════════
#  Meta
# ══════════════════════════════════════════════════════════════════════════════

def build_meta(
    strategy_cfg: dict,
    account: Account,
    same_strategy_accounts: List[Account],
    dry_run: bool = False,
    strategy_status: str = "active",
    strategy_start_date: Optional[str] = None,
    previous_strategy: Optional[str] = None,
    trading_date: Optional[str] = None,
    currency: str = "USD",
) -> dict:
    today = trading_date or date.today().isoformat()
    return {
        "schema_version":   SCHEMA_VERSION,
        "strategy":         strategy_cfg["id"],
        "account_id":       account.id,
        "account_label":    account.label,
        "currency":         currency,
        "generated_at":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trading_date":     today,
        "dry_run":          dry_run,
        "strategy_status":  strategy_status,
        "strategy_start_date": strategy_start_date or today,
        "previous_strategy": previous_strategy,
        "accent_color":     strategy_cfg["dashboard"]["accent_color"],
        "same_strategy_accounts": [
            {"id": a.id, "label": a.label}
            for a in same_strategy_accounts
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Summary
# ══════════════════════════════════════════════════════════════════════════════

def build_summary(
    nav: float,
    cash: float,
    initial_nav: float,
    inception_date: str,
    prev_nav: Optional[float],
    nav_history: List[dict],
    events: List[dict],
    trading_date: Optional[str] = None,
) -> dict:
    today = trading_date or date.today().isoformat()

    # 今日損益
    today_change     = nav - prev_nav if prev_nav is not None else 0.0
    today_change_pct = (today_change / prev_nav * 100) if prev_nav and prev_nav != 0 else 0.0

    # 報酬率
    total_return     = nav - initial_nav
    total_return_pct = (total_return / initial_nav * 100) if initial_nav != 0 else 0.0
    twr              = compute_twr(nav_history, events)

    # 資金流量
    net_contribution    = compute_net_contribution(events)
    total_deposited, total_withdrawn = compute_totals(events)
    investment_gain  = compute_investment_gain(nav, initial_nav, net_contribution)

    # YTD / 月報酬
    ytd_return_pct     = _compute_ytd(nav, nav_history, today)
    monthly_return_pct = _compute_monthly(nav, nav_history, today)

    # 最大回撤
    max_drawdown_pct = _compute_max_drawdown([p["nav"] for p in nav_history] + [nav])

    # 暫停統計
    paused_days, is_paused, paused_since = _compute_pause_stats(events)

    return {
        "nav":                  round(nav, 2),
        "cash":                 round(cash, 2),
        "initial_nav":          round(initial_nav, 2),
        "inception_date":       inception_date,
        "today_change":         round(today_change, 2),
        "today_change_pct":     round(today_change_pct, 4),
        "total_return":         round(total_return, 2),
        "total_return_pct":     round(total_return_pct, 4),
        "total_return_pct_twr": round(twr, 4),
        "net_contribution":     round(net_contribution, 2),
        "total_deposited":      round(total_deposited, 2),
        "total_withdrawn":      round(total_withdrawn, 2),
        "investment_gain":      round(investment_gain, 2),
        "ytd_return_pct":       round(ytd_return_pct, 4) if ytd_return_pct is not None else None,
        "monthly_return_pct":   round(monthly_return_pct, 4) if monthly_return_pct is not None else None,
        "max_drawdown_pct":     round(min(max_drawdown_pct, 0.0), 4),
        "sharpe_ratio":         None,   # 需要 30+ 天資料，在整合層計算
        "total_paused_days":    paused_days,
        "is_paused":            is_paused,
        "paused_since":         paused_since,
    }


def _compute_ytd(nav: float, history: List[dict], today: str) -> Optional[float]:
    year = today[:4]
    year_start = [p for p in history if p["date"] < f"{year}-01-01"]
    if not year_start:
        return None
    base = year_start[-1]["nav"]
    return (nav / base - 1) * 100 if base != 0 else None


def _compute_monthly(nav: float, history: List[dict], today: str) -> Optional[float]:
    ym = today[:7]   # "YYYY-MM"
    month_start = [p for p in history if p["date"] < f"{ym}-01"]
    if not month_start:
        return None
    base = month_start[-1]["nav"]
    return (nav / base - 1) * 100 if base != 0 else None


def _compute_max_drawdown(navs: List[float]) -> float:
    if len(navs) < 2:
        return 0.0
    max_dd = 0.0
    peak = navs[0]
    for n in navs[1:]:
        if n > peak:
            peak = n
        if peak > 0:
            dd = (n - peak) / peak * 100
            max_dd = min(max_dd, dd)
    return max_dd


def _compute_pause_stats(events: List[dict]) -> tuple[int, bool, Optional[str]]:
    paused_days = 0
    is_paused   = False
    paused_since: Optional[str] = None
    pause_start: Optional[str] = None

    for e in sorted(events, key=lambda x: x["date"]):
        if e["type"] == "strategy_pause":
            pause_start  = e["date"]
            is_paused    = True
            paused_since = e["date"]
        elif e["type"] == "strategy_resume" and pause_start:
            from datetime import date as _date
            d0 = _date.fromisoformat(pause_start)
            d1 = _date.fromisoformat(e["date"])
            paused_days += (d1 - d0).days
            is_paused    = False
            paused_since = None
            pause_start  = None

    return paused_days, is_paused, paused_since


# ══════════════════════════════════════════════════════════════════════════════
#  Portfolio
# ══════════════════════════════════════════════════════════════════════════════

def build_portfolio(
    strategy_cfg: dict,
    top_n_symbols: List[str],
    orders_count: int = 0,
) -> dict:
    return {
        "label":           strategy_cfg["dashboard"]["portfolio_label"],
        "symbols":         list(top_n_symbols),
        "rebalance_count": orders_count,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Positions
# ══════════════════════════════════════════════════════════════════════════════

def build_positions(
    raw_positions: List[dict],
    top_n_symbols: List[str],
    nav: float,
) -> List[dict]:
    portfolio_set = set(top_n_symbols)
    result = []
    for p in raw_positions:
        sym = p["symbol"]
        mv  = p.get("market_value", p.get("qty", 0) * p.get("current_price", 0))
        weight = (mv / nav * 100) if nav > 0 else 0.0
        # unrealized_plpc: 某些源格式是小數（0.02）需轉換為百分比
        raw_plpc = p.get("unrealized_plpc", 0.0)
        plpc = raw_plpc * 100 if abs(raw_plpc) < 1.0 and raw_plpc != 0 else raw_plpc
        result.append({
            "symbol":          sym,
            "qty":             p.get("qty", 0),
            "avg_entry_price": round(p.get("avg_entry_price", 0), 6),
            "current_price":   round(p.get("current_price", 0), 4),
            "market_value":    round(mv, 2),
            "unrealized_pl":   round(p.get("unrealized_pl", 0), 2),
            "unrealized_plpc": round(plpc, 6),
            "weight":          round(weight, 4),
            "in_portfolio":    sym in portfolio_set,
        })
    # 依市值排序（大到小）
    result.sort(key=lambda x: x["market_value"], reverse=True)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  NAV History
# ══════════════════════════════════════════════════════════════════════════════

def build_nav_history(
    existing_history: List[dict],
    today_nav: float,
    today_date: str,
    today_events: Optional[List[dict]] = None,
) -> List[dict]:
    """
    Append 今日 NAV 到歷史。若同日已存在，覆蓋（避免重複執行產生重複）。
    若當日有事件，加入 event 標記（取第一個事件）。
    """
    history = [p for p in existing_history if p["date"] != today_date]

    entry: dict = {"date": today_date, "nav": round(today_nav, 2)}

    if today_events:
        e = today_events[0]
        icon_map = {
            "deposit":         "💰 入金",
            "withdrawal":      "💸 出金",
            "strategy_switch": "🔄 切換策略",
            "strategy_pause":  "⏸️ 策略暫停",
            "strategy_resume": "▶️ 策略恢復",
        }
        label = icon_map.get(e["type"], e["type"])
        if e["type"] in ("deposit", "withdrawal"):
            amt = e.get("amount", 0)
            sign = "+" if amt >= 0 else ""
            label = f"{label} {sign}${abs(amt):,.0f}"
        elif e["type"] == "strategy_switch":
            label = f"{label} {e.get('from_strategy','?')}→{e.get('to_strategy','?')}"

        entry["event"] = {"type": e["type"], "label": label}
        if e["type"] in ("deposit", "withdrawal"):
            entry["event"]["amount"] = e.get("amount", 0)

    history.append(entry)
    history.sort(key=lambda p: p["date"])
    return history


# ══════════════════════════════════════════════════════════════════════════════
#  Drawdown
# ══════════════════════════════════════════════════════════════════════════════

def build_drawdown(
    nav_history: List[dict],
    benchmark_data: Optional[dict] = None,
) -> dict:
    """
    計算回撤序列。benchmark_data = {"QQQ": [...], "SPY": [...]} (NAV 序列)。
    """
    dates     = [p["date"] for p in nav_history]
    port_navs = [p["nav"] for p in nav_history]

    portfolio_dd = _drawdown_series(port_navs)

    # Benchmark（若無資料則全 null）
    bench = benchmark_data or {}
    qqq_navs = bench.get("QQQ", [])
    spy_navs = bench.get("SPY", [])

    nasdaq_dd = _drawdown_series(qqq_navs) if qqq_navs else [None] * len(dates)
    sp500_dd  = _drawdown_series(spy_navs) if spy_navs  else [None] * len(dates)

    # 對齊長度（benchmark 長度可能不同）
    n = len(dates)
    nasdaq_dd = _pad_or_trim(nasdaq_dd, n)
    sp500_dd  = _pad_or_trim(sp500_dd,  n)

    return {
        "dates":     dates,
        "portfolio": [round(v, 4) for v in portfolio_dd],
        "nasdaq":    [round(v, 4) if v is not None else None for v in nasdaq_dd],
        "sp500":     [round(v, 4) if v is not None else None for v in sp500_dd],
    }


def _drawdown_series(navs: List[float]) -> List[float]:
    if not navs:
        return []
    result = []
    peak = navs[0]
    for n in navs:
        if n > peak:
            peak = n
        dd = (n / peak - 1) * 100 if peak > 0 else 0.0
        result.append(dd)
    return result


def _pad_or_trim(series: List, n: int) -> List:
    if len(series) >= n:
        return series[:n]
    return [None] * (n - len(series)) + series


# ══════════════════════════════════════════════════════════════════════════════
#  Events
# ══════════════════════════════════════════════════════════════════════════════

def build_events(existing_events: Optional[List[dict]] = None) -> List[dict]:
    return list(existing_events or [])


def append_event(
    events: List[dict],
    event_type: str,
    date_str: str,
    nav_before: float,
    nav_after: float,
    amount: Optional[float] = None,
    from_strategy: Optional[str] = None,
    to_strategy: Optional[str] = None,
    pause_reason: Optional[str] = None,
    resumed_date: Optional[str] = None,
    note: Optional[str] = None,
) -> List[dict]:
    """新增一個事件，回傳新的 events 列表。"""
    # 生成唯一 ID
    seq = sum(1 for e in events if e["date"] == date_str) + 1
    event_id = f"evt_{date_str.replace('-','')}_{seq:03d}"

    entry: dict = {
        "id":        event_id,
        "date":      date_str,
        "type":      event_type,
        "nav_before": round(nav_before, 2),
        "nav_after":  round(nav_after, 2),
    }
    if amount is not None:
        entry["amount"] = round(amount, 2)
    if from_strategy:
        entry["from_strategy"] = from_strategy
    if to_strategy:
        entry["to_strategy"] = to_strategy
    if pause_reason:
        entry["pause_reason"] = pause_reason
    if resumed_date:
        entry["resumed_date"] = resumed_date
    if note:
        entry["note"] = note

    return events + [entry]


def get_today_events(events: List[dict], today: str) -> List[dict]:
    return [e for e in events if e["date"] == today]


# ══════════════════════════════════════════════════════════════════════════════
#  Trade Log
# ══════════════════════════════════════════════════════════════════════════════

def build_trade_log(
    existing_log: List[dict],
    today_date: str,
    nav: float,
    top_n_symbols: List[str],
    executed_orders: List[dict],
) -> List[dict]:
    """Append 今日交易紀錄（降序排列，最新在前）。"""
    log = [e for e in existing_log if e["date"] != today_date]

    entry = {
        "date":         today_date,
        "nav":          round(nav, 2),
        "trades_count": len(executed_orders),
        "portfolio":    list(top_n_symbols),
        "orders":       [_normalise_order(o) for o in executed_orders],
    }
    log.insert(0, entry)
    return log


def _normalise_order(o: dict) -> dict:
    return {
        "symbol": o.get("symbol", ""),
        "side":   o.get("side", "buy"),
        "qty":    float(o.get("qty", o.get("notional", 0))),
        "price":  float(o.get("price", o.get("filled_avg_price", 0))),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Rankings（多型）
# ══════════════════════════════════════════════════════════════════════════════

def build_rankings_market_cap(
    strategy_cfg: dict,
    ranked_stocks: List[dict],
    top_n_symbols: List[str],
) -> dict:
    """
    TOP10 策略用。
    ranked_stocks: [{"symbol": ..., "price": ..., "market_cap": ..., "rank": ..., "chg_pct": ...}]
    """
    portfolio_set = set(top_n_symbols)
    show_n = strategy_cfg["dashboard"]["rankings"].get("show_top_n", 20)
    items = []
    for s in ranked_stocks[:show_n]:
        items.append({
            "rank":         s.get("rank", 0),
            "symbol":       s["symbol"],
            "price":        round(s.get("close_price", s.get("price", 0)), 2),
            "change_pct":   round(s.get("chg_pct", s.get("change_pct", 0)), 4),
            "market_cap_b": round(s.get("market_cap", s.get("market_cap_b", 0)) / 1e9
                                  if s.get("market_cap", 0) > 1e6
                                  else s.get("market_cap_b", 0), 1),
            "in_portfolio": s["symbol"] in portfolio_set,
        })
    return {
        "type":  "market_cap_list",
        "label": strategy_cfg["dashboard"]["rankings"]["title"],
        "items": items,
    }


def build_rankings_universe_groups(
    strategy_cfg: dict,
    group_rankings: dict,
    top_n_symbols: List[str],
) -> dict:
    """
    D2P2T6 策略用。
    group_rankings: {"defense": [...], "pharma": [...], "tech": [...]}
    每個列表元素：{"sym": ..., "rank": ..., "price": ..., "chg_pct": ..., "mcap_b": ...}
    """
    portfolio_set = set(top_n_symbols)
    dash_cfg  = strategy_cfg["dashboard"]["rankings"]
    show_n    = dash_cfg.get("show_top_n_per_group", 5)
    group_labels = dash_cfg.get("group_labels", {})

    groups = []
    for group_id, stocks in group_rankings.items():
        label = group_labels.get(group_id, group_id)
        # 至少顯示 show_n 筆，但若組合內有更多股票，延伸到包含所有組合成員
        portfolio_in_group = sum(
            1 for s in stocks
            if s.get("sym", s.get("symbol", "")) in portfolio_set
        )
        effective_n = max(show_n, portfolio_in_group)
        items = []
        for s in stocks[:effective_n]:
            sym = s.get("sym", s.get("symbol", ""))
            items.append({
                "rank":         s.get("rank", 0),
                "symbol":       sym,
                "price":        round(s.get("price", 0), 2),
                "change_pct":   round(s.get("chg_pct", s.get("change_pct", 0)), 4),
                "market_cap_b": round(s.get("mcap_b", s.get("market_cap_b", 0)), 1),
                "in_portfolio": sym in portfolio_set,
            })
        groups.append({"id": group_id, "label": label, "items": items})

    return {
        "type":   "universe_groups",
        "label":  dash_cfg["title"],
        "groups": groups,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Email Meta
# ══════════════════════════════════════════════════════════════════════════════

def build_email_meta(
    strategy_cfg: dict,
    account_id: str,
    nav: float,
    today_change_pct: float,
    trading_date: str,
    sections: List[str],
    currency: str = "USD",
) -> dict:
    tmpl = strategy_cfg["email"]["subject_template"]
    subject = tmpl.format(
        account_id=account_id,
        date=trading_date,
        nav=nav,
        today_change_pct=today_change_pct,
    )
    sym = "NT$" if currency == "TWD" else "$"
    dashboard_url = f"{DASHBOARD_BASE_URL}/mvp_dashboard.html?a={account_id}"
    return {
        "subject":           subject,
        "preheader":         f"帳戶 #{account_id} · {trading_date} · NAV {sym}{nav:,.0f}",
        "dashboard_url":     dashboard_url,
        "sections_rendered": sections,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  整合入口
# ══════════════════════════════════════════════════════════════════════════════

def write_data_json(
    output_path: Path,
    strategy_cfg: dict,
    account: Account,
    same_strategy_accounts: List[Account],
    nav: float,
    cash: float,
    positions: List[dict],
    top_n_symbols: List[str],
    executed_orders: List[dict],
    rankings_raw: Any,                 # ranked_stocks list 或 group_rankings dict
    trading_date: str,
    dry_run: bool = False,
    existing_data: Optional[dict] = None,
    benchmark_data: Optional[dict] = None,
    new_events: Optional[List[dict]] = None,
) -> dict:
    """
    組合完整 data.json 並寫出到 output_path。
    existing_data: 上次執行的 data.json（用於 append 歷史資料）
    回傳完整的 data dict。
    """
    ex = existing_data or {}
    ccy = _account_currency(account)   # 依券商推幣別（TWD/USD），供 meta + 郵件 preheader

    # ── 事件 ─────────────────────────────────────────────────────────────────
    events = build_events(ex.get("events", []))
    for evt in (new_events or []):
        events = events + [evt]

    today_events = get_today_events(events, trading_date)

    # ── NAV 歷史 ─────────────────────────────────────────────────────────────
    prev_history = ex.get("nav_history", [])
    prev_nav     = prev_history[-1]["nav"] if prev_history else None
    nav_history  = build_nav_history(prev_history, nav, trading_date, today_events or None)

    # ── 各 section ───────────────────────────────────────────────────────────
    # 從 existing meta 取得策略啟動日與前策略
    ex_meta = ex.get("meta", {})
    strategy_start = ex_meta.get("strategy_start_date", trading_date)
    prev_strategy  = ex_meta.get("previous_strategy")

    # 判斷策略狀態
    strategy_status = "active"
    if events:
        last_type = sorted(events, key=lambda e: e["date"])[-1]["type"]
        if last_type == "strategy_pause":
            strategy_status = "paused"
        elif last_type == "strategy_switch":
            strategy_status = "switched"

    meta = build_meta(
        strategy_cfg          = strategy_cfg,
        account               = account,
        same_strategy_accounts= same_strategy_accounts,
        dry_run               = dry_run,
        strategy_status       = strategy_status,
        strategy_start_date   = strategy_start,
        previous_strategy     = prev_strategy,
        trading_date          = trading_date,
        currency              = ccy,
    )

    summary = build_summary(
        nav           = nav,
        cash          = cash,
        initial_nav   = ex.get("summary", {}).get("initial_nav", nav),
        inception_date= ex.get("summary", {}).get("inception_date", trading_date),
        prev_nav      = prev_nav,
        nav_history   = nav_history,
        events        = events,
        trading_date  = trading_date,
    )

    portfolio = build_portfolio(strategy_cfg, top_n_symbols, len(executed_orders))
    positions_out = build_positions(positions, top_n_symbols, nav)

    drawdown = build_drawdown(nav_history, benchmark_data)

    trade_log = build_trade_log(
        existing_log   = ex.get("trade_log", []),
        today_date     = trading_date,
        nav            = nav,
        top_n_symbols  = top_n_symbols,
        executed_orders= executed_orders,
    )

    # Rankings 多型
    uni_type = strategy_cfg["universe"]["type"]
    if uni_type == "single":
        rankings = build_rankings_market_cap(strategy_cfg, rankings_raw, top_n_symbols)
    else:
        rankings = build_rankings_universe_groups(strategy_cfg, rankings_raw, top_n_symbols)

    email_sections = strategy_cfg["email"]["sections"]
    email_meta = build_email_meta(
        strategy_cfg     = strategy_cfg,
        account_id       = account.id,
        nav              = nav,
        today_change_pct = summary["today_change_pct"],
        trading_date     = trading_date,
        sections         = email_sections,
        currency         = ccy,
    )

    data = {
        "meta":          meta,
        "summary":       summary,
        "strategy_card": build_strategy_card(strategy_cfg),
        "portfolio":     portfolio,
        "positions":     positions_out,
        "nav_history":   nav_history,
        "drawdown":      drawdown,
        "trade_log":     trade_log,
        "rankings":      rankings,
        "events":        events,
        "email":         email_meta,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("data.json 已寫出：%s", output_path)
    return data
