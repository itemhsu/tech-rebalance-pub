"""brokers/registry.py — 載入 broker spec、建構 client 實例。

外部呼叫者只用兩個函式：
    spec   = load_broker_spec("alpaca")
    client = build_client(broker_id="alpaca", environment="paper",
                          secret_prefix="ACC1")
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Dict

from .base import BrokerClient, BrokerAuthError


BROKERS_DIR = Path(__file__).resolve().parent


# ════════════════════════════════════════════════════════════════════════
#  Spec 載入
# ════════════════════════════════════════════════════════════════════════

def load_broker_spec(broker_id: str) -> dict:
    """讀 brokers/{broker_id}.json，回傳 dict。"""
    path = BROKERS_DIR / f"{broker_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"broker spec 不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ════════════════════════════════════════════════════════════════════════
#  環境變數解析
# ════════════════════════════════════════════════════════════════════════

def resolve_env_vars(spec: dict, secret_prefix: str, environment: str) -> Dict[str, str]:
    """從環境變數讀取 spec.auth.required_env 列出的 key（套用 {PREFIX} 模板）。

    範例：
        spec.auth.required_env = ["{PREFIX}_API_KEY", "{PREFIX}_API_SECRET"]
        secret_prefix = "ACC1"
        → 讀 ACC1_API_KEY、ACC1_API_SECRET

    回傳的 dict key 是「移除 {PREFIX}_ 後」的名稱：
        {"API_KEY": "PK...", "API_SECRET": "abc..."}

    若任一必要變數缺，raise BrokerAuthError 含明確訊息。
    """
    auth = spec.get("auth", {}) or {}
    required = list(auth.get("required_env") or [])
    if environment in ("live", "prod") and auth.get("required_env_live"):
        required += list(auth["required_env_live"])

    resolved: Dict[str, str] = {}
    missing = []
    for tpl in required:
        env_name = tpl.replace("{PREFIX}", secret_prefix)
        value = os.environ.get(env_name)
        if not value:
            missing.append(env_name)
            continue
        # key 去掉 prefix_ 變成 "API_KEY" 等
        plain_key = env_name[len(secret_prefix) + 1:] if env_name.startswith(secret_prefix + "_") else env_name
        resolved[plain_key] = value

    if missing:
        raise BrokerAuthError(
            f"缺少必要環境變數：{missing}（broker={spec.get('id')}, "
            f"prefix={secret_prefix}, env={environment}）"
        )
    return resolved


# ════════════════════════════════════════════════════════════════════════
#  Client 動態載入
# ════════════════════════════════════════════════════════════════════════

def build_client(broker_id: str, environment: str, secret_prefix: str) -> BrokerClient:
    """根據 broker_id 載 spec、resolve env vars、動態 import client class、建實例。"""
    spec = load_broker_spec(broker_id)

    # 校驗 environment 在 spec 內（讓使用者看到清晰訊息）
    if environment not in spec.get("environments", {}):
        raise ValueError(
            f"environment {environment!r} 不在 broker {broker_id} 支援的環境內；"
            f"可選：{sorted(spec.get('environments', {}).keys())}"
        )

    env_resolved = resolve_env_vars(spec, secret_prefix, environment)

    # 動態 import client class（e.g. "brokers.alpaca_client.AlpacaClient"）
    # 缺省 → 用通用 RestBrokerClient（JSON-driven，broker-schema v2）
    class_path = spec.get("integration", {}).get("client_class") \
        or "brokers.rest_broker.RestBrokerClient"

    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(
            f"無法載入 {module_path}（broker={broker_id}）：{e}"
        ) from e
    cls = getattr(module, class_name, None)
    if cls is None:
        raise AttributeError(
            f"{module_path} 內找不到 class {class_name}（broker={broker_id}）"
        )
    if not issubclass(cls, BrokerClient):
        raise TypeError(
            f"{class_path} 不是 BrokerClient 的子類別"
        )

    return cls(spec=spec, env=env_resolved, environment=environment)
