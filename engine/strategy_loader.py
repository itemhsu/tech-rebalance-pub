"""
engine/strategy_loader.py — 載入並驗證 strategy.json

用法：
    from engine.strategy_loader import load_strategy, validate_strategy
    cfg = load_strategy("top10")          # 讀 strategies/top10.json
    validate_strategy(cfg)                 # 驗證通過或 raise ValidationError
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft7Validator, ValidationError

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_STRATEGIES_DIR = _ROOT / "strategies"
_SCHEMA_V1_PATH = _STRATEGIES_DIR / "strategy-schema-v1.json"
_SCHEMA_V3_PATH = _STRATEGIES_DIR / "strategy-schema-v3.json"

# Legacy alias
_SCHEMA_PATH = _SCHEMA_V1_PATH

# Cache schemas to avoid repeated file I/O
_schema_cache_v1: dict | None = None
_schema_cache_v3: dict | None = None


def _get_schema(version: str = "v1") -> dict:
    global _schema_cache_v1, _schema_cache_v3
    if version == "v3":
        if _schema_cache_v3 is None:
            _schema_cache_v3 = json.loads(_SCHEMA_V3_PATH.read_text(encoding="utf-8"))
        return _schema_cache_v3
    else:
        if _schema_cache_v1 is None:
            _schema_cache_v1 = json.loads(_SCHEMA_V1_PATH.read_text(encoding="utf-8"))
        return _schema_cache_v1


def load_strategy(strategy_id: str, strategies_dir: Path = _STRATEGIES_DIR) -> dict:
    """
    從 strategies/{strategy_id}.json 讀取策略定義。
    回傳 dict；若檔案不存在則 raise FileNotFoundError。
    """
    path = strategies_dir / f"{strategy_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"策略檔案不存在：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    logger.debug("已載入策略：%s v%s", strategy_id, data.get("version", "?"))
    return data


def is_v3_strategy(data: dict) -> bool:
    """判斷策略是否為 v3 schema（schema_version 以 '3' 開頭）。"""
    sv = str(data.get("schema_version", ""))
    return sv.startswith("3")


def is_v3_algorithmic(data: dict) -> bool:
    """v3 策略且包含 indicators（即有完整演算法層）。"""
    return is_v3_strategy(data) and bool(data.get("indicators"))


def validate_strategy(data: dict) -> None:
    """
    驗證策略 dict 符合對應版本的 schema。
    v3 → strategy-schema-v3.json；其餘 → strategy-schema-v1.json。
    成功：無回傳
    失敗：raise jsonschema.ValidationError
    """
    version = "v3" if is_v3_strategy(data) else "v1"
    schema = _get_schema(version)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise ValidationError(
            f"策略定義驗證失敗（schema {version}，{len(errors)} 個錯誤）：{errors[0].message}",
            path=errors[0].path,
        )

    # 額外跨欄位驗證（v1 宇宙一致性）
    if not is_v3_strategy(data):
        _validate_universe_rankings_consistency(data)


def _validate_universe_rankings_consistency(data: dict) -> None:
    """universe.type 與 dashboard.rankings.type 必須一致。"""
    uni_type = data.get("universe", {}).get("type")
    rank_type = data.get("dashboard", {}).get("rankings", {}).get("type")

    expected = {
        "single":  "market_cap_list",
        "grouped": "universe_groups",
    }
    if uni_type in expected and rank_type != expected[uni_type]:
        raise ValidationError(
            f"universe.type='{uni_type}' 時，"
            f"dashboard.rankings.type 必須是 '{expected[uni_type]}'，"
            f"實際是 '{rank_type}'"
        )


def load_and_validate(strategy_id: str, strategies_dir: Path = _STRATEGIES_DIR) -> dict:
    """便利函式：載入並驗證，回傳 dict。"""
    data = load_strategy(strategy_id, strategies_dir)
    validate_strategy(data)
    return data


# v3 專用便利函式
def load_and_validate_v3(strategy_id: str, strategies_dir: Path = _STRATEGIES_DIR) -> dict:
    """載入 v3 策略並以 v3 schema 驗證。若非 v3 則 raise ValueError。"""
    data = load_strategy(strategy_id, strategies_dir)
    if not is_v3_strategy(data):
        raise ValueError(
            f"策略 '{strategy_id}' 的 schema_version='{data.get('schema_version')}' "
            f"不是 v3 schema（需以 '3' 開頭）"
        )
    validate_strategy(data)
    return data
