"""scripts/check_email_sent.py — 每日報告寄信看門狗檢查。

讀 data/email_send_log.jsonl，判斷「最近一段時間內是否有成功寄出、且無失敗」。
- 健康（退出 0）：近 N 小時內 ≥1 筆 status==ok 且 0 筆 status==fail。
- 異常（退出 1）：完全沒有近期成功紀錄（排程被跳過/未跑），或有失敗紀錄。

供 .github/workflows/email_watchdog.yml 使用：異常時自動補寄 + 開 issue。

用法：
    python scripts/check_email_sent.py [--hours 12] [--path data/email_send_log.jsonl]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import email_log


def _recent(entries, hours: float):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for e in entries:
        try:
            t = datetime.fromisoformat(e.get("ts", ""))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= cutoff:
            out.append(e)
    return out


def check(path, hours: float = 12.0):
    """回傳 (healthy: bool, oks: list, fails: list, recent: list)。"""
    recent = _recent(email_log.read(path), hours)
    oks = [e for e in recent if e.get("status") == "ok"]
    fails = [e for e in recent if e.get("status") == "fail"]
    healthy = bool(oks) and not fails
    return healthy, oks, fails, recent


def main() -> int:
    ap = argparse.ArgumentParser(description="每日報告寄信看門狗")
    ap.add_argument("--hours", type=float, default=12.0)
    ap.add_argument("--path", default=str(email_log.DEFAULT_PATH))
    args = ap.parse_args()

    healthy, oks, fails, recent = check(args.path, args.hours)
    print(f"近 {args.hours:g}h 寄信：成功 {len(oks)}、失敗 {len(fails)}、總 {len(recent)} 筆")
    if fails:
        for e in fails:
            print(f"  ❌ #{e.get('account')} {e.get('date')} {e.get('error','')[:80]}")
    if healthy:
        print("✅ 健康：近期有成功寄出且無失敗")
        return 0
    print("⚠️ 異常：近期沒有成功寄出，或有失敗 → 需補寄/通知")
    return 1


if __name__ == "__main__":
    sys.exit(main())
