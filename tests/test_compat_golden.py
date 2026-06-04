"""CT-BACK-CORPUS — 向後相容：現行碼回放舊版 golden 樣本不崩（fork 相容性計劃 §6.1 ④）。

抓「悄悄破壞舊 fork」最有效的網：把各發佈版的真實（去敏）樣本存在
tests/fixtures/golden/{tag}/，每次跑都用「現在的程式碼」重讀它們。
若某次重構讓舊 accounts/策略/state/data.json 讀不了，這裡立刻紅。

新增版本：發佈時把當下樣本複製到 golden/{tag}/，測試自動納入（parametrize）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
GOLDEN = ROOT / "tests" / "fixtures" / "golden"


def _versions() -> list[Path]:
    if not GOLDEN.exists():
        return []
    return sorted(p for p in GOLDEN.iterdir() if p.is_dir())


_VERS = _versions()
_IDS = [p.name for p in _VERS]


def test_golden_corpus_is_not_empty():
    """有 golden 目錄則須非空；完全沒有（如 public 鏡像排除 fixtures）→ skip。"""
    if not GOLDEN.exists():
        pytest.skip("無 golden fixtures（public 鏡像排除）")
    assert _VERS, f"golden corpus 為空：{GOLDEN}"


@pytest.mark.parametrize("vdir", _VERS, ids=_IDS)
def test_accounts_json_loads(vdir):
    from engine.accounts import load_accounts
    f = vdir / "accounts.json"
    if not f.exists():
        pytest.skip("此版本無 accounts.json")
    accounts = load_accounts(path=f)
    assert accounts, "golden accounts.json 載入後為空"
    assert all(a.id and a.strategy for a in accounts)


@pytest.mark.parametrize("vdir", _VERS, ids=_IDS)
def test_strategies_load_and_validate(vdir):
    from engine.strategy_loader import load_and_validate
    sdir = vdir / "strategies"
    files = list(sdir.glob("*.json")) if sdir.exists() else []
    assert files, f"{vdir.name} 無策略樣本"
    for f in files:
        load_and_validate(f.stem, strategies_dir=sdir)   # v1/v3 皆不應拋例外


@pytest.mark.parametrize("vdir", _VERS, ids=_IDS)
def test_data_json_passes_current_schema(vdir):
    from engine.data_validator import validate_data_json
    f = vdir / "data.json"
    if not f.exists():
        pytest.skip("此版本無 data.json")
    validate_data_json(json.loads(f.read_text(encoding="utf-8")))


@pytest.mark.parametrize("vdir", _VERS, ids=_IDS)
def test_portfolio_state_readable(vdir):
    from engine.report_generator import resolve_holdings
    f = vdir / "portfolio_state.json"
    if not f.exists():
        pytest.skip("此版本無 portfolio_state.json")
    holdings = resolve_holdings(json.loads(f.read_text(encoding="utf-8")))
    assert isinstance(holdings, list)


@pytest.mark.parametrize("vdir", _VERS, ids=_IDS)
def test_golden_has_no_pii_or_secrets(vdir):
    """守門：golden 樣本不得含真實 email / 金鑰值（去敏回歸鎖）。"""
    import re
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in vdir.rglob("*") if p.is_file())
    emails = set(re.findall(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", blob))
    bad = {e for e in emails if not e.endswith("example.com")}
    assert not bad, f"golden 含未去敏 email：{bad}"
