"""Phase 1 安全測試 — 對應計劃書 SEC-01 ~ SEC-06。

確保密鑰不外洩、URL 不帶 secret、log/repr/traceback 過濾正確。
"""
import json as _json
import logging
import re
from pathlib import Path

import pytest

responses = pytest.importorskip("responses")

from brokers.alpaca_client import AlpacaClient
from brokers.base import BrokerError
from brokers.registry import load_broker_spec, BROKERS_DIR


# 共用：建一個 client，用「容易辨識」的 secret 字串
SECRET_SENTINEL = "SUPER_SECRET_xyz_NEVER_LOG_ME"
KEY_SENTINEL    = "PK_TEST_KEY_xyz"


def _client_with_sentinel():
    spec = load_broker_spec("alpaca")
    env = {"API_KEY": KEY_SENTINEL, "API_SECRET": SECRET_SENTINEL}
    return AlpacaClient(spec=spec, env=env, environment="paper")


# ── SEC-01 ─────────────────────────────────────────────────────────────
def test_secrets_never_in_logs(caplog):
    """所有 log 內容不可包含 API_SECRET 全文。"""
    @responses.activate
    def _inner():
        responses.add(responses.GET,
                      "https://paper-api.alpaca.markets/v2/account",
                      json={"portfolio_value": "100", "cash": "10"}, status=200)
        with caplog.at_level(logging.DEBUG):
            c = _client_with_sentinel()
            c.get_account_balance()
        for rec in caplog.records:
            full = rec.getMessage() + " " + str(rec.args or "")
            assert SECRET_SENTINEL not in full, f"log 洩露 secret：{rec.message}"
            assert KEY_SENTINEL    not in full, f"log 洩露 api_key：{rec.message}"
    _inner()


# ── SEC-02 ─────────────────────────────────────────────────────────────
def test_repr_masks_secrets():
    """client.__repr__() 不可印出 secret 全文。"""
    c = _client_with_sentinel()
    r = repr(c)
    assert SECRET_SENTINEL not in r
    assert KEY_SENTINEL    not in r
    # 但應顯示 broker id 等基本資訊
    assert "alpaca" in r.lower()


# ── SEC-03 ─────────────────────────────────────────────────────────────
@responses.activate
def test_url_no_secret_in_query():
    """送出的 URL query string 不可含 secret（必須走 header）。"""
    responses.add(responses.GET,
                  "https://paper-api.alpaca.markets/v2/account",
                  json={"portfolio_value": "100"}, status=200)
    _client_with_sentinel().get_account_balance()

    # 檢查 responses 攔到的所有 request URL
    for call in responses.calls:
        assert SECRET_SENTINEL not in call.request.url
        assert KEY_SENTINEL    not in call.request.url
        # 但 header 內可有
        assert KEY_SENTINEL in str(call.request.headers)


# ── SEC-04 ─────────────────────────────────────────────────────────────
@responses.activate
def test_traceback_no_secret():
    """強制 raise exception，stack trace 內不能有 secret。"""
    responses.add(responses.GET,
                  "https://paper-api.alpaca.markets/v2/account",
                  json={"err": "bad"}, status=500)
    c = _client_with_sentinel()
    try:
        c.get_account_balance()
    except Exception as e:
        import traceback
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        assert SECRET_SENTINEL not in tb
        assert KEY_SENTINEL    not in tb


# ── SEC-05 ─────────────────────────────────────────────────────────────
def test_broker_json_no_sample_secret():
    """brokers/*.json 不可意外包含像 API key 的字串。

    啟發式：找開頭為 PK / SG / SK 後接 12+ 字元的字串。
    """
    pattern = re.compile(r"\b(PK|SG|SK)[A-Za-z0-9_]{12,}\b")
    for p in BROKERS_DIR.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        # template 字串如 "{api_key}" 不算
        if "{api_key}" in text or "{api_secret}" in text:
            text = re.sub(r"\{[a-z_]+\}", "", text)
        m = pattern.search(text)
        assert not m, f"{p.name} 疑似包含真實 API key：{m.group()}"


# ── SEC-06 ─────────────────────────────────────────────────────────────
def test_oauth_refresh_token_rotation_persistence(tmp_path, monkeypatch):
    """OAuth refresh token rotation 後正確更新（為未來 Tradier/TS 預備）。

    Phase 1 只先確認介面：可呼叫 gh secret set CLI 並傳新值。
    用 monkeypatch 攔截 subprocess.run，確認被正確呼叫。
    """
    import subprocess
    called = []
    def fake_run(*args, **kwargs):
        called.append(args)
        class R: returncode = 0
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)

    # 模擬一個 helper 函式（未來 OAuth client 會用）
    def update_github_secret(name: str, value: str) -> bool:
        result = subprocess.run(["gh", "secret", "set", name, "--body", value])
        return result.returncode == 0

    ok = update_github_secret("ACC1_REFRESH_TOKEN", "NEW_REFRESH_xxxxx")
    assert ok
    assert called, "subprocess.run 應該被呼叫"
    args = called[0][0]
    assert "secret" in args and "set" in args
    assert "ACC1_REFRESH_TOKEN" in args
    assert "NEW_REFRESH_xxxxx" in args
