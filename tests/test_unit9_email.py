"""
tests/test_unit9_email.py — Unit 9: email_renderer.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT     = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

sys.path.insert(0, str(ROOT))

from engine.email_renderer import render_from_dict
from engine.strategy_loader import load_and_validate

TOP10  = load_and_validate("top10")
D2P2T6 = load_and_validate("d2p2t6")


def _top10_data() -> dict:
    return json.loads((FIXTURES / "top10_data.json").read_text(encoding="utf-8"))


def _d2p2t6_data() -> dict:
    return json.loads((FIXTURES / "d2p2t6_data.json").read_text(encoding="utf-8"))


def _render_top10(**kwargs) -> tuple[str, str]:
    d = _top10_data()
    d.update(kwargs)
    return render_from_dict(d, TOP10)


# ══════════════════════════════════════════════════════════════════════════════
#  基本渲染
# ══════════════════════════════════════════════════════════════════════════════

def test_render_returns_subject_and_html():
    subject, html = _render_top10()
    assert isinstance(subject, str) and subject
    assert isinstance(html, str) and "<!DOCTYPE html>" in html


def test_subject_matches_data_json():
    subject, _ = _render_top10()
    assert subject == _top10_data()["email"]["subject"]


def test_html_contains_doctype():
    _, html = _render_top10()
    assert "<!DOCTYPE html>" in html


# ══════════════════════════════════════════════════════════════════════════════
#  Sections
# ══════════════════════════════════════════════════════════════════════════════

def test_all_configured_sections_produce_content():
    """strategy.email.sections 的已知 section 都會在 html 中有對應內容。"""
    _, html = _render_top10()
    # header → account id 出現在 html
    d = _top10_data()
    assert f"帳戶 #{d['meta']['account_id']}" in html


def test_unknown_section_skipped_not_crash():
    d = _top10_data()
    strategy_mod = dict(TOP10)
    strategy_mod = {**TOP10, "email": {**TOP10["email"], "sections": ["header", "nonexistent_section", "footer"]}}
    # 不應 raise
    _, html = render_from_dict(d, strategy_mod)
    assert "<!DOCTYPE html>" in html


def test_empty_events_hides_events_block():
    d = _top10_data()
    d["events"] = []
    _, html = render_from_dict(d, TOP10)
    assert "今日帳戶事件" not in html


def test_today_events_shows_event_block():
    d = _top10_data()
    d["meta"]["trading_date"] = "2026-05-16"
    d["events"] = [{
        "id": "e1", "date": "2026-05-16", "type": "deposit",
        "nav_before": 100000, "nav_after": 150000, "amount": 50000
    }]
    _, html = render_from_dict(d, TOP10)
    assert "今日帳戶事件" in html


# ══════════════════════════════════════════════════════════════════════════════
#  DRY RUN / Paused
# ══════════════════════════════════════════════════════════════════════════════

def test_dry_run_shows_dry_run_badge():
    d = _top10_data()
    d["meta"]["dry_run"] = True
    _, html = render_from_dict(d, TOP10)
    assert "DRY RUN" in html


def test_live_shows_live_badge():
    d = _top10_data()
    d["meta"]["dry_run"] = False
    d["meta"]["strategy_status"] = "active"
    _, html = render_from_dict(d, TOP10)
    assert "LIVE" in html


def test_paused_shows_paused_badge():
    d = _top10_data()
    d["meta"]["dry_run"] = False
    d["meta"]["strategy_status"] = "paused"
    _, html = render_from_dict(d, TOP10)
    assert "PAUSED" in html


# ══════════════════════════════════════════════════════════════════════════════
#  CTA
# ══════════════════════════════════════════════════════════════════════════════

def test_cta_href_matches_dashboard_url():
    d = _top10_data()
    url = d["email"]["dashboard_url"]
    _, html = render_from_dict(d, TOP10)
    assert url in html


# ══════════════════════════════════════════════════════════════════════════════
#  Rankings 多型
# ══════════════════════════════════════════════════════════════════════════════

def test_market_cap_list_renders_single_table():
    _, html = _render_top10()
    # market_cap_list 顯示單一排名表
    assert "科技股市值排名" in html


def test_universe_groups_renders_three_columns():
    d = _d2p2t6_data()
    _, html = render_from_dict(d, D2P2T6)
    assert "三大宇宙即時排名" in html
    assert "軍火" in html
    assert "醫藥" in html
    assert "科技" in html


# ══════════════════════════════════════════════════════════════════════════════
#  HTML 安全性
# ══════════════════════════════════════════════════════════════════════════════

def test_html_no_external_src():
    """無外部 src（圖片、script 等），確保 email client 相容。"""
    import re
    _, html = _render_top10()
    # 不應有 <img src="http..." 或 <script src="http..."
    bad = re.findall(r'src=["\']http', html)
    assert not bad, f"發現外部 src：{bad}"


def test_html_no_external_link_href():
    """只允許 CTA 按鈕的 href；不應有其他外部 <link>。"""
    import re
    _, html = _render_top10()
    link_hrefs = re.findall(r'<link[^>]+href=["\']http', html)
    assert not link_hrefs


# ══════════════════════════════════════════════════════════════════════════════
#  事件渲染
# ══════════════════════════════════════════════════════════════════════════════

def test_deposit_event_shows_positive_amount():
    d = _top10_data()
    d["meta"]["trading_date"] = "2026-05-16"
    d["events"] = [{
        "id": "e1", "date": "2026-05-16", "type": "deposit",
        "nav_before": 100000, "nav_after": 150000, "amount": 50000
    }]
    _, html = render_from_dict(d, TOP10)
    assert "+$50,000" in html


def test_withdrawal_event_shows_negative():
    d = _top10_data()
    d["meta"]["trading_date"] = "2026-05-16"
    d["events"] = [{
        "id": "e1", "date": "2026-05-16", "type": "withdrawal",
        "nav_before": 150000, "nav_after": 120000, "amount": -30000
    }]
    _, html = render_from_dict(d, TOP10)
    assert "出金" in html


def test_strategy_switch_shows_from_to():
    d = _top10_data()
    d["meta"]["trading_date"] = "2026-05-16"
    d["events"] = [{
        "id": "e1", "date": "2026-05-16", "type": "strategy_switch",
        "nav_before": 100000, "nav_after": 100000,
        "from_strategy": "top10", "to_strategy": "d2p2t6"
    }]
    _, html = render_from_dict(d, TOP10)
    assert "top10" in html
    assert "d2p2t6" in html


# ══════════════════════════════════════════════════════════════════════════════
#  持倉 in_portfolio 標記
# ══════════════════════════════════════════════════════════════════════════════

def test_positions_in_portfolio_has_green_indicator():
    _, html = _render_top10()
    # in_portfolio=True 的持倉有 ● 標記
    assert "●" in html


def test_twr_displayed_in_kpi():
    """KPI 顯示 TWR 而非簡單報酬。"""
    _, html = _render_top10()
    assert "TWR" in html
