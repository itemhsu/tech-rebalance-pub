"""
tests/test_unit1_strategy_schema.py — Unit 1: strategy.json Schema 定義與驗證
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

ROOT = Path(__file__).parent.parent
STRATEGIES_DIR = ROOT / "strategies"

import sys
sys.path.insert(0, str(ROOT))
from engine.strategy_loader import load_strategy, validate_strategy, load_and_validate


# ── fixtures ─────────────────────────────────────────────────────────────────

def _load(name: str) -> dict:
    return json.loads((STRATEGIES_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
#  1. 合法策略檔案通過 schema
# ══════════════════════════════════════════════════════════════════════════════

def test_top10_json_passes_schema():
    data = _load("top10")
    validate_strategy(data)   # 不應 raise


def test_d2p2t6_json_passes_schema():
    data = _load("d2p2t6")
    validate_strategy(data)   # 不應 raise


# ══════════════════════════════════════════════════════════════════════════════
#  2. 非法值應 raise ValidationError
# ══════════════════════════════════════════════════════════════════════════════

def test_unknown_selection_method_fails():
    data = _load("top10")
    data["selection"]["method"] = "magic_algo"
    with pytest.raises(ValidationError):
        validate_strategy(data)


def test_unknown_weighting_fails():
    data = _load("top10")
    data["portfolio"]["weighting"] = "random"
    with pytest.raises(ValidationError):
        validate_strategy(data)


def test_missing_required_field_fails():
    data = _load("top10")
    del data["meta"]["name"]
    with pytest.raises(ValidationError):
        validate_strategy(data)


def test_invalid_accent_color_fails():
    data = _load("top10")
    data["dashboard"]["accent_color"] = "blue"   # 不是 hex
    with pytest.raises(ValidationError):
        validate_strategy(data)


def test_invalid_version_format_fails():
    data = _load("top10")
    data["version"] = "1"   # 應為 "1.0" 格式
    with pytest.raises(ValidationError):
        validate_strategy(data)


def test_invalid_created_at_format_fails():
    data = _load("top10")
    data["meta"]["created_at"] = "2024/01/15"   # 應為 YYYY-MM-DD
    with pytest.raises(ValidationError):
        validate_strategy(data)


# ══════════════════════════════════════════════════════════════════════════════
#  3. universe.type 與 rankings.type 一致性
# ══════════════════════════════════════════════════════════════════════════════

def test_dashboard_rankings_type_matches_single_universe():
    """single universe → market_cap_list"""
    data = _load("top10")
    assert data["universe"]["type"] == "single"
    assert data["dashboard"]["rankings"]["type"] == "market_cap_list"
    validate_strategy(data)  # 應通過


def test_dashboard_rankings_type_matches_grouped_universe():
    """grouped universe → universe_groups"""
    data = _load("d2p2t6")
    assert data["universe"]["type"] == "grouped"
    assert data["dashboard"]["rankings"]["type"] == "universe_groups"
    validate_strategy(data)  # 應通過


def test_universe_rankings_mismatch_fails():
    """single universe 搭配 universe_groups → 應失敗"""
    data = _load("top10")
    data["dashboard"]["rankings"]["type"] = "universe_groups"
    with pytest.raises(ValidationError):
        validate_strategy(data)


# ══════════════════════════════════════════════════════════════════════════════
#  4. load_strategy
# ══════════════════════════════════════════════════════════════════════════════

def test_load_strategy_returns_dict():
    data = load_strategy("top10")
    assert isinstance(data, dict)
    assert data["id"] == "top10"


def test_load_strategy_nonexistent_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        load_strategy("nonexistent_strategy_xyz")


def test_load_and_validate_top10():
    data = load_and_validate("top10")
    assert data["id"] == "top10"


def test_load_and_validate_d2p2t6():
    data = load_and_validate("d2p2t6")
    assert data["id"] == "d2p2t6"
