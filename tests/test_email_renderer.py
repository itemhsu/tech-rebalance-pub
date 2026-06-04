"""
tests/test_email_renderer.py

電子郵件 Model-View 分離架構測試。

測試範圍：
  1. render_from_dict：核心渲染函式（純 dict，不依賴檔案系統）
  2. 各帳戶 data.json 結構完整性
  3. Subject 由 data["email"]["subject"] 生成（Model 驅動）
  4. dashboard_url 使用 MVP 格式
  5. send_for_account：DRY RUN 模式（不發送真實郵件）
  6. send_email_from_data：全帳戶批次 DRY RUN
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.email_renderer import render_from_dict
from scripts.send_email_from_data import (
    account_strategy_map,
    send_for_account,
)

# 從 accounts.json 動態建構（取代舊硬編 dict）
ACCOUNT_STRATEGY = account_strategy_map()

# ── 共用 Fixtures ──────────────────────────────────────────────────────────────

MVP_DATA_DIR = ROOT / "mvp_data"

ACCOUNTS = ["1", "2", "3"]

STRATEGY_EMAIL_SECTIONS = {
    "top10": [
        "header", "kpi", "portfolio_badges",
        "positions_table", "rankings",
        "today_events", "trades", "cta", "footer",
    ],
    "d2p2t6": [
        "header", "kpi", "portfolio_badges",
        "positions_table", "rankings",
        "today_events", "trades", "cta", "footer",
    ],
    "top9psq": [
        "header", "kpi", "portfolio_badges",
        "positions_table", "rankings",
        "today_events", "trades", "cta", "footer",
    ],
}


def _minimal_data(account_id: str = "1", strategy: str = "top10") -> dict[str, Any]:
    """建立最小合法 data.json dict（不依賴磁碟）。"""
    return {
        "schema_version": "1",
        "meta": {
            "account_id":     account_id,
            "strategy":       strategy,
            "trading_date":   "2026-05-20",
            "generated_at":   "2026-05-20T22:00:00Z",
            "dry_run":        False,
            "strategy_status": "active",
            "accent_color":   "#38bdf8",
        },
        "strategy_name": "TOP10",
        "summary": {
            "nav":                100_000.0,
            "cash":               1_000.0,
            "today_change":       -100.0,
            "today_change_pct":   -0.10,
            "total_return_pct_twr": 5.00,
            "ytd_return_pct":     3.00,
            "inception_date":     "2026-01-02",
            "initial_nav":        95_000.0,
        },
        "portfolio": {
            "label":   "TOP10 持股",
            "symbols": ["AAPL", "MSFT", "NVDA"],
        },
        "positions": [
            {
                "symbol":        "AAPL",
                "qty":           10,
                "current_price": 200.0,
                "weight":        20.0,
                "in_portfolio":  True,
                "unrealized_pl":    50.0,
                "unrealized_plpc":  0.25,
            },
        ],
        "rankings": {
            "type":  "market_cap_list",
            "label": "市值排名",
            "items": [
                {
                    "rank":         1,
                    "symbol":       "NVDA",
                    "price":        900.0,
                    "change_pct":   1.5,
                    "market_cap_b": 2200.0,
                    "in_portfolio": True,
                },
            ],
        },
        "nav_history": [{"date": "2026-05-20", "nav": 100_000.0}],
        "drawdown":    {"labels": [], "portfolio": [], "sp500": [], "nasdaq": []},
        "trade_log":   [],
        "events":      [],
        "email": {
            "subject":          f"[TOP10 #{account_id}] 2026-05-20 NAV $100,000 (-0.10%)",
            "preheader":        f"帳戶 #{account_id} · 2026-05-20 · NAV $100,000",
            "dashboard_url":    f"https://itemhsu.github.io/tech-rebalance-dashboard/mvp_dashboard.html?a={account_id}",
            "sections_rendered": ["header", "kpi", "positions_table", "cta", "footer"],
        },
    }


def _minimal_strategy(strategy_id: str = "top10") -> dict[str, Any]:
    """建立最小合法 strategy dict。"""
    return {
        "id": strategy_id,
        "email": {
            "subject_template": "[TOP10 #{account_id}] {date} NAV ${nav:,.0f} ({today_change_pct:+.2f}%)",
            "sections": STRATEGY_EMAIL_SECTIONS.get(strategy_id, ["header", "cta", "footer"]),
        },
        "dashboard": {
            "accent_color":    "#38bdf8",
            "portfolio_label": "持股",
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. render_from_dict — 核心渲染（不依賴檔案）
# ══════════════════════════════════════════════════════════════════════════════

class TestRenderFromDict:

    def test_returns_tuple(self):
        data     = _minimal_data()
        strategy = _minimal_strategy()
        result   = render_from_dict(data, strategy)
        assert isinstance(result, tuple), "render_from_dict 應回傳 tuple"
        assert len(result) == 2, "回傳 tuple 應含 (subject, html)"

    def test_subject_from_data_json(self):
        """主旨應直接取自 data['email']['subject']（Model 驅動）。"""
        data     = _minimal_data()
        strategy = _minimal_strategy()
        subject, _ = render_from_dict(data, strategy)
        assert subject == data["email"]["subject"], \
            f"主旨應等於 data.email.subject，但得到：{subject!r}"

    def test_html_is_string(self):
        data       = _minimal_data()
        strategy   = _minimal_strategy()
        _, html    = render_from_dict(data, strategy)
        assert isinstance(html, str), "HTML 應為字串"
        assert len(html) > 100, "HTML 內容不應為空"

    def test_html_contains_account_id(self):
        data     = _minimal_data("1")
        strategy = _minimal_strategy()
        _, html  = render_from_dict(data, strategy)
        assert "#1" in html, "HTML 應包含帳戶 ID"

    def test_html_contains_nav(self):
        data     = _minimal_data()
        strategy = _minimal_strategy()
        _, html  = render_from_dict(data, strategy)
        assert "100,000" in html, "HTML 應包含 NAV 數值"

    def test_html_contains_dashboard_cta(self):
        """CTA 按鈕應指向 MVP Dashboard URL。"""
        data     = _minimal_data("2")
        strategy = _minimal_strategy()
        _, html  = render_from_dict(data, strategy)
        assert "mvp_dashboard.html?a=2" in html, \
            "CTA 按鈕應包含 mvp_dashboard.html?a=2"

    def test_html_is_valid_html(self):
        data     = _minimal_data()
        strategy = _minimal_strategy()
        _, html  = render_from_dict(data, strategy)
        assert html.strip().startswith("<!DOCTYPE html>"), "HTML 應以 DOCTYPE 開頭"
        assert "</html>" in html, "HTML 應有結尾標籤"

    @pytest.mark.parametrize("account_id", ACCOUNTS)
    def test_all_accounts_render(self, account_id: str):
        """三個帳戶都能成功渲染。"""
        strategy_id = ACCOUNT_STRATEGY[account_id]
        data     = _minimal_data(account_id, strategy_id)
        strategy = _minimal_strategy(strategy_id)
        subject, html = render_from_dict(data, strategy)
        assert subject, f"帳戶 #{account_id} 主旨不應為空"
        assert html,    f"帳戶 #{account_id} HTML 不應為空"

    def test_section_header_rendered(self):
        strategy = {**_minimal_strategy(), "email": {
            "subject_template": "[T] {date}",
            "sections": ["header"],
        }}
        _, html = render_from_dict(_minimal_data(), strategy)
        assert "TOP10" in html or "帳戶" in html, "header section 應包含帳戶資訊"

    def test_section_kpi_rendered(self):
        strategy = {**_minimal_strategy(), "email": {
            "subject_template": "[T] {date}",
            "sections": ["kpi"],
        }}
        _, html = render_from_dict(_minimal_data(), strategy)
        assert "NAV" in html or "100,000" in html, "KPI section 應包含 NAV"

    def test_unknown_section_skipped_gracefully(self):
        """未知 section 不應導致例外。"""
        strategy = {**_minimal_strategy(), "email": {
            "subject_template": "[T] {date}",
            "sections": ["nonexistent_section", "cta"],
        }}
        subject, html = render_from_dict(_minimal_data(), strategy)
        assert "mvp_dashboard" in html, "未知 section 後，CTA 仍應渲染"

    def test_positions_empty_returns_no_table(self):
        data = _minimal_data()
        data["positions"] = []
        strategy = {**_minimal_strategy(), "email": {
            "subject_template": "[T] {date}",
            "sections": ["positions_table"],
        }}
        _, html = render_from_dict(data, strategy)
        # 持倉為空時不渲染表格
        assert "股票" not in html, "持倉為空時不應渲染欄位標題"

    def test_trade_log_empty_shows_no_trades(self):
        data = _minimal_data()
        data["trade_log"] = []
        strategy = {**_minimal_strategy(), "email": {
            "subject_template": "[T] {date}",
            "sections": ["trades"],
        }}
        _, html = render_from_dict(data, strategy)
        assert "今日無交易" not in html, "交易紀錄為空時 trades section 應不渲染（回傳空字串）"


# ══════════════════════════════════════════════════════════════════════════════
# 2. dashboard_url 格式驗證（MVP URL）
# ══════════════════════════════════════════════════════════════════════════════

class TestDashboardUrl:

    @pytest.mark.parametrize("account_id", ACCOUNTS)
    def test_dashboard_url_is_mvp_format(self, account_id: str):
        """data.json 中的 dashboard_url 應使用 mvp_dashboard.html?a={id} 格式。"""
        data_path = MVP_DATA_DIR / account_id / "data.json"
        if not data_path.exists():
            pytest.skip(f"mvp_data/{account_id}/data.json 尚未生成")
        data = json.loads(data_path.read_text(encoding="utf-8"))
        url  = data.get("email", {}).get("dashboard_url", "")
        assert "mvp_dashboard.html" in url, \
            f"帳戶 #{account_id} dashboard_url 應含 mvp_dashboard.html，實際：{url}"
        assert f"?a={account_id}" in url, \
            f"帳戶 #{account_id} dashboard_url 應含 ?a={account_id}，實際：{url}"

    @pytest.mark.parametrize("account_id", ACCOUNTS)
    def test_cta_button_url_correct(self, account_id: str):
        """渲染後的 HTML CTA 按鈕應包含正確的 MVP URL。"""
        strategy_id = ACCOUNT_STRATEGY[account_id]
        data     = _minimal_data(account_id, strategy_id)
        strategy = _minimal_strategy(strategy_id)
        _, html  = render_from_dict(data, strategy)
        expected_url_fragment = f"mvp_dashboard.html?a={account_id}"
        assert expected_url_fragment in html, \
            f"帳戶 #{account_id} CTA 按鈕應含 {expected_url_fragment}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. send_for_account DRY RUN（不發送真實郵件）
# ══════════════════════════════════════════════════════════════════════════════

class TestSendForAccount:

    def test_dry_run_missing_data_returns_false(self, tmp_path):
        """data.json 不存在時應回傳 False（不拋例外）。"""
        result = send_for_account("1", tmp_path, dry_run=True)
        assert result == "skip"   # 無資料 → skip（不算失敗）

    def test_dry_run_valid_data_returns_true(self, tmp_path):
        """data.json 存在且格式正確時，dry_run 應回傳 True。"""
        data      = _minimal_data("1", "top10")
        acct_dir  = tmp_path / "1"
        acct_dir.mkdir()
        (acct_dir / "data.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = send_for_account("1", tmp_path, dry_run=True)
        assert result == "ok"

    def test_dry_run_no_network_call(self, tmp_path):
        """dry_run 模式不應發送任何 HTTP 請求。"""
        data     = _minimal_data("2", "d2p2t6")
        data["email"]["subject"] = "[D2P2T6 #2] 2026-05-20 NAV $50,000 (+0.10%)"
        data["rankings"] = {
            "type": "universe_groups",
            "label": "D2P2T6 排名",
            "groups": [
                {"label": "軍火", "items": [
                    {"rank": 1, "symbol": "RTX", "price": 100.0,
                     "change_pct": 0.5, "in_portfolio": True},
                ]},
                {"label": "醫藥", "items": [
                    {"rank": 1, "symbol": "LLY", "price": 700.0,
                     "change_pct": -0.3, "in_portfolio": True},
                ]},
                {"label": "科技", "items": [
                    {"rank": 1, "symbol": "NVDA", "price": 900.0,
                     "change_pct": 1.0, "in_portfolio": True},
                ]},
            ],
        }
        acct_dir = tmp_path / "2"
        acct_dir.mkdir()
        (acct_dir / "data.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

        with patch("urllib.request.urlopen") as mock_url:
            result = send_for_account("2", tmp_path, dry_run=True)
            mock_url.assert_not_called()
        assert result == "ok"

    @pytest.mark.parametrize("account_id", ACCOUNTS)
    def test_dry_run_all_accounts_succeed(self, tmp_path, account_id: str):
        """三個帳戶 dry_run 均能成功（不依賴磁碟 data.json）。"""
        strategy_id = ACCOUNT_STRATEGY[account_id]
        data = _minimal_data(account_id, strategy_id)
        # D2P2T6 (account #2) 用 universe_groups ranking
        if strategy_id == "d2p2t6":
            data["rankings"] = {
                "type": "universe_groups",
                "label": "D2P2T6 排名",
                "groups": [
                    {"label": "軍火", "items": [
                        {"rank": 1, "symbol": "RTX", "price": 100.0,
                         "change_pct": 0.5, "in_portfolio": True},
                    ]},
                    {"label": "醫藥", "items": []},
                    {"label": "科技", "items": []},
                ],
            }
        acct_dir = tmp_path / account_id
        acct_dir.mkdir()
        (acct_dir / "data.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = send_for_account(account_id, tmp_path, dry_run=True)
        assert result == "ok", f"帳戶 #{account_id} dry_run 應成功"

    def test_unknown_account_returns_false(self, tmp_path):
        """未知帳戶 ID 應回傳 False。"""
        result = send_for_account("99", tmp_path, dry_run=True)
        assert result == "skip"   # 無 data.json → skip


# ══════════════════════════════════════════════════════════════════════════════
# 4. 已生成的 data.json 結構（需要 mvp_data/ 目錄存在）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("account_id", ACCOUNTS)
class TestDataJsonStructure:

    def test_email_section_exists(self, account_id: str):
        data_path = MVP_DATA_DIR / account_id / "data.json"
        if not data_path.exists():
            pytest.skip(f"mvp_data/{account_id}/data.json 尚未生成")
        data = json.loads(data_path.read_text(encoding="utf-8"))
        assert "email" in data, f"帳戶 #{account_id} data.json 缺少 email 欄位"

    def test_email_subject_not_empty(self, account_id: str):
        data_path = MVP_DATA_DIR / account_id / "data.json"
        if not data_path.exists():
            pytest.skip(f"mvp_data/{account_id}/data.json 尚未生成")
        data    = json.loads(data_path.read_text(encoding="utf-8"))
        subject = data.get("email", {}).get("subject", "")
        assert subject, f"帳戶 #{account_id} email.subject 不應為空"

    def test_email_subject_contains_nav(self, account_id: str):
        data_path = MVP_DATA_DIR / account_id / "data.json"
        if not data_path.exists():
            pytest.skip(f"mvp_data/{account_id}/data.json 尚未生成")
        data    = json.loads(data_path.read_text(encoding="utf-8"))
        subject = data.get("email", {}).get("subject", "")
        assert "NAV" in subject, \
            f"帳戶 #{account_id} subject 應含 'NAV'，實際：{subject!r}"

    def test_email_subject_contains_date(self, account_id: str):
        data_path = MVP_DATA_DIR / account_id / "data.json"
        if not data_path.exists():
            pytest.skip(f"mvp_data/{account_id}/data.json 尚未生成")
        data         = json.loads(data_path.read_text(encoding="utf-8"))
        subject      = data.get("email", {}).get("subject", "")
        trading_date = data.get("meta", {}).get("trading_date", "")
        assert trading_date in subject, \
            f"帳戶 #{account_id} subject 應含交易日期 {trading_date!r}"

    def test_data_json_renders_without_exception(self, account_id: str):
        """已生成的 data.json 應可直接渲染成 HTML（不拋例外）。"""
        data_path = MVP_DATA_DIR / account_id / "data.json"
        if not data_path.exists():
            pytest.skip(f"mvp_data/{account_id}/data.json 尚未生成")
        data        = json.loads(data_path.read_text(encoding="utf-8"))
        strategy_id = ACCOUNT_STRATEGY[account_id]
        strategy    = json.loads(
            (ROOT / "strategies" / f"{strategy_id}.json").read_text(encoding="utf-8")
        )
        subject, html = render_from_dict(data, strategy)
        assert subject, "渲染後 subject 不應為空"
        assert html,    "渲染後 HTML 不應為空"


# ══════════════════════════════════════════════════════════════════════════════
# 5. accounts.json → 策略對應完整性（動態建構，取代舊硬編 dict）
# ══════════════════════════════════════════════════════════════════════════════

class TestAccountStrategyMapping:

    def test_mapping_built_from_accounts_json(self):
        """account_strategy_map() 應為 accounts.json 內每個帳戶建表。"""
        accts = json.loads((ROOT / "accounts.json").read_text(encoding="utf-8"))["accounts"]
        expected_ids = {str(a["id"]) for a in accts if a.get("strategy")}
        assert set(ACCOUNT_STRATEGY.keys()) == expected_ids, \
            "對應表帳戶 id 應與 accounts.json 一致"

    def test_mapping_not_hardcoded(self):
        """確認對應表反映 accounts.json 的真實 strategy（不是過時硬編值）。"""
        accts = json.loads((ROOT / "accounts.json").read_text(encoding="utf-8"))["accounts"]
        for a in accts:
            if a.get("strategy"):
                assert ACCOUNT_STRATEGY[str(a["id"])] == a["strategy"], \
                    f"帳戶 #{a['id']} 對應表 strategy 與 accounts.json 不符"

    def test_strategy_files_exist(self):
        for account_id, strategy_id in ACCOUNT_STRATEGY.items():
            path = ROOT / "strategies" / f"{strategy_id}.json"
            assert path.exists(), \
                f"帳戶 #{account_id} 策略檔不存在：{path}"

    def test_all_strategy_files_have_email_section(self):
        for account_id, strategy_id in ACCOUNT_STRATEGY.items():
            path = ROOT / "strategies" / f"{strategy_id}.json"
            if not path.exists():
                continue
            cfg = json.loads(path.read_text(encoding="utf-8"))
            assert "email" in cfg, \
                f"策略 {strategy_id}.json 缺少 email 設定"
            assert "sections" in cfg["email"], \
                f"策略 {strategy_id}.json 缺少 email.sections"
            assert len(cfg["email"]["sections"]) > 0, \
                f"策略 {strategy_id}.json email.sections 不應為空"
