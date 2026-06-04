"""brokers/from_env.py — 從 run_account.py 注入的環境變數建構 BrokerClient。

對應 run_account.py 注入的 env vars：
    ACC{id}_BROKER       (預設 "alpaca")
    ACC{id}_ENVIRONMENT  (預設 "paper")
    ACC{id}_API_KEY      (broker spec required_env 內 resolved 的值)
    ACC{id}_API_SECRET   (同上)

runner.py 可呼叫：

    from brokers.from_env import build_client_for_account
    client = build_client_for_account(account_id="1")
    nav = client.get_account_balance().nav
"""
from __future__ import annotations

import os
from typing import Optional

from .base import BrokerClient
from .registry import build_client


def build_client_for_account(account_id: str) -> BrokerClient:
    """從 ACC{id}_* env vars 自動建 client。

    account_id 通常是 accounts.json 內的 'id' 欄位（如 "1" / "2"）。
    若 ACC{id}_BROKER 沒設則預設 alpaca / paper（向下相容）。
    """
    prefix = f"ACC{account_id}"
    broker_id   = os.environ.get(f"{prefix}_BROKER",      "alpaca")
    environment = os.environ.get(f"{prefix}_ENVIRONMENT", "paper")
    return build_client(broker_id=broker_id,
                        environment=environment,
                        secret_prefix=prefix)


def build_client_from_prefix(
    secret_prefix: str,
    broker_id: str = "alpaca",
    environment: str = "paper",
) -> BrokerClient:
    """另一種使用方式：明確指定 prefix。給不依 accounts.json 的程式用。"""
    return build_client(broker_id=broker_id,
                        environment=environment,
                        secret_prefix=secret_prefix)
