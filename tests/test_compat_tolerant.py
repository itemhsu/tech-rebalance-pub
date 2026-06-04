"""CT-FWD-TOLERANT — 向前相容：載入器忽略「未來未知欄位」不崩（fork 相容性計劃 §6.1 ⑤）。

情境：較新的上游引擎在資料檔/設定檔寫入新欄位後，較舊的 fork 讀取端必須
「忽略不認得的欄位、補預設」而非崩潰（Postel 法則）。這些測試把容忍度鎖成回歸基線，
避免日後有人把寬鬆讀改成 strict（例如直接 Account(**a) 而不過濾）而悄悄破壞舊 fork。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_FUTURE = "__future_field_from_newer_upstream__"


# ── accounts.json：Account 模型忽略未知欄位 ─────────────────────────────────
def test_account_loader_ignores_unknown_fields(tmp_path):
    from engine.accounts import load_accounts
    payload = {"accounts": [{
        "id": "9", "strategy": "top10", "label": "未來帳戶",
        "enabled": True, "data_dir": "data/9",
        _FUTURE: {"nested": [1, 2, 3]},          # 未來新欄位
        "another_future_scalar": "v2.0",
    }]}
    p = tmp_path / "accounts.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    accounts = load_accounts(path=p)              # 不應拋例外
    assert len(accounts) == 1
    a = accounts[0]
    assert a.id == "9" and a.strategy == "top10" and a.label == "未來帳戶"


# ── universe JSON：只取需要的 key，額外頂層欄位忽略 ─────────────────────────
def test_universe_json_loader_ignores_extra_keys(tmp_path, monkeypatch):
    import engine.universe_loader as ul
    uni = tmp_path / "universe_future.json"
    uni.write_text(json.dumps({
        "stocks": ["aapl", "MSFT", "nvda"],
        "last_updated": "2030-01-01",
        _FUTURE: {"schema_rev": 7},               # 未來新增的頂層欄位
    }), encoding="utf-8")
    monkeypatch.setattr(ul, "_ROOT", tmp_path)    # 讓相對路徑指向 tmp
    spec = {"universe": {"type": "single",
                         "source": {"type": "json_file",
                                    "path": "universe_future.json", "key": "stocks"}}}
    groups = ul.load_universe_groups(spec)
    assert groups["__all__"] == ["AAPL", "MSFT", "NVDA"]


# ── inline 來源：source 內多餘 key 忽略 ─────────────────────────────────────
def test_universe_inline_source_ignores_extra_keys():
    from engine.universe_loader import load_universe_groups
    spec = {"universe": {"type": "single",
                         "source": {"type": "inline", "symbols": ["v", "ma"],
                                    _FUTURE: "ignored"}}}
    assert load_universe_groups(spec)["__all__"] == ["V", "MA"]


# ── broker spec：消費端對未知欄位寬鬆（resolve_env_vars 仍運作）──────────────
def test_broker_spec_consumer_tolerates_unknown(monkeypatch):
    from brokers.registry import load_broker_spec, resolve_env_vars
    spec = load_broker_spec("alpaca")
    spec[_FUTURE] = {"future": True}              # 注入未來欄位
    monkeypatch.setenv("PFX_ALPACA_KEY", "k")     # 不依賴真金鑰；只驗證不崩
    monkeypatch.setenv("PFX_API_KEY", "k")
    monkeypatch.setenv("PFX_API_SECRET", "s")
    out = resolve_env_vars(spec, "PFX", "paper")  # 不應因未知頂層欄位拋例外
    assert isinstance(out, dict)


# ── 持倉快照：report_generator 取持股時忽略未知 state 欄位 ────────────────────
def test_state_reader_tolerates_unknown_fields():
    from engine.report_generator import resolve_holdings
    state = {
        "date": "2026-06-03", "nav": 100000.0, "cash": 0.0,
        "top10": ["AAPL", "MSFT", "NVDA"],
        _FUTURE: {"v": 2}, "another_future": [1, 2],
    }
    assert resolve_holdings(state) == ["AAPL", "MSFT", "NVDA"]
