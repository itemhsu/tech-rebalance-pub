"""engine/cashflow.py — 外部現金流（入金/出金）落地 + 轉 TWR 事件。

為什麼需要：report_generator 每天從 portfolio_state_history 重建 data.json，
若沒有入金事件，compute_twr 會退化成「單純報酬」，入金被當成報酬
（#3 於 2026-06 入金 $9,476 → dashboard 顯示 +64.81%）。

流程：
  runner（每次執行、守門前）→ sync_cash_flows(client, data_dir)
      → 向券商抓自成立日起的 CSD/CSW/JNLC → 寫 data/<id>/cash_flows.json（整份覆寫、冪等）
  report_generator → load_cash_flows + flows_to_events(nav_history) → existing_data["events"]
      → compute_twr 以 nav_before / nav_after 切子期間，入金不再算報酬

非 Alpaca 券商（永豐 SDK）沒有 get_cash_flows → 不抓、不覆寫既有檔、不報錯。
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

_FILE = "cash_flows.json"
_WIDE_SINCE = "2000-01-01"     # 無歷史時的保底起點（券商活動量小，全抓無妨）
_FLOW_TYPES = ("deposit", "withdrawal")
MIN_FLOW = 1.0                 # USD；低於此視為雜訊（如 Juneteenth 保證金補貼 $0.06）


def load_cash_flows(data_dir: Path | str) -> List[dict]:
    """讀 data_dir/cash_flows.json 的 flows；檔案缺或壞 → []。"""
    p = Path(data_dir) / _FILE
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    flows = raw.get("flows") if isinstance(raw, dict) else raw
    return [f for f in (flows or []) if isinstance(f, dict)]


def _inception_date(data_dir: Path) -> Optional[str]:
    p = data_dir / "portfolio_state_history.json"
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    hist = raw.get("history") if isinstance(raw, dict) else raw
    dates = sorted(h.get("date") for h in (hist or []) if isinstance(h, dict) and h.get("date"))
    return dates[0] if dates else None


def _normalize(flows: list) -> List[dict]:
    """只留 deposit/withdrawal、amount 取正數且 ≥ MIN_FLOW、依 (date,type,amount) 去重、日期排序。"""
    seen = set()
    out = []
    for f in flows or []:
        if not isinstance(f, dict) or f.get("type") not in _FLOW_TYPES:
            continue
        try:
            amt = round(abs(float(f.get("amount") or 0)), 2)
        except (TypeError, ValueError):
            continue
        day = str(f.get("date") or "")[:10]
        if amt < MIN_FLOW or not day:
            continue
        key = (day, f["type"], amt)
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": day, "type": f["type"], "amount": amt})
    out.sort(key=lambda x: (x["date"], x["type"]))
    return out


def sync_cash_flows(client, data_dir: Path | str, log: Optional[logging.Logger] = None) -> List[dict]:
    """向券商抓「自帳戶成立日前一天起」的入出金，整份覆寫 cash_flows.json。

    - 整份重抓 + 去重 → 冪等；首次上線就能補到歷史入金。
    - client 無 get_cash_flows（SDK 券商）→ 回 []、不動既有檔。
    - 券商錯誤 → 記 warning、回 []、不動既有檔（永不讓每日流程因此失敗）。
    """
    log = log or logging.getLogger(__name__)
    data_dir = Path(data_dir)
    getter = getattr(client, "get_cash_flows", None)
    if not callable(getter):
        return []
    inception = _inception_date(data_dir)
    since = ((date.fromisoformat(inception) - timedelta(days=1)).isoformat()
             if inception else _WIDE_SINCE)
    try:
        flows = _normalize(getter(since))
    except Exception as e:  # noqa: BLE001
        log.warning("現金流同步失敗（忽略，沿用既有 cash_flows.json）：%s", e)
        return []
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / _FILE).write_text(json.dumps(
        {"synced_at": date.today().isoformat(), "since": since, "flows": flows},
        ensure_ascii=False, indent=2), encoding="utf-8")
    if flows:
        log.info("現金流同步：%d 筆（自 %s）→ %s", len(flows), since, data_dir / _FILE)
    return flows


def _nav_before(flow: dict, history: List[dict]) -> Optional[float]:
    """入金前最後一筆 NAV。

    規則：取 date < 流水日的最後一筆。但若「流水日當天」也有快照、且其 NAV 明顯
    尚未反映該筆現金流（入金：當日 NAV < 前一筆 + 金額/2；出金：當日 NAV > 前一筆 − 金額/2），
    代表快照在入帳前拍的 → 改用當天快照，避免把當天漲跌算進入金子期間。
    """
    day, amt, kind = flow["date"], flow["amount"], flow["type"]
    prev = [h for h in history if h["date"] < day]
    same = [h for h in history if h["date"] == day]
    prev_nav = prev[-1]["nav"] if prev else None
    if same:
        nav = same[-1]["nav"]
        if prev_nav is None:
            return nav
        half = amt / 2.0
        if (kind == "deposit" and nav < prev_nav + half) or \
           (kind == "withdrawal" and nav > prev_nav - half):
            return nav
    return prev_nav


def flows_to_events(flows: List[dict], nav_history: List[dict]) -> List[dict]:
    """把正規化流水轉成 data.json events（compute_twr 用 nav_before/nav_after 切期）。
    出金 amount 為負（compute_net_contribution 慣例）。無歷史 → []。"""
    history = sorted((h for h in (nav_history or []) if h.get("date")), key=lambda h: h["date"])
    if not history:
        return []
    from engine.data_writer import append_event
    events: List[dict] = []
    for f in _normalize(flows):
        before = _nav_before(f, history)
        if before is None or before <= 0:
            continue
        signed = f["amount"] if f["type"] == "deposit" else -f["amount"]
        events = append_event(events, f["type"], f["date"], before, before + signed, amount=signed)
    return events


def net_flow_on(events: List[dict], day: str) -> float:
    """某日的淨外部現金流（入金正、出金負）。"""
    return sum(float(e.get("amount") or 0) for e in events
               if e.get("type") in _FLOW_TYPES and e.get("date") == day)
