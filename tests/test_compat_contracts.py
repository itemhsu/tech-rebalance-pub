"""CT-VER / CT-SEL / CT-EVT — 版本欄位 lint + 字串耦合完整性（fork 相容性計劃 §6.1 ②⑦）。

字串耦合是 fork 最隱形的地雷：策略 JSON 用字串指向 selection method、
trade event 用字串 type 跨三個消費端傳遞。上游改名/移除而 fork 沒跟上 → 執行期才炸。
這些測試把「字串契約」在 CI 就鎖住。
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _is_schema_file(path: str) -> bool:
    return "schema" in os.path.basename(path)


def _real_strategies() -> list[str]:
    return [f for f in glob.glob(str(ROOT / "strategies" / "*.json"))
            if not _is_schema_file(f)]


# ── CT-VER-PRESENT：每個可版本化產物都帶版本標記 ─────────────────────────────
def test_json_schema_files_have_id():
    """所有 JSON Schema 檔須有 $id（可識別/可版本化）。"""
    schemas = (glob.glob(str(ROOT / "schemas" / "*.json"))
               + glob.glob(str(ROOT / "strategies" / "strategy-schema-*.json"))
               + glob.glob(str(ROOT / "brokers" / "broker-schema-*.json")))
    missing = [os.path.relpath(f, ROOT) for f in schemas
               if "$id" not in json.loads(Path(f).read_text(encoding="utf-8"))]
    assert not missing, f"JSON Schema 檔缺 $id（無法版本化）：{missing}"


def test_strategy_jsons_declare_schema_and_version():
    """每個真策略須宣告 $schema（指向哪份 schema）+ version。"""
    bad = []
    for f in _real_strategies():
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        miss = [k for k in ("$schema", "version") if k not in d]
        if miss:
            bad.append((os.path.basename(f), miss))
    assert not bad, f"策略缺版本標記：{bad}"


def test_broker_defs_declare_id_and_version():
    """每個券商定義 JSON（非 schema）須有 id + version。"""
    bad = []
    for f in glob.glob(str(ROOT / "brokers" / "*.json")):
        if _is_schema_file(f):
            continue
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        miss = [k for k in ("id", "version") if k not in d]
        if miss:
            bad.append((os.path.basename(f), miss))
    assert not bad, f"券商定義缺 id/version：{bad}"


# ── CT-SEL：策略用到的 selection.method 都必須已註冊 ─────────────────────────
def test_all_strategy_methods_are_registered():
    from engine.selection import _METHODS
    registered = set(_METHODS)
    unknown = []
    for f in _real_strategies():
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        method = (d.get("selection") or {}).get("method")
        if method is None:
            continue  # 部分 v1/benchmark 策略無 selection.method（走預設路徑）
        if method not in registered:
            unknown.append((os.path.basename(f), method))
    assert not unknown, (
        f"策略引用了 selection.py 未註冊的 method：{unknown}；"
        f"已註冊：{sorted(registered)}。改/移除 method 名稱會打爆 fork 舊策略——"
        "請用別名表保留舊名。")


# ── CT-EVT：消費端引用的 event type 都必須是生產端會發出的 ────────────────────
_TYPE_RE = re.compile(r"\b(ORDER_[A-Z]+|REBALANCE_[A-Z]+)\b")


def _producer_event_types() -> set[str]:
    """trade_log.py（生產端）會寫出的所有 event type 字串。"""
    text = (ROOT / "trade_log.py").read_text(encoding="utf-8")
    # 只取被當成字面值 "TYPE" 寫出的（避免抓到函式名等）
    return set(re.findall(r'"(ORDER_[A-Z]+|REBALANCE_[A-Z]+)"', text))


def _consumer_files() -> list[Path]:
    return [ROOT / "trader.py",
            ROOT / "engine" / "report_generator.py",
            ROOT / "docs" / "log" / "index.html"]


def test_consumers_only_reference_emitted_event_types():
    produced = _producer_event_types()
    assert produced, "trade_log.py 找不到任何 event type 字面值（解析失敗？）"
    phantom = {}
    for f in _consumer_files():
        if not f.exists():
            continue
        refs = set(_TYPE_RE.findall(f.read_text(encoding="utf-8")))
        extra = refs - produced
        if extra:
            phantom[f.name] = sorted(extra)
    assert not phantom, (
        f"消費端引用了生產端不存在的 event type（改名/拼錯→默默讀不到）：{phantom}；"
        f"生產端實際發出：{sorted(produced)}")
