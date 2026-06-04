"""Phase 3 測試 — brokers.from_env helper + accounts.json 向下相容。

對應計劃書 E-09 / E-10（不打網路版本）。
"""
import json
from pathlib import Path

import pytest

from brokers.base import BrokerClient
from brokers.from_env import build_client_for_account, build_client_from_prefix


# ── E-09 等價 ─────────────────────────────────────────────────────────
def test_build_client_for_account_defaults_to_alpaca(monkeypatch):
    """ACC{id}_BROKER 沒設 → 預設 'alpaca'（向下相容）。"""
    monkeypatch.delenv("ACC1_BROKER", raising=False)
    monkeypatch.delenv("ACC1_ENVIRONMENT", raising=False)
    monkeypatch.setenv("ACC1_API_KEY", "PK_X")
    monkeypatch.setenv("ACC1_API_SECRET", "SECRET_X")

    client = build_client_for_account("1")
    assert isinstance(client, BrokerClient)
    assert client.broker_id == "alpaca"
    assert client.environment == "paper"


def test_build_client_for_account_explicit_broker(monkeypatch):
    """ACC{id}_BROKER='alpaca' + ACC{id}_ENVIRONMENT='live' → 拿到對應 spec。"""
    monkeypatch.setenv("ACC2_BROKER", "alpaca")
    monkeypatch.setenv("ACC2_ENVIRONMENT", "live")
    monkeypatch.setenv("ACC2_API_KEY", "PK_LIVE")
    monkeypatch.setenv("ACC2_API_SECRET", "SECRET_LIVE")

    client = build_client_for_account("2")
    assert client.environment == "live"
    assert client.env_config["base_url"] == "https://api.alpaca.markets"


def test_build_client_for_account_missing_key(monkeypatch):
    """缺 ACC{id}_API_KEY 時 raise，訊息含明確變數名。"""
    from brokers.base import BrokerAuthError
    monkeypatch.delenv("ACC99_API_KEY", raising=False)
    monkeypatch.delenv("ACC99_API_SECRET", raising=False)
    with pytest.raises(BrokerAuthError, match="ACC99_API_KEY"):
        build_client_for_account("99")


def test_build_client_from_prefix(monkeypatch):
    """build_client_from_prefix 提供不依 accounts.json 的用法。"""
    monkeypatch.setenv("MYACC_API_KEY", "PK")
    monkeypatch.setenv("MYACC_API_SECRET", "SECRET")
    client = build_client_from_prefix("MYACC")
    assert client.broker_id == "alpaca"
    assert client.environment == "paper"


# ── accounts.json 結構驗證 ──────────────────────────────────────────────
def test_accounts_json_has_new_broker_fields():
    """accounts.json 升級後每個帳戶都有 broker + environment + secret_prefix。"""
    p = Path(__file__).resolve().parent.parent.parent / "accounts.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for acc in data["accounts"]:
        assert "broker" in acc, f"帳戶 #{acc['id']} 缺 broker"
        assert "environment" in acc, f"帳戶 #{acc['id']} 缺 environment"
        assert "secret_prefix" in acc, f"帳戶 #{acc['id']} 缺 secret_prefix"
        # 向下相容：舊欄位 alpaca_secret_prefix 仍存（未移除）
        assert acc.get("alpaca_secret_prefix") == acc["secret_prefix"], \
            f"帳戶 #{acc['id']} 新舊欄位值不一致"


def test_accounts_json_default_broker_alpaca():
    """目前所有帳戶都是 alpaca paper（保留 sanity check）。"""
    p = Path(__file__).resolve().parent.parent.parent / "accounts.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for acc in data["accounts"]:
        assert acc["broker"] == "alpaca"
        assert acc["environment"] in ("paper", "live")
