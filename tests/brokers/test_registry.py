"""Phase 1 Registry 單元測試 — 對應計劃書 U-06 ~ U-12 + 部分安全測試。
"""
import os

import pytest

from brokers.base import BrokerAuthError, BrokerClient
from brokers.registry import (
    load_broker_spec, resolve_env_vars, build_client,
)


# ── U-06 ───────────────────────────────────────────────────────────────
def test_load_broker_spec_alpaca():
    """load_broker_spec('alpaca') 回 dict 且 id='alpaca'。"""
    spec = load_broker_spec("alpaca")
    assert isinstance(spec, dict)
    assert spec["id"] == "alpaca"
    assert "auth" in spec
    assert "environments" in spec


# ── U-07 ───────────────────────────────────────────────────────────────
def test_load_broker_spec_unknown():
    """未知 broker → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError, match="不存在"):
        load_broker_spec("not_a_real_broker")


# ── U-08 ───────────────────────────────────────────────────────────────
def test_resolve_env_vars_ok(monkeypatch):
    """正常解析 {PREFIX}_API_KEY。"""
    monkeypatch.setenv("ACC1_API_KEY", "PK_TEST")
    monkeypatch.setenv("ACC1_API_SECRET", "SECRET_TEST")
    spec = {
        "id": "alpaca",
        "auth": {
            "method": "api_key_secret",
            "required_env": ["{PREFIX}_API_KEY", "{PREFIX}_API_SECRET"],
        },
    }
    env = resolve_env_vars(spec, secret_prefix="ACC1", environment="paper")
    assert env["API_KEY"] == "PK_TEST"
    assert env["API_SECRET"] == "SECRET_TEST"


# ── U-09 ───────────────────────────────────────────────────────────────
def test_resolve_env_vars_missing(monkeypatch):
    """缺環境變數 → BrokerAuthError 且訊息含缺失 key。"""
    monkeypatch.delenv("ACC999_API_KEY", raising=False)
    monkeypatch.delenv("ACC999_API_SECRET", raising=False)
    spec = {
        "id": "alpaca",
        "auth": {
            "method": "api_key_secret",
            "required_env": ["{PREFIX}_API_KEY", "{PREFIX}_API_SECRET"],
        },
    }
    with pytest.raises(BrokerAuthError, match="ACC999_API_KEY"):
        resolve_env_vars(spec, secret_prefix="ACC999", environment="paper")


def test_resolve_env_vars_live_extra(monkeypatch):
    """live 環境額外讀 required_env_live 列出的變數。"""
    monkeypatch.setenv("ACC1_API_KEY", "k")
    monkeypatch.setenv("ACC1_API_SECRET", "s")
    monkeypatch.setenv("ACC1_CA_PATH", "/tmp/ca.pfx")

    spec = {
        "id": "shioaji",
        "auth": {
            "method": "sdk_login",
            "required_env":      ["{PREFIX}_API_KEY", "{PREFIX}_API_SECRET"],
            "required_env_live": ["{PREFIX}_CA_PATH"],
        },
    }
    # paper 不需要 CA_PATH
    env_paper = resolve_env_vars(spec, "ACC1", "paper")
    assert "CA_PATH" not in env_paper
    # live 必須含 CA_PATH
    env_live = resolve_env_vars(spec, "ACC1", "live")
    assert env_live["CA_PATH"] == "/tmp/ca.pfx"


# ── U-10 ───────────────────────────────────────────────────────────────
def test_build_client_returns_correct_class(monkeypatch):
    """spec id=alpaca（Phase B 後無 client_class）→ 拿到通用 RestBrokerClient。"""
    monkeypatch.setenv("ACC1_API_KEY", "PK_TEST")
    monkeypatch.setenv("ACC1_API_SECRET", "SECRET_TEST")
    client = build_client(broker_id="alpaca", environment="paper", secret_prefix="ACC1")
    assert isinstance(client, BrokerClient)
    assert client.__class__.__name__ == "RestBrokerClient"
    assert client.broker_id == "alpaca"


# ── U-11 ───────────────────────────────────────────────────────────────
def test_environment_selection(monkeypatch):
    """env='paper' → base_url 是 paper-api.alpaca.markets。"""
    monkeypatch.setenv("ACC1_API_KEY", "k")
    monkeypatch.setenv("ACC1_API_SECRET", "s")
    client = build_client(broker_id="alpaca", environment="paper", secret_prefix="ACC1")
    assert client.env_config["base_url"] == "https://paper-api.alpaca.markets"

    client_live = build_client(broker_id="alpaca", environment="live", secret_prefix="ACC1")
    assert client_live.env_config["base_url"] == "https://api.alpaca.markets"


# ── U-12 ───────────────────────────────────────────────────────────────
def test_environment_invalid(monkeypatch):
    """env 不在 spec.environments → ValueError。"""
    monkeypatch.setenv("ACC1_API_KEY", "k")
    monkeypatch.setenv("ACC1_API_SECRET", "s")
    with pytest.raises(ValueError, match="dev"):
        build_client(broker_id="alpaca", environment="dev", secret_prefix="ACC1")
