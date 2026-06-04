"""寄信日誌 + 看門狗檢查（避免每日報告寄信失敗無聲無息）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import email_log
import importlib.util

# 動態載入 scripts/check_email_sent.py（非套件）
_spec = importlib.util.spec_from_file_location(
    "check_email_sent", ROOT / "scripts" / "check_email_sent.py")
ces = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ces)


def _ts(hours_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


# ── email_log 基本 ───────────────────────────────────────────────────────
def test_append_read_roundtrip(tmp_path):
    p = tmp_path / "email_send_log.jsonl"
    email_log.append(p, "1", "2026-06-02", "[TOP10] ...", "ok")
    email_log.append(p, "4", "", "", "skip", "data.json 不存在")
    rows = email_log.read(p)
    assert [r["status"] for r in rows] == ["ok", "skip"]
    assert rows[0]["account"] == "1" and rows[0]["date"] == "2026-06-02"


def test_accounts_sent_on(tmp_path):
    p = tmp_path / "log.jsonl"
    email_log.append(p, "1", "2026-06-02", "s", "ok")
    email_log.append(p, "2", "2026-06-02", "s", "fail", "SMTP")
    email_log.append(p, "3", "2026-06-01", "s", "ok")
    assert email_log.accounts_sent_on(p, "2026-06-02") == {"1"}
    assert email_log.latest_date(p) == "2026-06-02"


# ── check_email_sent 看門狗 ───────────────────────────────────────────────
def test_watchdog_healthy(tmp_path):
    p = tmp_path / "log.jsonl"
    _write(p, [{"ts": _ts(1), "account": "1", "date": "d", "status": "ok"}])
    healthy, oks, fails, _ = ces.check(p, hours=12)
    assert healthy and len(oks) == 1 and not fails


def test_watchdog_alert_when_no_recent_send(tmp_path):
    """排程被跳過 → 近期完全沒有寄信紀錄 → 異常（這正是 6/02 的情形）。"""
    p = tmp_path / "log.jsonl"
    _write(p, [{"ts": _ts(40), "account": "1", "date": "d", "status": "ok"}])  # 40h 前
    healthy, oks, fails, _ = ces.check(p, hours=12)
    assert not healthy and not oks


def test_watchdog_alert_on_recent_fail(tmp_path):
    """近期有失敗（如 SendGrid 403）→ 異常。"""
    p = tmp_path / "log.jsonl"
    _write(p, [
        {"ts": _ts(1), "account": "1", "date": "d", "status": "ok"},
        {"ts": _ts(1), "account": "2", "date": "d", "status": "fail", "error": "403"},
    ])
    healthy, oks, fails, _ = ces.check(p, hours=12)
    assert not healthy and len(fails) == 1


def test_watchdog_empty_log_is_alert(tmp_path):
    healthy, *_ = ces.check(tmp_path / "nope.jsonl", hours=12)
    assert not healthy


# ── send_for_account 無資料 → 記 skip、不算失敗 ──────────────────────────
def test_send_for_account_logs_skip(tmp_path, monkeypatch):
    log = tmp_path / "email_send_log.jsonl"
    monkeypatch.setenv("EMAIL_LOG_PATH", str(log))
    import importlib
    sefd = importlib.import_module("scripts.send_email_from_data") \
        if "scripts.send_email_from_data" in sys.modules else None
    if sefd is None:
        spec = importlib.util.spec_from_file_location(
            "send_email_from_data", ROOT / "scripts" / "send_email_from_data.py")
        sefd = importlib.util.module_from_spec(spec); spec.loader.exec_module(sefd)
    status = sefd.send_for_account("9", tmp_path / "mvp_data", dry_run=False)
    assert status == "skip"
    rows = email_log.read(log)
    assert rows and rows[-1]["status"] == "skip" and rows[-1]["account"] == "9"


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
