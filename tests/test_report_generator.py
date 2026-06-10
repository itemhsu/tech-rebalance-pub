"""資料驅動報告產生器：Parity（新=舊）+ 每帳戶有效 + resolver 單元（提案 R-01~R-06）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# accounts.json 是執行期產物（run-account / 部署時 provision），fresh clone 沒有 →
# 整個模組以指名理由 skip，不靜默、不假綠。
if not (ROOT / "accounts.json").exists():
    pytest.skip(
        "requires runtime artifact: accounts.json — provisioned at runtime by "
        "run-account (CI or dev repo); absent in a fresh clone",
        allow_module_level=True,
    )

from engine.report_generator import (
    generate_for_account, can_generate, is_grouped,
    resolve_holdings, resolve_rankings,
)
from engine.accounts import get_account, load_accounts
from engine.data_validator import validate_data_json
from engine.strategy_loader import load_and_validate

# label 是刻意改用 accounts.json 真實值；generated_at 是時間戳 → 比對時忽略
_IGNORE_META = {"generated_at", "account_label", "same_strategy_accounts"}


def _canon(d):
    d = dict(d)
    if "meta" in d:
        d["meta"] = {k: v for k, v in d["meta"].items() if k not in _IGNORE_META}
    # rankings 現在用 positions 真實股價（取代舊 $100 placeholder）→ 比對只看結構
    if isinstance(d.get("rankings"), dict):
        items = d["rankings"].get("items", [])
        d["rankings"] = dict(d["rankings"],
                             items=[{k: it.get(k) for k in ("rank", "symbol", "in_portfolio")}
                                    for it in items])
    return d


# ── R-03：泛用產生器輸出含真實股價（舊的 migrate_top10 parity 已隨函式移除）──────
def test_top10_rankings_real_prices(tmp_path):
    generate_for_account(get_account("1"), tmp_path / "new")
    new = json.loads((tmp_path / "new" / "1" / "data.json").read_text("utf-8"))
    prices = [it["price"] for it in new["rankings"]["items"]]
    assert any(p not in (0.0, 100.0) for p in prices), "rankings 應為真實股價"


# ── R-04：accounts.json 每個 enabled 帳戶都能產出有效報告（#3 漏接會被擋下）──
@pytest.mark.parametrize("account", [a for a in load_accounts() if a.enabled],
                         ids=lambda a: f"#{a.id}-{a.strategy}")
def test_every_account_generates_valid(tmp_path, account):
    if not can_generate(account):
        pytest.skip("分組排名（universe_groups）由既有 migrator 處理")
    status = generate_for_account(account, tmp_path)
    if status == "skip":
        return                                   # 無資料帳戶 → 合法略過
    data = json.loads((tmp_path / account.id / "data.json").read_text("utf-8"))
    validate_data_json(data)                     # schema 全過
    subj = data["email"]["subject"]
    assert account.id in subj                    # 主旨含帳戶 id（不會張冠李戴）
    if "cta" in load_and_validate(account.strategy)["email"]["sections"]:
        assert data["email"].get("dashboard_url")  # cta 三按鈕有 URL 可渲染


# ── R-01 resolve_holdings ────────────────────────────────────────────────
def test_resolve_holdings_fallback():
    assert resolve_holdings({"top10": ["AAPL", "MSFT"]}) == ["AAPL", "MSFT"]
    assert resolve_holdings({"target_weights": {"RTX": .5, "LLY": .5}}) == ["RTX", "LLY"]
    assert resolve_holdings({"positions": [{"symbol": "NVDA"}]}) == ["NVDA"]


# ── R-02 resolve_rankings / is_grouped ───────────────────────────────────
def test_resolve_rankings_ranked_stocks():
    rs = [{"rank": 1, "symbol": "AAPL"}]
    assert resolve_rankings({"ranked_stocks": rs}, {}) == rs


def test_resolve_rankings_scorecard_maps():
    out = resolve_rankings({"scorecard": [{"symbol": "AAPL", "score": 3}]}, {})
    assert out[0]["sym"] == "AAPL" and out[0]["rank"] == 1


def test_grouped_routes_to_legacy():
    # d2p2t6 宣告 universe_groups（用 type 宣告）→ 不走泛用
    assert is_grouped(load_and_validate("d2p2t6")) is True
    assert resolve_rankings({}, load_and_validate("d2p2t6")) is None
    # top10 / mom 非分組 → 走泛用
    assert is_grouped(load_and_validate("top10")) is False


# ── R-06 無資料 → skip ───────────────────────────────────────────────────
def test_missing_state_skips(tmp_path):
    from engine.accounts import Account
    acct = Account(id="99", strategy="top10", label="x", data_dir="data/__nope__")
    assert generate_for_account(acct, tmp_path) == "skip"


# ── 訂單異常告警（email 紅色橫幅）─────────────────────────────────────────
def test_order_alerts_reads_recent(tmp_path, monkeypatch):
    import datetime as dt
    from engine import report_generator as rg
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    d = tmp_path / "data" / "9"; d.mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    (d / "trade_events.jsonl").write_text(
        json.dumps({"type": "ORDER_REJECTED", "ts": now, "symbol": "V", "action": "BUY", "error": "status=rejected"}) + "\n" +
        json.dumps({"type": "ORDER_STALE", "ts": now, "symbol": "AAPL", "action": "BUY", "age_days": 5}) + "\n" +
        json.dumps({"type": "ORDER_FILLED", "ts": now, "symbol": "MSFT"}) + "\n", encoding="utf-8")
    out = rg.order_alerts("data/9")
    kinds = sorted(a["kind"] for a in out)
    assert kinds == ["rejected", "stale"]
    assert any(a["symbol"] == "AAPL" and "5" in a["detail"] for a in out)


def test_email_order_alert_banner():
    from engine.email_renderer import _section_order_alerts
    html = _section_order_alerts({"order_alerts": [
        {"kind": "rejected", "symbol": "V", "action": "BUY", "detail": "status=rejected"}]})
    assert "訂單異常" in html and "V" in html and "被拒" in html
    assert _section_order_alerts({}) == ""   # 無告警 → 不顯示
