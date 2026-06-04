"""engine/email_log.py — 每日寄信結果結構化日誌（避免寄信失敗無聲無息）。

每寄一個帳戶就 append 一筆 JSON 到 data/email_send_log.jsonl：
    {ts, account, date, subject, status, error}
    status ∈ {"ok","fail","skip"}（skip＝該帳戶當日無資料）

純函式、可單測；scripts/check_email_sent.py 與 GUI 日誌都讀這個檔。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set

from engine.paths import workdir

# email 寄送日誌是使用者資料 → workdir()（預設同 repo root；TR_WORKDIR 可外置）
DEFAULT_PATH = workdir() / "data" / "email_send_log.jsonl"


def append(path, account_id: str, report_date: str, subject: str,
           status: str, error: str = "") -> dict:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "account": str(account_id),
        "date": report_date or "",
        "subject": (subject or "")[:200],
        "status": status,
        "error": (error or "")[:300],
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read(path) -> List[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out: List[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def accounts_sent_on(path, report_date: str) -> Set[str]:
    """回傳在指定報告日期成功寄出（status==ok）的帳戶集合。"""
    return {e["account"] for e in read(path)
            if e.get("date") == report_date and e.get("status") == "ok"}


def latest_date(path) -> Optional[str]:
    """日誌中最新的報告日期（用於未指定日期時的檢查基準）。"""
    dates = [e.get("date") for e in read(path) if e.get("date")]
    return max(dates) if dates else None
