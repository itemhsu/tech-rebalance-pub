"""
engine/data_validator.py — 驗證 data.json 符合 data-schema-v1.json
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from jsonschema import Draft7Validator, ValidationError

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_SCHEMA_PATH = _ROOT / "schemas" / "data-schema-v1.json"

_schema_cache: dict | None = None


def _get_schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema_cache


def validate_data_json(data: dict) -> None:
    """
    驗證 data dict 符合 data-schema-v1.json。
    成功：無回傳。
    失敗：raise jsonschema.ValidationError。
    """
    schema = _get_schema()
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise ValidationError(
            f"data.json 驗證失敗（{len(errors)} 個錯誤）：{errors[0].message}",
            path=errors[0].path,
        )


def validate_file(path: Path) -> None:
    """讀取 JSON 檔案並驗證。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_data_json(data)
    logger.debug("data.json 驗證通過：%s", path)
