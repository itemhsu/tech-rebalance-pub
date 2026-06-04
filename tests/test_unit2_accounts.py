"""
tests/test_unit2_accounts.py — Unit 2: accounts.json 管理
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

import sys
sys.path.insert(0, str(ROOT))
from engine.accounts import (
    Account, load_accounts, get_account,
    get_same_strategy_accounts, update_account_strategy,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_accounts(tmp_path: Path, accounts: list[dict]) -> Path:
    p = tmp_path / "accounts.json"
    p.write_text(json.dumps({"accounts": accounts}, ensure_ascii=False, indent=2))
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  1. 基本讀取
# ══════════════════════════════════════════════════════════════════════════════

def test_each_account_id_unique():
    """正式 accounts.json 中帳戶 ID 不重複。"""
    accounts = load_accounts()
    ids = [a.id for a in accounts]
    assert len(ids) == len(set(ids))


def test_strategy_values_are_non_empty_strings():
    """每個帳戶的 strategy 欄位是非空字串。"""
    accounts = load_accounts()
    for a in accounts:
        assert isinstance(a.strategy, str) and a.strategy.strip()


def test_load_accounts_returns_account_objects():
    accounts = load_accounts()
    assert len(accounts) >= 1
    assert all(isinstance(a, Account) for a in accounts)


# ══════════════════════════════════════════════════════════════════════════════
#  2. get_same_strategy_accounts
# ══════════════════════════════════════════════════════════════════════════════

def test_get_same_strategy_accounts_excludes_other_strategies(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10",  "label": "帳戶1"},
        {"id": "2", "strategy": "top10",  "label": "帳戶2"},
        {"id": "3", "strategy": "d2p2t6", "label": "帳戶3"},
    ])
    result = get_same_strategy_accounts("top10", path)
    assert all(a.strategy == "top10" for a in result)
    ids = [a.id for a in result]
    assert "3" not in ids


def test_get_same_strategy_accounts_includes_self(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10",  "label": "帳戶1"},
        {"id": "2", "strategy": "d2p2t6", "label": "帳戶2"},
    ])
    result = get_same_strategy_accounts("top10", path)
    ids = [a.id for a in result]
    assert "1" in ids


def test_get_same_strategy_accounts_unknown_strategy_returns_empty(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10", "label": "帳戶1"},
    ])
    result = get_same_strategy_accounts("nonexistent", path)
    assert result == []


# ══════════════════════════════════════════════════════════════════════════════
#  3. update_account_strategy
# ══════════════════════════════════════════════════════════════════════════════

def test_update_account_strategy_writes_to_file(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10",  "label": "帳戶1"},
    ])
    update_account_strategy("1", "d2p2t6", path)
    raw = json.loads(path.read_text())
    assert raw["accounts"][0]["strategy"] == "d2p2t6"


def test_update_account_strategy_nonexistent_raises(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10", "label": "帳戶1"},
    ])
    with pytest.raises(KeyError):
        update_account_strategy("99", "d2p2t6", path)


# ══════════════════════════════════════════════════════════════════════════════
#  4. 錯誤處理
# ══════════════════════════════════════════════════════════════════════════════

def test_load_accounts_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_accounts(Path("/nonexistent/accounts.json"))


def test_duplicate_account_id_raises(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10",  "label": "帳戶1"},
        {"id": "1", "strategy": "d2p2t6", "label": "帳戶1dup"},
    ])
    with pytest.raises(ValueError, match="重複"):
        load_accounts(path)


def test_get_account_returns_correct_account(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10",  "label": "帳戶1"},
        {"id": "2", "strategy": "d2p2t6", "label": "帳戶2"},
    ])
    a = get_account("2", path)
    assert a.strategy == "d2p2t6"


def test_get_account_nonexistent_raises(tmp_path):
    path = _write_accounts(tmp_path, [
        {"id": "1", "strategy": "top10", "label": "帳戶1"},
    ])
    with pytest.raises(KeyError):
        get_account("99", path)
