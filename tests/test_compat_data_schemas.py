"""B 類資料檔形式 schema 驗證（fork 相容性計劃 §6.4-⑥）。

#4–9 這些 de-facto schema 過去無形式驗證，改鍵名只會在執行期炸。
此處給它們補上「寬鬆」JSON Schema（require 核心欄位、additionalProperties:true
允許未來欄位），並驗證 live 檔 + golden 樣本都符合。
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, validate

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SCHEMAS = ROOT / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


# ── schema 本身合法 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "accounts-schema-v1.json", "universe-schema-v1.json",
    "shares-outstanding-schema-v1.json", "portfolio-state-schema-v1.json",
    "portfolio-state-history-schema-v1.json", "trade-event-schema-v1.json",
])
def test_schema_is_valid_draft7(name):
    Draft7Validator.check_schema(_schema(name))


# ── live 檔符合各自 schema ───────────────────────────────────────────────────
def test_accounts_json_conforms():
    validate(_load(ROOT / "accounts.json"), _schema("accounts-schema-v1.json"))


def test_universe_json_conforms():
    validate(_load(ROOT / "data" / "universe.json"), _schema("universe-schema-v1.json"))


def test_shares_outstanding_conforms():
    validate(_load(ROOT / "data" / "shares_outstanding.json"),
             _schema("shares-outstanding-schema-v1.json"))


def test_all_portfolio_states_conform():
    sch = _schema("portfolio-state-schema-v1.json")
    files = glob.glob(str(ROOT / "data" / "*" / "portfolio_state.json"))
    assert files, "找不到任何 portfolio_state.json"
    for f in files:
        validate(_load(Path(f)), sch)


def test_all_state_histories_conform():
    sch = _schema("portfolio-state-history-schema-v1.json")
    for f in glob.glob(str(ROOT / "data" / "*" / "portfolio_state_history.json")):
        d = _load(Path(f))
        if "history" in d:                # 僅驗證有 history 結構者
            validate(d, sch)


def test_trade_events_lines_conform():
    sch = _schema("trade-event-schema-v1.json")
    files = glob.glob(str(ROOT / "data" / "*" / "trade_events.jsonl"))
    assert files, "找不到任何 trade_events.jsonl"
    checked = 0
    for f in files:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            validate(json.loads(line), sch)
            checked += 1
    assert checked > 0, "沒有任何事件被驗證"


# ── golden 樣本也符合（向後相容 × 形式 schema）────────────────────────────────
def test_golden_accounts_and_state_conform():
    gdir = ROOT / "tests" / "fixtures" / "golden"
    if not gdir.exists():
        pytest.skip("無 golden corpus")
    for vdir in (p for p in gdir.iterdir() if p.is_dir()):
        if (vdir / "accounts.json").exists():
            validate(_load(vdir / "accounts.json"), _schema("accounts-schema-v1.json"))
        if (vdir / "portfolio_state.json").exists():
            validate(_load(vdir / "portfolio_state.json"),
                     _schema("portfolio-state-schema-v1.json"))


# ── 向前相容：注入未來未知欄位仍通過（additionalProperties:true）─────────────
def test_schemas_allow_future_unknown_fields():
    cases = [
        ("accounts-schema-v1.json",
         {"accounts": [{"id": "1", "strategy": "x", "__future__": 1}], "__top_future__": 2}),
        ("universe-schema-v1.json", {"stocks": ["AAPL"], "__future__": True}),
        ("portfolio-state-schema-v1.json",
         {"date": "2026-06-03", "nav": 1.0, "cash": 0.0,
          "positions": [{"symbol": "AAPL", "qty": 1, "__f__": 9}], "__future__": "ok"}),
        ("trade-event-schema-v1.json",
         {"ts": "t", "type": "ORDER_FUTURE_KIND", "account": "1", "strategy": "x", "__f__": 1}),
    ]
    for name, doc in cases:
        validate(doc, _schema(name))      # 未知欄位 + 未來 event type 都不應拒
