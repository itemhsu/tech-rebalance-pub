"""run_account 券商感知金鑰解析 + env 注入（Tradier 支援）。純單元、不打網路。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run_account as ra


# ── _source_map：依券商給對的 GitHub-Secret 名稱 ─────────────────────────
def test_source_map_alpaca():
    assert ra._source_map("ACC1", "alpaca") == {
        "API_KEY": "ACC1_ALPACA_KEY",
        "API_SECRET": "ACC1_ALPACA_SECRET",
    }


def test_source_map_tradier():
    assert ra._source_map("ACC5", "tradier") == {
        "API_KEY": "ACC5_API_KEY",
        "ACCOUNT_ID": "ACC5_ACCOUNT_ID",
    }


# ── _resolve_credentials：讀環境變數 ─────────────────────────────────────
def test_resolve_alpaca(monkeypatch):
    monkeypatch.setenv("ACC1_ALPACA_KEY", "PKxxx")
    monkeypatch.setenv("ACC1_ALPACA_SECRET", "secret")
    creds, _, missing = ra._resolve_credentials("ACC1", "alpaca")
    assert creds == {"API_KEY": "PKxxx", "API_SECRET": "secret"}
    assert missing == []


def test_resolve_alpaca_missing(monkeypatch):
    monkeypatch.delenv("ACC1_ALPACA_KEY", raising=False)
    monkeypatch.delenv("ACC1_ALPACA_SECRET", raising=False)
    creds, _, missing = ra._resolve_credentials("ACC1", "alpaca")
    assert "ACC1_ALPACA_KEY" in missing and "ACC1_ALPACA_SECRET" in missing


def test_resolve_tradier(monkeypatch):
    monkeypatch.setenv("ACC5_API_KEY", "tok")
    monkeypatch.setenv("ACC5_ACCOUNT_ID", "VA123")
    creds, _, missing = ra._resolve_credentials("ACC5", "tradier")
    assert creds == {"API_KEY": "tok", "ACCOUNT_ID": "VA123"}
    assert missing == []


# ── _build_env：注入 registry 期望的 ACC{id}_<PLAIN> ─────────────────────
def test_build_env_alpaca():
    env = ra._build_env({"id": "1"}, "alpaca", "paper",
                        {"API_KEY": "PK", "API_SECRET": "s"}, False, "")
    assert env["ACC1_BROKER"] == "alpaca"
    assert env["ACC1_ENVIRONMENT"] == "paper"
    assert env["ACC1_API_KEY"] == "PK"
    assert env["ACC1_API_SECRET"] == "s"


def test_build_env_tradier_injects_account_id():
    env = ra._build_env({"id": "5"}, "tradier", "sandbox",
                        {"API_KEY": "tok", "ACCOUNT_ID": "VA123"}, False, "")
    assert env["ACC5_BROKER"] == "tradier"
    assert env["ACC5_ENVIRONMENT"] == "sandbox"
    assert env["ACC5_API_KEY"] == "tok"
    assert env["ACC5_ACCOUNT_ID"] == "VA123"   # registry required_env 需要
