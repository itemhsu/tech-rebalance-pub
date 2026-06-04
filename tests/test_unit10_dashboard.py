"""
tests/test_unit10_dashboard.py — Unit 10: mvp_dashboard.html 靜態分析測試

由於無法在 CI 環境跑 Playwright，此檔用 HTML 解析確認 dashboard.html 的
結構正確性、關鍵元素存在、JS 邏輯要素正確。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
DASHBOARD_PATH = ROOT / "mvp_dashboard.html"


def _html() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  基本結構
# ══════════════════════════════════════════════════════════════════════════════

def test_dashboard_file_exists():
    assert DASHBOARD_PATH.exists()


def test_has_doctype():
    assert "<!DOCTYPE html>" in _html()


def test_has_chart_js():
    assert "chart.js" in _html().lower()


def test_has_tailwind():
    assert "tailwindcss" in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  路由邏輯
# ══════════════════════════════════════════════════════════════════════════════

def test_fetches_accounts_json():
    assert 'accounts.json' in _html()


def test_fetches_data_json():
    assert 'data.json' in _html()


def test_url_param_a_used():
    """?a= 參數決定帳戶 ID。"""
    assert 'get("a")' in _html() or "get('a')" in _html()


def test_account_not_found_shows_error():
    """帳戶 ID 不存在時呼叫 showError。"""
    h = _html()
    assert "showError" in h
    assert "帳戶 ID 不存在" in h


def test_fetch_failure_shows_error():
    """fetch 失敗時呼叫 showError。"""
    assert "showError" in _html()


def test_schema_version_check():
    """schema_version 不符顯示 version-banner。"""
    assert "version-banner" in _html()
    assert "SUPPORTED_SCHEMA_VERSION" in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  KPI 元素
# ══════════════════════════════════════════════════════════════════════════════

def test_kpi_nav_element_exists():
    assert 'id="kpi-nav"' in _html()


def test_kpi_today_pct_element_exists():
    assert 'id="kpi-today-pct"' in _html()


def test_kpi_twr_element_exists():
    assert 'id="kpi-twr"' in _html()


def test_kpi_ytd_element_exists():
    assert 'id="kpi-ytd"' in _html()


def test_twr_label_in_html():
    """KPI 標題應包含 TWR 字樣。"""
    assert "TWR" in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  帳戶切換選單
# ══════════════════════════════════════════════════════════════════════════════

def test_account_switcher_element_exists():
    assert 'id="account-switcher"' in _html()


def test_account_switcher_function_defined():
    assert "renderAccountSwitcher" in _html()


def test_account_switcher_has_options():
    """帳戶切換器使用 allAccounts 顯示全部帳戶。"""
    h = _html()
    # 新版顯示全部帳戶（allAccounts），或保有同策略過濾（sameStrategy）
    assert "allAccounts" in h or "sameStrategy" in h or "currentStrategy" in h


# ══════════════════════════════════════════════════════════════════════════════
#  圖表
# ══════════════════════════════════════════════════════════════════════════════

def test_nav_chart_canvas_exists():
    assert 'id="nav-chart"' in _html()


def test_drawdown_chart_canvas_exists():
    assert 'id="drawdown-chart"' in _html()


def test_nav_chart_function_defined():
    assert "renderNavChart" in _html()


def test_drawdown_chart_function_defined():
    assert "renderDrawdownChart" in _html()


def test_drawdown_benchmark_null_safe():
    """benchmark null 值判斷。"""
    assert "some(v => v !== null)" in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  持倉
# ══════════════════════════════════════════════════════════════════════════════

def test_positions_tbody_exists():
    assert 'id="positions-tbody"' in _html()


def test_in_portfolio_green_marker():
    """in_portfolio=true 的持倉有綠色標記。"""
    h = _html()
    assert "in_portfolio" in h or "in-port" in h


def test_positions_function_defined():
    assert "renderPositions" in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  Rankings 多型
# ══════════════════════════════════════════════════════════════════════════════

def test_rankings_function_defined():
    assert "renderRankings" in _html()


def test_market_cap_list_render_function():
    assert "renderMarketCapList" in _html()


def test_universe_groups_render_function():
    assert "renderUniverseGroups" in _html()


def test_rankings_type_dispatch():
    """根據 rankings.type 分派渲染。"""
    assert "market_cap_list" in _html()
    assert "universe_groups" in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  事件
# ══════════════════════════════════════════════════════════════════════════════

def test_events_section_exists():
    assert 'id="events-section"' in _html()


def test_events_function_defined():
    assert "renderEvents" in _html()


def test_events_filtered_by_today():
    """只顯示今日事件。"""
    assert "e.date === today" in _html()


def test_events_hidden_when_empty():
    """無事件時 events-section 不顯示。"""
    assert 'display = "none"' in _html() or "display:none" in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  Banner
# ══════════════════════════════════════════════════════════════════════════════

def test_dry_run_banner_exists():
    assert 'id="dry-run-banner"' in _html()


def test_pause_banner_exists():
    assert 'id="pause-banner"' in _html()


def test_error_banner_exists():
    assert 'id="error-banner"' in _html()


# ══════════════════════════════════════════════════════════════════════════════
#  交易日誌
# ══════════════════════════════════════════════════════════════════════════════

def test_trade_log_element_exists():
    assert 'id="trade-log"' in _html()


def test_trade_log_function_defined():
    assert "renderTradeLog" in _html()
