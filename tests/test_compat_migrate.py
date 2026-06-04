"""CT-MIGRATE-RT — 生成管線 idempotent + 不丟欄位（fork 相容性計劃 §6.1 ⑧）。

本系統沒有獨立的 vN→vN+1 schema 遷移腳本；真正每日跑的「遷移」是
portfolio_state → data.json 的生成管線（engine.data_writer.write_data_json）。
此處用 golden 樣本驗證該管線：
  - idempotent：同輸入跑兩次 → 輸出一致（除 meta.generated_at 時戳）→ 無虛假 churn
  - lossless：來源 state 的核心事實（nav/positions/date）原封不動進到 data.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "tests" / "fixtures" / "golden"


def _latest_golden() -> Path | None:
    vers = sorted(p for p in GOLDEN.iterdir() if p.is_dir()) if GOLDEN.exists() else []
    return vers[-1] if vers else None


def _generate(vdir: Path, tmp: Path) -> dict:
    """用 golden state + strategy 跑一次 write_data_json，回傳 data dict。"""
    from engine.accounts import Account
    from engine.data_writer import write_data_json
    from engine.strategy_loader import load_and_validate
    from engine.report_generator import resolve_holdings, resolve_rankings

    state = json.loads((vdir / "portfolio_state.json").read_text(encoding="utf-8"))
    sdir = vdir / "strategies"
    # 取 golden 裡任一 v3 策略（與帳戶3 相符）；找不到就用第一個
    strat_id = "mom_6m_t20" if (sdir / "mom_6m_t20.json").exists() else \
        next(sdir.glob("*.json")).stem
    strat = load_and_validate(strat_id, strategies_dir=sdir)

    account = Account(id="3", strategy=strat_id, label="golden",
                      data_dir=str(vdir))
    holdings = resolve_holdings(state)
    rankings = resolve_rankings(state, strat)

    return write_data_json(
        output_path            = tmp / "3" / "data.json",
        strategy_cfg           = strat,
        account                = account,
        same_strategy_accounts = [account],
        nav                    = state["nav"],
        cash                   = state["cash"],
        positions              = state.get("positions", []),
        top_n_symbols          = holdings,
        executed_orders        = [],
        rankings_raw           = rankings,
        trading_date           = state["date"],
        dry_run                = False,
        existing_data          = None,
    )


_VOLATILE = ["meta.generated_at"]


def _strip_volatile(d: dict) -> dict:
    import copy
    d = copy.deepcopy(d)
    for path in _VOLATILE:
        cur = d
        *parents, leaf = path.split(".")
        for p in parents:
            cur = cur.get(p, {}) if isinstance(cur, dict) else {}
        if isinstance(cur, dict):
            cur.pop(leaf, None)
    return d


def test_generation_is_idempotent(tmp_path):
    vdir = _latest_golden()
    if not vdir:
        pytest.skip("無 golden corpus")
    a = _generate(vdir, tmp_path / "run1")
    b = _generate(vdir, tmp_path / "run2")
    assert _strip_volatile(a) == _strip_volatile(b), \
        "同輸入兩次生成結果不一致（非確定性 → 會造成 dashboard 虛假 churn）"


def test_generation_is_lossless_for_core_facts(tmp_path):
    vdir = _latest_golden()
    if not vdir:
        pytest.skip("無 golden corpus")
    state = json.loads((vdir / "portfolio_state.json").read_text(encoding="utf-8"))
    data = _generate(vdir, tmp_path / "run")

    # nav / 交易日原封保留
    assert data["summary"]["nav"] == state["nav"]
    assert data["meta"]["trading_date"] == state["date"]

    # 持倉代號不遺漏（state.positions ⊆ data.positions）
    state_syms = {p["symbol"] for p in state.get("positions", [])}
    data_syms = {p["symbol"] for p in data.get("positions", [])}
    assert state_syms <= data_syms, f"持倉遺漏：{state_syms - data_syms}"


def test_generated_data_passes_schema(tmp_path):
    """round-trip 產物本身仍須通過現行 data-schema。"""
    vdir = _latest_golden()
    if not vdir:
        pytest.skip("無 golden corpus")
    from engine.data_validator import validate_data_json
    validate_data_json(_generate(vdir, tmp_path / "run"))
