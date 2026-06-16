"""幣別感知郵件：TWD→NT$、其餘→$（對齊 dashboard resolveCurrency）。

回歸事故：SinoPac（台股 TWD）帳戶 #6 的每日郵件把 NT$ 金額顯示成 "$"，
使 NT$4,750 看起來像 US$4,750。修法：data.json 帶 meta.currency、
email_renderer 依此選符號。
"""
from types import SimpleNamespace as NS

from engine.email_renderer import _currency_symbol, _money, _section_kpi
from engine.data_writer import _account_currency, build_meta


# ── _currency_symbol：與 dashboard resolveCurrency 對齊 ────────────────────────
def test_currency_symbol_twd():
    assert _currency_symbol({"meta": {"currency": "TWD"}}) == "NT$"


def test_currency_symbol_usd():
    assert _currency_symbol({"meta": {"currency": "USD"}}) == "$"


def test_currency_symbol_default_when_missing():
    # 舊 data.json 無 currency → 預設 $（向後相容，不影響既有美股帳戶）
    assert _currency_symbol({}) == "$"
    assert _currency_symbol({"meta": {}}) == "$"


# ── _money：符號可注入，預設維持 "$"（向後相容）─────────────────────────────
def test_money_default_symbol_unchanged():
    assert _money(1234.5) == "$1,234.50"


def test_money_ntd_symbol():
    assert _money(1234.5, "NT$") == "NT$1,234.50"


def test_money_negative_keeps_sign_after_symbol():
    assert _money(-5, "NT$") == "NT$−5.00"


# ── KPI 卡片端到端（重現 #6 情境）─────────────────────────────────────────────
def _kpi_data(currency):
    return {
        "meta": {"currency": currency},
        "summary": {
            "nav": 4750, "cash": 0,
            "today_change": 130.0, "today_change_pct": 2.81,
            "total_return_pct_twr": 5.32, "ytd_return_pct": None,
            "inception_date": "2026-06-10",
        },
    }


def test_kpi_twd_renders_ntd():
    html = _section_kpi(_kpi_data("TWD"), "#38bdf8")
    assert "NT$4,750" in html        # NAV
    assert "NT$0" in html            # 現金
    assert "NT$130.00" in html       # 今日損益


def test_kpi_usd_renders_dollar():
    html = _section_kpi(_kpi_data("USD"), "#38bdf8")
    assert "$4,750" in html
    assert "NT$" not in html         # 美股帳戶不應出現 NT$


# ── data_writer：幣別來源（broker spec 的 market.currency）─────────────────────
def test_account_currency_sinopac_is_twd():
    assert _account_currency(NS(broker="sinopac")) == "TWD"


def test_account_currency_alpaca_is_usd():
    assert _account_currency(NS(broker="alpaca")) == "USD"


def test_account_currency_default_usd():
    assert _account_currency(NS(broker=None)) == "USD"


# ── build_meta 把 currency 寫進 data.json 的 meta ─────────────────────────────
def test_build_meta_includes_currency():
    strat = {"id": "tech_top10", "dashboard": {"accent_color": "#38bdf8"}}
    acc = NS(id="6", label="sini")
    meta = build_meta(strat, acc, [acc], currency="TWD")
    assert meta["currency"] == "TWD"
