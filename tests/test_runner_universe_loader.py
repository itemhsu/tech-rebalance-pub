"""Regression：engine/universe_loader.load_universe_groups。

歷史 bug：d2p2t6 spec 用 csv_file 指向不存在的 CSV → 全部 fallback
到 data/universe.json（top10 科技股），導致 3 個 group 都同一份。

修正後（P2-C+）：
  - specs 改用 inline (d2p2t6) / json_file (top10) — 無 fallback chain
  - 未知 source.type / 缺檔 / 缺欄位 都 raise，不靜默
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import runner
from engine.universe_loader import load_universe_groups, _SOURCE_LOADERS


def test_d2p2t6_loads_three_distinct_groups():
    spec = json.loads((ROOT / "strategies" / "d2p2t6_v3.json").read_text())
    groups = runner.load_universe_groups(spec)

    assert set(groups.keys()) == {"defense", "pharma", "tech"}
    defense, pharma, tech = set(groups["defense"]), set(groups["pharma"]), set(groups["tech"])

    assert defense != pharma and defense != tech and pharma != tech
    assert "LMT" in defense and "NOC" in defense
    assert "JNJ" in pharma and "PFE" in pharma
    assert "AAPL" in tech and "NVDA" in tech
    assert "AAPL" not in defense
    assert "LMT" not in tech


def test_top10_loads_25_stock_universe():
    spec = json.loads((ROOT / "strategies" / "top10_v3.json").read_text())
    groups = runner.load_universe_groups(spec)
    assert "__all__" in groups
    syms = set(groups["__all__"])
    assert len(syms) >= 20
    assert {"AAPL", "MSFT", "NVDA"}.issubset(syms)


def test_unknown_grouped_source_type_raises():
    """Code review #1：未知 source.type 必須炸開，不能靜默 drop group。"""
    bad_spec = {
        "universe": {
            "type": "grouped",
            "groups": [
                {"id": "a", "source": {"type": "inline", "symbols": ["X"]}},
                {"id": "b", "source": {"type": "csv"}},  # typo
            ],
        }
    }
    with pytest.raises(ValueError, match="source.type"):
        runner.load_universe_groups(bad_spec)


def test_unknown_single_source_type_raises():
    """Code review #1：single 路徑同樣不能靜默接受未知 type。"""
    bad = {"universe": {"type": "single", "source": {"type": "yaml_file"}}}
    with pytest.raises(ValueError, match="source.type"):
        load_universe_groups(bad)


def test_unknown_universe_type_raises():
    bad = {"universe": {"type": "exotic"}}
    with pytest.raises(ValueError, match="universe.type"):
        load_universe_groups(bad)


def test_csv_missing_file_raises():
    """Code review #2：CSV 不存在不能靜默 fallback，必須 raise。"""
    bad = {"universe": {"type": "single",
                        "source": {"type": "csv_file", "path": "nope.csv"}}}
    with pytest.raises(FileNotFoundError):
        load_universe_groups(bad)


def test_csv_missing_column_raises(tmp_path):
    """Code review #2：CSV 存在但欄位錯也必須 raise，不能 fallback 到別的 universe。"""
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("ticker\nAAPL\n")
    bad = {"universe": {"type": "single",
                        "source": {"type": "csv_file",
                                   "path": str(bad_csv.relative_to(ROOT)) if tmp_path.is_relative_to(ROOT) else str(bad_csv),
                                   "symbol_column": "symbol"}}}
    # 用絕對路徑（tmp_path 不在 ROOT 內）— 寫入後測試
    bad["universe"]["source"]["path"] = str(bad_csv)
    # _load_csv 用 _ROOT / path_str，傳絕對路徑時會用絕對路徑
    # 但我們需要 tmp_path 相對 _ROOT 不存在，故 file_not_found 會先觸發
    # 改測法：直接 mock _ROOT
    import engine.universe_loader as ul
    orig = ul._ROOT
    try:
        ul._ROOT = tmp_path.parent
        bad["universe"]["source"]["path"] = bad_csv.name
        # 還是不對；最簡單：直接 cd 到 tmp_path
        import os
        ul._ROOT = tmp_path
        bad["universe"]["source"]["path"] = bad_csv.name
        with pytest.raises(KeyError, match="symbol"):
            load_universe_groups(bad)
    finally:
        ul._ROOT = orig


def test_json_file_missing_key_raises(tmp_path, monkeypatch):
    """Code review #2：JSON 缺 key 也要 raise。"""
    import engine.universe_loader as ul
    bad_json = tmp_path / "x.json"
    bad_json.write_text('{"wrong_key": ["A"]}')
    monkeypatch.setattr(ul, "_ROOT", tmp_path)
    spec = {"universe": {"type": "single",
                         "source": {"type": "json_file", "path": "x.json", "key": "stocks"}}}
    with pytest.raises(KeyError, match="stocks"):
        load_universe_groups(spec)


def test_no_strategy_specific_fallbacks_in_loader():
    """Code review #3+#4：engine 內不該再有 strategy-specific 函式。"""
    import engine.universe_loader as ul
    public_funcs = [n for n in dir(ul) if not n.startswith("_") or n.startswith("_load")]
    # 不該有 _fallback_d2p2t6 / _fallback_top10
    for name in dir(ul):
        assert "fallback" not in name.lower(), f"engine 不該含 fallback 函式：{name}"
        assert "d2p2t6" not in name.lower(), f"engine 不該含 strategy-specific 函式：{name}"
        assert "top10" not in name.lower(), f"engine 不該含 strategy-specific 函式：{name}"
