"""
trade_log.py — 結構化交易事件記錄器

每個帳戶寫 NDJSON（每行一個 JSON event）到 data/<account_id>/trade_events.jsonl，
append-only，方便 grep/jq 分析「誰觸發、為何下單」。

事件類型 (event types):
- REBALANCE_TRIGGER  : 啟動再平衡（含 trigger 來源 + 為何）
- REBALANCE_SKIP     : 跳過再平衡（含原因）
- ORDER_PLANNED      : 計劃下單（含 pre/post qty、weight、reason）
- ORDER_SUBMITTED    : 已送出給 broker（含 order_id）
- ORDER_FILLED       : 成交回報
- ORDER_REJECTED     : broker 拒絕
- REBALANCE_SUMMARY  : 收尾統計 + 換股守則驗證

理由代碼 (reason codes):
- exit_top10         : 跌出 Top N，全清
- new_entrant        : 新進 Top N，建倉
- weight_adjust      : 持續持股權重超出容忍帶
- cash_deployment    : 賣出後閒置現金分散到 Top N

觸發代碼 (trigger codes):
- monthly_first_day  : 月初第一個交易日（排程）
- weekly_scheduled   : 週度排程
- daily_scheduled    : 每日排程
- composition_change : Top N 名單變動觸發
- weight_drift       : 持股偏離目標權重超過閾值
- manual_dispatch    : 手動觸發
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 預設路徑：data/<account_id>/trade_events.jsonl
_DEFAULT_ACCOUNT = os.environ.get("TOP10_ACCOUNT_ID", "1")
_DEFAULT_PATH = Path(__file__).parent / "data" / _DEFAULT_ACCOUNT / "trade_events.jsonl"

_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_path(path: Optional[Path] = None, account_id: Optional[str] = None) -> Path:
    """決定要寫的 jsonl 路徑。優先順序：明確路徑 > account_id 推導 > 環境變數預設。"""
    if path is not None:
        return Path(path)
    if account_id is not None:
        return Path(__file__).parent / "data" / str(account_id) / "trade_events.jsonl"
    return _DEFAULT_PATH


def write_event(
    event_type: str,
    *,
    path: Optional[Path] = None,
    account_id: Optional[str] = None,
    **fields: Any,
) -> None:
    """寫一筆事件到 jsonl。所有 keyword args 都會進到該事件物件。

    用法：
        trade_log.write_event(
            "ORDER_PLANNED",
            account_id="1",
            symbol="ORCL", action="SELL", qty=10,
            reason="exit_top10", trigger="monthly_first_day",
            pre_qty=10, post_qty=0,
            current_weight=0.105, target_weight=0.0,
        )
    """
    target = _resolve_path(path, account_id)
    event = {
        "ts": _utc_now(),
        "type": event_type,
        "account": account_id or _DEFAULT_ACCOUNT,
        **fields,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(target, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("trade_log 寫入失敗 %s: %s", target, e)


def read_events(
    account_id: Optional[str] = None, path: Optional[Path] = None
) -> list:
    """讀回某帳戶的所有事件（list[dict]，缺檔回 []）。給對帳/檢視用。"""
    target = _resolve_path(path, account_id)
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ────────────────────────────────────────────────
# 高層便利函式
# ────────────────────────────────────────────────

def record_trigger(
    *, account_id: str, strategy: str, trigger: str, detail: str = "",
    today: str = "", path: Optional[Path] = None,
) -> None:
    """記錄「為何啟動本次再平衡」。"""
    write_event(
        "REBALANCE_TRIGGER",
        account_id=account_id, path=path,
        strategy=strategy, trigger=trigger, detail=detail, today=today,
    )


def record_skip(
    *, account_id: str, strategy: str, reason_code: str, reason_human: str = "",
    today: str = "", path: Optional[Path] = None,
) -> None:
    """記錄「為何跳過再平衡」。"""
    write_event(
        "REBALANCE_SKIP",
        account_id=account_id, path=path,
        strategy=strategy, reason_code=reason_code, reason_human=reason_human,
        today=today,
    )


def record_order_plan(
    *, account_id: str, strategy: str, symbol: str, action: str,
    qty: float, est_value: float, reason: str,
    trigger: str = "",
    pre_qty: float = 0.0, post_qty: float = 0.0,
    current_weight: float = 0.0, target_weight: float = 0.0,
    path: Optional[Path] = None,
) -> None:
    """記錄「我打算下這張單，因為 ___」（送出前）。"""
    write_event(
        "ORDER_PLANNED",
        account_id=account_id, path=path,
        strategy=strategy, symbol=symbol, action=action,
        qty=qty, est_value=round(est_value, 2),
        reason=reason, trigger=trigger,
        pre_qty=pre_qty, post_qty=post_qty,
        current_weight=round(current_weight, 4),
        target_weight=round(target_weight, 4),
    )


def record_order_submit(
    *, account_id: str, strategy: str, symbol: str, action: str, qty: float,
    order_id: str, reason: str = "",
    path: Optional[Path] = None,
) -> None:
    """記錄「已送出給 broker，得到 order_id」。"""
    write_event(
        "ORDER_SUBMITTED",
        account_id=account_id, path=path,
        strategy=strategy, symbol=symbol, action=action, qty=qty,
        order_id=order_id, reason=reason,
    )


def record_order_fill(
    *, account_id: str, strategy: str, symbol: str, action: str, qty: float,
    order_id: str, filled_avg_price: float = 0.0, reason: str = "",
    path: Optional[Path] = None,
) -> None:
    """記錄「broker 確認成交」。"""
    write_event(
        "ORDER_FILLED",
        account_id=account_id, path=path,
        strategy=strategy, symbol=symbol, action=action, qty=qty,
        order_id=order_id, filled_avg_price=round(filled_avg_price, 4),
        reason=reason,
    )


def record_order_reject(
    *, account_id: str, strategy: str, symbol: str, action: str, qty: float,
    reason: str = "", error: str = "",
    path: Optional[Path] = None,
) -> None:
    write_event(
        "ORDER_REJECTED",
        account_id=account_id, path=path,
        strategy=strategy, symbol=symbol, action=action, qty=qty,
        reason=reason, error=error,
    )


def record_order_stale(
    *, account_id: str, strategy: str, symbol: str, action: str,
    order_id: str, age_days: int, path: Optional[Path] = None,
) -> None:
    """已送出但超過 N 天仍未成交/未結 → 告警事件（每個 order_id 只記一次）。"""
    write_event(
        "ORDER_STALE",
        account_id=account_id, path=path,
        strategy=strategy, symbol=symbol, action=action,
        order_id=order_id, age_days=age_days,
    )


def record_summary(
    *, account_id: str, strategy: str, today: str,
    continuing: int, exit_n: int, new_entrant: int,
    weight_adjust: int, cash_deploy: int,
    sells: int, buys: int,
    minimum_swap_check: bool, minimum_swap_note: str = "",
    path: Optional[Path] = None,
) -> None:
    """收尾統計。minimum_swap_check 證明「不是全賣全買」。"""
    write_event(
        "REBALANCE_SUMMARY",
        account_id=account_id, path=path,
        strategy=strategy, today=today,
        continuing=continuing, exit=exit_n, new_entrant=new_entrant,
        weight_adjust=weight_adjust, cash_deploy=cash_deploy,
        sells=sells, buys=buys,
        minimum_swap_check=minimum_swap_check,
        minimum_swap_note=minimum_swap_note,
    )
