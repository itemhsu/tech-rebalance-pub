"""Phase A：broker-schema v2 驗證測試（S-01 ~ S-05）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
BROKERS_DIR = ROOT / "brokers"
SCHEMA_V2 = BROKERS_DIR / "broker-schema-v2.json"


def _schema():
    return json.loads(SCHEMA_V2.read_text(encoding="utf-8"))


def _alpaca():
    return json.loads((BROKERS_DIR / "alpaca.json").read_text(encoding="utf-8"))


def test_S01_alpaca_passes_v2():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(_alpaca(), _schema())


def test_S02_tradier_passes_v2():
    jsonschema = pytest.importorskip("jsonschema")
    tradier = BROKERS_DIR / "tradier.json"
    if not tradier.exists():
        pytest.skip("tradier.json 尚未建立（Phase C）")
    jsonschema.validate(json.loads(tradier.read_text(encoding="utf-8")), _schema())


def test_S03_encoding_enum_enforced():
    jsonschema = pytest.importorskip("jsonschema")
    spec = _alpaca()
    spec.setdefault("request", {"encoding": "json", "field_map": {"symbol": "symbol"}})
    spec["request"]["encoding"] = "xml"   # 非法
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, _schema())


def test_S04_request_requires_field_map():
    jsonschema = pytest.importorskip("jsonschema")
    spec = _alpaca()
    spec["request"] = {"encoding": "json"}   # 缺 field_map
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(spec, _schema())


def test_S05_v1_spec_without_mappings_still_valid():
    """向下相容：沒有 request/response 區塊的 v1 風格 spec 仍通過 v2。"""
    jsonschema = pytest.importorskip("jsonschema")
    spec = _alpaca()
    spec.pop("request", None)
    spec.pop("response", None)
    spec.pop("value_maps", None)
    jsonschema.validate(spec, _schema())   # 不該丟例外
