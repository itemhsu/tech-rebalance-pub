"""遷移守門：market-agnostic 策略在美股市場必須與 legacy 策略選股等價。

top10 (json_file data/universe.json[stocks]) 之 universe 必須 == tech_top10
(market_group tech → data/tech.us.json[symbols])，且選股設定相同 → 換策略不動持倉。
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STRAT = ROOT / "strategies"
DATA = ROOT / "data"


def _strategy(name):
    return json.loads((STRAT / f"{name}.json").read_text(encoding="utf-8"))


def _legacy_universe(spec):
    src = spec["universe"]["source"]
    if src["type"] == "inline":                       # mom_6m_t20 用 inline 股池
        return set(src["symbols"])
    assert src["type"] == "json_file", src
    blob = json.loads((ROOT / src["path"]).read_text(encoding="utf-8"))
    return set(blob[src["key"]])


def _market_group_universe(spec, market="us"):
    src = spec["universe"]["source"]
    assert src["type"] == "market_group", src
    blob = json.loads((DATA / f"{src['group']}.{market}.json").read_text(encoding="utf-8"))
    return set(blob["symbols"])


def _selection(spec):
    return spec.get("selection") or spec.get("ranking") or spec.get("weighting")


def test_tech_top10_universe_equals_top10_us():
    assert _market_group_universe(_strategy("tech_top10")) == _legacy_universe(_strategy("top10"))


def test_tech_top10_selection_matches_top10():
    assert _selection(_strategy("tech_top10")) == _selection(_strategy("top10"))


def test_tech_mom_universe_equals_mom_us():
    assert _market_group_universe(_strategy("tech_mom_6m_t10")) == _legacy_universe(_strategy("mom_6m_t20"))


@pytest.mark.xfail(strict=True, reason=(
    "KNOWN GAP（已查證 2026-06-10）：mom_6m_t20 watchlist_top_n=20，"
    "tech_mom_6m_t10=15 → 動能預篩範圍不同，選股可能不同。帳戶 #3 在兩者對齊前"
    "「不可」遷移。若本測試開始 PASS（有人把兩者對齊了）→ strict xfail 會轉為 FAIL，"
    "提醒重新評估 #3 遷移。"))
def test_tech_mom_selection_matches_mom():
    assert _selection(_strategy("tech_mom_6m_t10")) == _selection(_strategy("mom_6m_t20"))
