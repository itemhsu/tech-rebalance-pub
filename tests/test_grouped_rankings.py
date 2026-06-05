"""tests/test_grouped_rankings.py — 分組排名通用化（取代寫死的 migrate_d2p2t6）。

自包含：用合成 fixture，不需 live accounts.json / data。驗證：
  - group 名稱來自策略 JSON（dashboard.rankings.group_labels），非寫死
  - latest_rankings.json 的輔助鍵（top_def 等字串清單）被略過、不誤入
  - 缺檔回 None
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine import report_generator as rg


def _strat():
    return {"dashboard": {"rankings": {
        "type": "universe_groups",
        "group_labels": {"defense": "🛡️ 軍火", "pharma": "💊 醫藥", "tech": "💻 科技"},
    }}}


def test_group_ids_from_strategy_json():
    assert rg._group_ids(_strat()) == ["defense", "pharma", "tech"]
    # 後援：universe_groups.groups
    s2 = {"universe_groups": {"groups": {"a": {}, "b": {}}}}
    assert rg._group_ids(s2) == ["a", "b"]


def test_grouped_rankings_picks_only_declared_groups(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    dd = tmp_path / "d2p2t6" / "data" / "1"
    dd.mkdir(parents=True)
    (dd / "latest_rankings.json").write_text(json.dumps({
        "date": "2026-05-29",
        "defense": [{"sym": "RTX", "rank": 1, "price": 179.6, "chg_pct": 0.4, "mcap_b": 241.9}],
        "pharma":  [{"sym": "LLY", "rank": 1, "price": 1105.0, "chg_pct": -1.9, "mcap_b": 985.4}],
        "tech":    [{"sym": "NVDA", "rank": 1, "price": 212.5, "chg_pct": -1.5, "mcap_b": 5114.0}],
        "top_def": ["RTX", "LMT"],          # 輔助鍵（字串清單）——必須略過
        "d2p2t6_portfolio": ["AAPL"],       # 同上
        "caps_b": {"RTX": 241.9},           # dict——非 list，略過
    }), encoding="utf-8")
    groups = rg._grouped_rankings(_strat(), "d2p2t6/data/1")
    assert set(groups.keys()) == {"defense", "pharma", "tech"}   # 不含 top_def 等
    assert groups["defense"][0]["sym"] == "RTX"
    assert groups["tech"][0]["mcap_b"] == 5114.0


def test_grouped_rankings_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    assert rg._grouped_rankings(_strat(), "nope/data/1") is None
