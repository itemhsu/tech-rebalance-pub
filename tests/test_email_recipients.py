"""驗證 _resolve_recipients + SMTP 寄送邏輯。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from send_email_from_data import _resolve_recipients, DEFAULT_CC


def test_account_with_explicit_recipients(tmp_path, monkeypatch):
    """帳戶 email_recipients：無 EMAIL_CC 時不自動補 CC（不硬寫個人信箱）。"""
    # 寫一個假的 accounts.json
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({
        "accounts": [
            {"id": "1", "email_recipients": ["trader@example.com"]},
        ]
    }))
    monkeypatch.setattr("send_email_from_data.ROOT", tmp_path)
    result = _resolve_recipients("1")
    assert result == ["trader@example.com"]  # 無 EMAIL_CC → 不自動補 CC


def test_account_recipient_same_as_default(tmp_path, monkeypatch):
    """primary 已是 DEFAULT_CC → 不重複加入。"""
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({
        "accounts": [
            {"id": "2", "email_recipients": [DEFAULT_CC]},
        ]
    }))
    monkeypatch.setattr("send_email_from_data.ROOT", tmp_path)
    result = _resolve_recipients("2")
    assert result == [DEFAULT_CC]


def test_account_two_explicit_recipients(tmp_path, monkeypatch):
    """帳戶明確設兩個 → 用這兩個（不再多補）。"""
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({
        "accounts": [
            {"id": "3", "email_recipients": ["a@example.com", "b@example.com"]},
        ]
    }))
    monkeypatch.setattr("send_email_from_data.ROOT", tmp_path)
    result = _resolve_recipients("3")
    assert result == ["a@example.com", "b@example.com"]


def test_account_no_field_fallback_env(tmp_path, monkeypatch):
    """帳戶沒 email_recipients → fallback EMAIL_RECIPIENT env var。"""
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({
        "accounts": [
            {"id": "4"},
        ]
    }))
    monkeypatch.setattr("send_email_from_data.ROOT", tmp_path)
    monkeypatch.setenv("EMAIL_RECIPIENT", "fallback@example.com")
    result = _resolve_recipients("4")
    assert result == ["fallback@example.com"]


def test_account_not_found(tmp_path, monkeypatch):
    """帳戶不在 accounts.json → fallback EMAIL_RECIPIENT。"""
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({"accounts": []}))
    monkeypatch.setattr("send_email_from_data.ROOT", tmp_path)
    monkeypatch.setenv("EMAIL_RECIPIENT", "x@example.com")
    result = _resolve_recipients("99")
    assert result == ["x@example.com"]


def test_account_no_fallback_returns_empty(tmp_path, monkeypatch):
    """都沒設 → 回空 list（呼叫者要處理）。"""
    fake = tmp_path / "accounts.json"
    fake.write_text(json.dumps({"accounts": []}))
    monkeypatch.setattr("send_email_from_data.ROOT", tmp_path)
    monkeypatch.delenv("EMAIL_RECIPIENT", raising=False)
    result = _resolve_recipients("1")
    assert result == []


# ── SMTP 寄送 mock 測試（不真連 Gmail）─────────────────────────────────
def test_smtp_send_calls_correct_apis(monkeypatch):
    """_send_via_smtp 正確呼叫 smtplib（用 mock 不真連）。"""
    from send_email_from_data import _send_via_smtp

    calls = {"login": None, "sendmail": None}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): self.host = host; self.port = port
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ehlo(self): pass
        def starttls(self): pass
        def login(self, u, p): calls["login"] = (u, p)
        def sendmail(self, sender, recipients, msg):
            calls["sendmail"] = (sender, list(recipients), len(msg))

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    ok = _send_via_smtp(
        subject="Test",
        html_body="<p>hello</p>",
        recipients=["a@example.com", "b@example.com"],
        sender="sender@example.com",
        password="app_password",
    )
    assert ok
    assert calls["login"] == ("sender@example.com", "app_password")
    sender, rs, _ = calls["sendmail"]
    assert sender == "sender@example.com"
    assert rs == ["a@example.com", "b@example.com"]


def test_smtp_dedupe_recipients(monkeypatch):
    """recipients 含重複 → 去重後送。"""
    from send_email_from_data import _send_via_smtp

    captured = []
    class FakeSMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ehlo(self): pass
        def starttls(self): pass
        def login(self, *a): pass
        def sendmail(self, s, r, msg): captured.append(list(r))

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    _send_via_smtp("S", "<p>x</p>",
                   ["a@example.com", "a@example.com", "b@example.com"],
                   "s@example.com", "pw")
    assert captured[0] == ["a@example.com", "b@example.com"]


def test_smtp_auth_failure_returns_false(monkeypatch):
    """Gmail 拒絕登入 → 回 False（不 raise）。"""
    from send_email_from_data import _send_via_smtp
    import smtplib

    class FakeSMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ehlo(self): pass
        def starttls(self): pass
        def login(self, *a):
            raise smtplib.SMTPAuthenticationError(535, b"BadCredentials")
        def sendmail(self, *a): pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    ok = _send_via_smtp("S", "<p>x</p>", ["a@example.com"], "s@example.com", "bad")
    assert ok is False
