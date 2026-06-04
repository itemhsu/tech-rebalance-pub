"""守門測試：每個策略的 email 設定都必須有效、可渲染（避免 #3 類報告壞掉）。

對應事故：mom_6m_t20 曾用無效 section 名 "positions"、缺 cta、subject_template 用 {pct}
（render 時 KeyError），且 migrate_to_mvp 缺少 #3 產生器 → 報告長期停在舊資料。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# renderer 支援的合法 section 名稱
VALID_SECTIONS = {
    "header", "kpi", "strategy_card", "portfolio_badges", "positions_table",
    "rankings", "today_events", "harvest_plan", "trades", "cta", "strategy_history", "footer",
}
# subject_template 允許的 placeholder（build_email_meta 提供的）
VALID_PLACEHOLDERS = {"account_id", "date", "nav", "today_change_pct"}

# 有寄信的「真實帳戶」策略（accounts.json 用到的）
ACCOUNT_STRATEGIES = sorted({
    a["strategy"] for a in json.loads((ROOT / "accounts.json").read_text("utf-8"))["accounts"]
})


def _email_cfg(strategy_id):
    p = ROOT / "strategies" / f"{strategy_id}.json"
    return json.loads(p.read_text("utf-8")).get("email", {}) if p.exists() else {}


@pytest.mark.parametrize("strategy_id", ACCOUNT_STRATEGIES)
def test_sections_are_valid(strategy_id):
    cfg = _email_cfg(strategy_id)
    secs = [s.get("type") if isinstance(s, dict) else s for s in cfg.get("sections", [])]
    bad = [s for s in secs if s not in VALID_SECTIONS]
    assert not bad, f"{strategy_id} 有無效 email section：{bad}"


@pytest.mark.parametrize("strategy_id", ACCOUNT_STRATEGIES)
def test_subject_template_formats(strategy_id):
    tmpl = _email_cfg(strategy_id).get("subject_template", "")
    if not tmpl:
        return
    # 用假值套版，缺 placeholder 會 KeyError → 測試失敗
    tmpl.format(account_id="3", date="2026-06-02", nav=21020.0, today_change_pct=0.0)


def test_mom_6m_t20_has_cta_buttons():
    secs = _email_cfg("mom_6m_t20").get("sections", [])
    assert "cta" in secs, "mom_6m_t20 缺 cta（三個按鈕）"
    assert "header" in secs and "footer" in secs


def test_account3_covered_by_generic_generator():
    """P4 後：#3 不再需要專屬 migrate 函式，泛用產生器涵蓋（非分組排名）。"""
    from engine.report_generator import can_generate
    from engine.accounts import get_account
    assert can_generate(get_account("3")) is True   # mom_6m_t20 走泛用產生器
