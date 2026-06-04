"""
tests/test_unit11_migration.py — Unit 11: migrate_to_mvp.py 遷移腳本測試

測試對象：scripts/migrate_to_mvp.py
  - migrate_top10()
  - migrate_d2p2t6()
  - _extract_history_list()
  - 輸出通過 data-schema-v1.json 驗證
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.migrate_to_mvp import (
    _extract_history_list,
    _extract_nav_history,
    _extract_trade_log,
    migrate_top10,
    migrate_d2p2t6,
)
from engine.data_validator import validate_data_json

# ── 前置條件：原始資料必須存在 ────────────────────────────────────────────────

TOP10_STATE   = ROOT / "data" / "1" / "portfolio_state.json"
D2P2T6_STATE  = ROOT / "d2p2t6" / "data" / "1" / "portfolio_state.json"


def _top10_available():
    return TOP10_STATE.exists()


def _d2p2t6_available():
    return D2P2T6_STATE.exists()


# ══════════════════════════════════════════════════════════════════════════════
#  _extract_history_list — 兩種格式均可
# ══════════════════════════════════════════════════════════════════════════════

def test_extract_history_list_from_list():
    raw = [{"date": "2026-05-01", "nav": 100000.0}]
    result = _extract_history_list(raw)
    assert result == raw


def test_extract_history_list_from_dict_format():
    """新格式：dict 包含 history 鍵。"""
    entries = [{"date": "2026-05-01", "nav": 100000.0}]
    raw = {"initial_nav": 100000.0, "start_date": "2026-05-01", "history": entries}
    result = _extract_history_list(raw)
    assert result == entries


def test_extract_history_list_none_returns_empty():
    assert _extract_history_list(None) == []


def test_extract_history_list_empty_dict_returns_empty():
    assert _extract_history_list({}) == []


# ══════════════════════════════════════════════════════════════════════════════
#  _extract_nav_history — 排序、去重
# ══════════════════════════════════════════════════════════════════════════════

def test_extract_nav_history_sorted():
    history = [
        {"date": "2026-05-10", "nav": 102000.0},
        {"date": "2026-05-05", "nav": 100000.0},
    ]
    result = _extract_nav_history(history)
    dates = [e["date"] for e in result]
    assert dates == sorted(dates)


def test_extract_nav_history_deduped():
    history = [
        {"date": "2026-05-01", "nav": 100000.0},
        {"date": "2026-05-01", "nav": 101000.0},  # duplicate date
    ]
    result = _extract_nav_history(history)
    dates = [e["date"] for e in result]
    assert len(dates) == len(set(dates)), "不應有重複日期"


def test_extract_nav_history_fields():
    history = [{"date": "2026-05-01", "nav": 100000.0, "cash": 5000.0}]
    result = _extract_nav_history(history)
    assert result[0] == {"date": "2026-05-01", "nav": 100000.0}


# ══════════════════════════════════════════════════════════════════════════════
#  _extract_trade_log — 降序、缺欄位安全
# ══════════════════════════════════════════════════════════════════════════════

def test_extract_trade_log_descending():
    history = [
        {"date": "2026-05-05", "nav": 100000.0, "top10": []},
        {"date": "2026-05-10", "nav": 102000.0, "top10": []},
    ]
    result = _extract_trade_log(history)
    dates = [e["date"] for e in result]
    assert dates == sorted(dates, reverse=True)


def test_extract_trade_log_missing_orders_executed():
    """history entry 沒有 orders_executed 不應 raise。"""
    history = [{"date": "2026-05-01", "nav": 100000.0}]
    result = _extract_trade_log(history)
    assert result[0]["trades_count"] == 0
    assert result[0]["orders"] == []


def test_extract_trade_log_with_orders():
    history = [{
        "date": "2026-05-01",
        "nav": 100000.0,
        "top10": ["NVDA"],
        "orders_executed": [
            {"symbol": "NVDA", "side": "buy", "qty": 10, "filled_avg_price": 900.0}
        ],
    }]
    result = _extract_trade_log(history)
    assert result[0]["trades_count"] == 1
    assert result[0]["orders"][0]["symbol"] == "NVDA"
    assert result[0]["orders"][0]["price"] == 900.0


# ══════════════════════════════════════════════════════════════════════════════
#  migrate_top10 — 端對端（需要原始資料）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_migrated_top10_passes_schema(tmp_path):
    ok = migrate_top10(tmp_path)
    assert ok, "migrate_top10 應回傳 True"
    output = tmp_path / "1" / "data.json"
    assert output.exists(), "應產生 1/data.json"
    data = json.loads(output.read_text())
    validate_data_json(data)   # 不應 raise


@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_migrated_top10_meta_account_id_matches_directory(tmp_path):
    migrate_top10(tmp_path)
    data = json.loads((tmp_path / "1" / "data.json").read_text())
    assert str(data["meta"]["account_id"]) == "1"


@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_migrated_top10_nav_history_nonempty(tmp_path):
    migrate_top10(tmp_path)
    data = json.loads((tmp_path / "1" / "data.json").read_text())
    assert len(data["nav_history"]) >= 1


@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_migrated_top10_nav_matches_state(tmp_path):
    state = json.loads(TOP10_STATE.read_text())
    migrate_top10(tmp_path)
    data = json.loads((tmp_path / "1" / "data.json").read_text())
    assert data["summary"]["nav"] == pytest.approx(state["nav"], rel=1e-4)


@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_migrated_top10_positions_preserved(tmp_path):
    state = json.loads(TOP10_STATE.read_text())
    orig_symbols = {p["symbol"] for p in state.get("positions", [])}
    migrate_top10(tmp_path)
    data = json.loads((tmp_path / "1" / "data.json").read_text())
    mig_symbols = {p["symbol"] for p in data.get("positions", [])}
    assert mig_symbols == orig_symbols, "所有持倉股票應保留"


@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_migrated_top10_strategy_is_top10(tmp_path):
    migrate_top10(tmp_path)
    data = json.loads((tmp_path / "1" / "data.json").read_text())
    assert data["meta"]["strategy"] == "top10"


@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_migrated_top10_nav_history_length_matches_original(tmp_path):
    history_path = ROOT / "data" / "1" / "portfolio_state_history.json"
    if not history_path.exists():
        pytest.skip("無 history 檔")
    raw = json.loads(history_path.read_text())
    orig_history = _extract_history_list(raw)
    migrate_top10(tmp_path)
    data = json.loads((tmp_path / "1" / "data.json").read_text())
    # nav_history 長度應 >= 原始歷史條目數（今日可能新增一筆）
    assert len(data["nav_history"]) >= len(orig_history)


# ══════════════════════════════════════════════════════════════════════════════
#  migrate_d2p2t6 — 端對端（需要原始資料）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _d2p2t6_available(), reason="需要 d2p2t6/data/1/portfolio_state.json")
def test_migrated_d2p2t6_passes_schema(tmp_path):
    ok = migrate_d2p2t6(tmp_path)
    assert ok, "migrate_d2p2t6 應回傳 True"
    output = tmp_path / "2" / "data.json"
    assert output.exists(), "應產生 2/data.json"
    data = json.loads(output.read_text())
    validate_data_json(data)   # 不應 raise


@pytest.mark.skipif(not _d2p2t6_available(), reason="需要 d2p2t6/data/1/portfolio_state.json")
def test_migrated_d2p2t6_meta_account_id_matches_directory(tmp_path):
    migrate_d2p2t6(tmp_path)
    data = json.loads((tmp_path / "2" / "data.json").read_text())
    assert str(data["meta"]["account_id"]) == "2"


@pytest.mark.skipif(not _d2p2t6_available(), reason="需要 d2p2t6/data/1/portfolio_state.json")
def test_migrated_d2p2t6_strategy_is_d2p2t6(tmp_path):
    migrate_d2p2t6(tmp_path)
    data = json.loads((tmp_path / "2" / "data.json").read_text())
    assert data["meta"]["strategy"] == "d2p2t6"


@pytest.mark.skipif(not _d2p2t6_available(), reason="需要 d2p2t6/data/1/portfolio_state.json")
def test_migrated_d2p2t6_nav_matches_state(tmp_path):
    state = json.loads(D2P2T6_STATE.read_text())
    migrate_d2p2t6(tmp_path)
    data = json.loads((tmp_path / "2" / "data.json").read_text())
    assert data["summary"]["nav"] == pytest.approx(state["nav"], rel=1e-4)


@pytest.mark.skipif(not _d2p2t6_available(), reason="需要 d2p2t6/data/1/portfolio_state.json")
def test_migrated_d2p2t6_positions_preserved(tmp_path):
    state = json.loads(D2P2T6_STATE.read_text())
    orig_symbols = {p["symbol"] for p in state.get("positions", [])}
    migrate_d2p2t6(tmp_path)
    data = json.loads((tmp_path / "2" / "data.json").read_text())
    mig_symbols = {p["symbol"] for p in data.get("positions", [])}
    assert mig_symbols == orig_symbols


@pytest.mark.skipif(not _d2p2t6_available(), reason="需要 d2p2t6/data/1/portfolio_state.json")
def test_migrated_d2p2t6_rankings_type_universe_groups(tmp_path):
    migrate_d2p2t6(tmp_path)
    data = json.loads((tmp_path / "2" / "data.json").read_text())
    assert data["rankings"]["type"] == "universe_groups"


# ══════════════════════════════════════════════════════════════════════════════
#  dry_run 模式
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not _top10_available(), reason="需要 data/1/portfolio_state.json")
def test_dry_run_top10_does_not_write_file(tmp_path):
    migrate_top10(tmp_path, dry_run=True)
    assert not (tmp_path / "1" / "data.json").exists()


@pytest.mark.skipif(not _d2p2t6_available(), reason="需要 d2p2t6/data/1/portfolio_state.json")
def test_dry_run_d2p2t6_does_not_write_file(tmp_path):
    migrate_d2p2t6(tmp_path, dry_run=True)
    assert not (tmp_path / "2" / "data.json").exists()
