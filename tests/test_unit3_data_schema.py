"""
tests/test_unit3_data_schema.py — Unit 3: data.json JSON Schema 驗證器
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

ROOT     = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

import sys
sys.path.insert(0, str(ROOT))
from engine.data_validator import validate_data_json, validate_file


def _top10() -> dict:
    return json.loads((FIXTURES / "top10_data.json").read_text(encoding="utf-8"))


def _d2p2t6() -> dict:
    return json.loads((FIXTURES / "d2p2t6_data.json").read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
#  1. 合法 fixture 通過驗證
# ══════════════════════════════════════════════════════════════════════════════

def test_valid_top10_fixture_passes():
    validate_data_json(_top10())


def test_valid_d2p2t6_fixture_passes():
    validate_data_json(_d2p2t6())


def test_validate_file_top10(tmp_path):
    src = FIXTURES / "top10_data.json"
    dst = tmp_path / "data.json"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    validate_file(dst)


# ══════════════════════════════════════════════════════════════════════════════
#  2. 缺少必要欄位
# ══════════════════════════════════════════════════════════════════════════════

def test_missing_meta_fails():
    d = _top10()
    del d["meta"]
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_missing_summary_fails():
    d = _top10()
    del d["summary"]
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_missing_events_fails():
    d = _top10()
    del d["events"]
    with pytest.raises(ValidationError):
        validate_data_json(d)


# ══════════════════════════════════════════════════════════════════════════════
#  3. 型別錯誤
# ══════════════════════════════════════════════════════════════════════════════

def test_wrong_strategy_status_fails():
    d = _top10()
    d["meta"]["strategy_status"] = "running"   # 不在 enum 中
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_dry_run_string_instead_of_bool_fails():
    d = _top10()
    d["meta"]["dry_run"] = "true"   # 應是 boolean
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_summary_nav_must_be_number():
    d = _top10()
    d["summary"]["nav"] = "128450"
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_nav_history_not_array_fails():
    d = _top10()
    d["nav_history"] = {"date": "2026-05-16", "nav": 100}
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_schema_version_not_string_fails():
    d = _top10()
    d["meta"]["schema_version"] = 1.0
    with pytest.raises(ValidationError):
        validate_data_json(d)


# ══════════════════════════════════════════════════════════════════════════════
#  4. rankings 多型
# ══════════════════════════════════════════════════════════════════════════════

def test_market_cap_list_with_missing_items_fails():
    d = _top10()
    del d["rankings"]["items"]
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_universe_groups_with_missing_groups_fails():
    d = _d2p2t6()
    del d["rankings"]["groups"]
    with pytest.raises(ValidationError):
        validate_data_json(d)


# ══════════════════════════════════════════════════════════════════════════════
#  5. events 欄位
# ══════════════════════════════════════════════════════════════════════════════

def test_events_invalid_type_fails():
    d = _top10()
    d["events"] = [{"id": "e1", "date": "2026-05-16", "type": "magic",
                    "nav_before": 100, "nav_after": 150}]
    with pytest.raises(ValidationError):
        validate_data_json(d)


def test_events_missing_id_fails():
    d = _top10()
    d["events"] = [{"date": "2026-05-16", "type": "deposit",
                    "nav_before": 100, "nav_after": 150, "amount": 50}]
    with pytest.raises(ValidationError):
        validate_data_json(d)


# ══════════════════════════════════════════════════════════════════════════════
#  6. max_drawdown_pct 必須 <= 0
# ══════════════════════════════════════════════════════════════════════════════

def test_max_drawdown_positive_fails():
    d = _top10()
    d["summary"]["max_drawdown_pct"] = 5.0   # 應為負數
    with pytest.raises(ValidationError):
        validate_data_json(d)
