"""
engine/accounts.py — accounts.json 管理

每個帳戶唯一對應一種策略（1 帳戶 1 策略）。
accounts.json 是帳戶↔策略對應的全域真相來源。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

from engine.paths import workdir

# accounts.json 是使用者設定 → workdir()（預設同 repo root；TR_WORKDIR 可外置）
_ACCOUNTS_PATH = workdir() / "accounts.json"


@dataclass
class Account:
    id: str
    strategy: str
    label: str
    # ── ba4632c 起新增的選填欄位（向下相容舊 accounts.json）─────────────────
    enabled: bool = True
    alpaca_secret_prefix: Optional[str] = None
    data_dir: Optional[str] = None
    runner_sub_id: Optional[str] = None
    # 帳戶生命週期：歷經的策略段（縫合 NAV 歷史用）。每段 {strategy,label,data_dir}
    strategy_history: Optional[list] = None


# 已知欄位集合：超出此集合的 key 會被靜默忽略（保留向前相容性）
_KNOWN_FIELDS = {"id", "strategy", "label",
                 "enabled", "alpaca_secret_prefix", "data_dir", "runner_sub_id",
                 "strategy_history"}


# ── 讀取 ──────────────────────────────────────────────────────────────────────

def load_accounts(path: Path = _ACCOUNTS_PATH) -> List[Account]:
    """讀取 accounts.json，回傳 Account 清單。

    對未來新增的欄位採取「白名單過濾」策略：未知欄位被忽略而非報錯，
    避免下游 dataclass 沒同步更新時整個生產 workflow 死掉。
    """
    if not path.exists():
        raise FileNotFoundError(f"accounts.json 不存在：{path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    accounts: List[Account] = []
    for a in raw["accounts"]:
        filtered = {k: v for k, v in a.items() if k in _KNOWN_FIELDS}
        unknown = set(a.keys()) - _KNOWN_FIELDS
        if unknown:
            logger.debug("帳戶 #%s 含未知欄位（已忽略）：%s", a.get("id", "?"), sorted(unknown))
        accounts.append(Account(**filtered))
    _validate(accounts)
    return accounts


def get_account(account_id: str, path: Path = _ACCOUNTS_PATH) -> Account:
    """取得指定 ID 的帳戶；不存在則 raise KeyError。"""
    accounts = load_accounts(path)
    for a in accounts:
        if a.id == account_id:
            return a
    raise KeyError(f"帳戶 ID 不存在：{account_id}")


def get_same_strategy_accounts(strategy_id: str, path: Path = _ACCOUNTS_PATH) -> List[Account]:
    """取得使用相同策略的所有帳戶（包含 strategy_id 自己的帳戶）。"""
    accounts = load_accounts(path)
    return [a for a in accounts if a.strategy == strategy_id]


def list_strategy_ids(path: Path = _ACCOUNTS_PATH) -> List[str]:
    """列出所有已知策略 ID（不重複）。"""
    accounts = load_accounts(path)
    seen = []
    for a in accounts:
        if a.strategy not in seen:
            seen.append(a.strategy)
    return seen


# ── 寫入 ──────────────────────────────────────────────────────────────────────

def update_account_strategy(
    account_id: str,
    new_strategy: str,
    path: Path = _ACCOUNTS_PATH,
) -> None:
    """
    更新帳戶的策略（策略切換用）。
    直接修改 accounts.json 並存檔。
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    found = False
    for a in raw["accounts"]:
        if a["id"] == account_id:
            a["strategy"] = new_strategy
            found = True
            break
    if not found:
        raise KeyError(f"帳戶 ID 不存在：{account_id}")
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("帳戶 #%s 策略已更新為 %s", account_id, new_strategy)


# ── 驗證 ──────────────────────────────────────────────────────────────────────

def _validate(accounts: List[Account]) -> None:
    """驗證 accounts 清單的完整性。"""
    # 帳戶 ID 唯一
    ids = [a.id for a in accounts]
    if len(ids) != len(set(ids)):
        duplicates = [i for i in ids if ids.count(i) > 1]
        raise ValueError(f"accounts.json 中有重複的帳戶 ID：{set(duplicates)}")

    # ID 必須是字串（非空）
    for a in accounts:
        if not isinstance(a.id, str) or not a.id.strip():
            raise ValueError(f"帳戶 ID 必須是非空字串：{a.id!r}")
        if not isinstance(a.strategy, str) or not a.strategy.strip():
            raise ValueError(f"帳戶 {a.id} 的 strategy 必須是非空字串")
