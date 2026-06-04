"""CT-BREAK-DETECT — schema 破壞性變更偵測（fork 相容性計劃 §6.2）。

兩層：
  1) 對 scripts/schema_compat.breaking_changes 的確定性單元測試（合成 old/new 對）
  2) git 基線守門：每個 schema 對「上一個基線（tag / origin/main / HEAD~1）」比對，
     若同名 schema 出現破壞性變更 → fail（刻意破版應 bump 檔名，舊檔不動）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.schema_compat import breaking_changes  # noqa: E402


# ── 1) 確定性單元測試 ─────────────────────────────────────────────────────────
def test_added_required_is_breaking():
    old = {"type": "object", "required": ["a"]}
    new = {"type": "object", "required": ["a", "b"]}
    assert any("required" in c for c in breaking_changes(old, new))


def test_removed_required_is_ok():
    old = {"type": "object", "required": ["a", "b"]}
    new = {"type": "object", "required": ["a"]}
    assert breaking_changes(old, new) == []


def test_additional_properties_tightened_is_breaking():
    assert breaking_changes({"additionalProperties": True},
                            {"additionalProperties": False})


def test_additional_properties_loosened_is_ok():
    assert breaking_changes({"additionalProperties": False},
                            {"additionalProperties": True}) == []


def test_removed_property_under_strict_is_breaking():
    old = {"additionalProperties": False, "properties": {"a": {}, "b": {}}}
    new = {"additionalProperties": False, "properties": {"a": {}}}
    assert any("移除" in c for c in breaking_changes(old, new))


def test_added_optional_property_is_ok():
    old = {"additionalProperties": False, "properties": {"a": {}}}
    new = {"additionalProperties": False, "properties": {"a": {}, "b": {}}}
    assert breaking_changes(old, new) == []


def test_enum_narrowed_is_breaking():
    assert any("enum" in c for c in breaking_changes(
        {"enum": ["x", "y", "z"]}, {"enum": ["x", "y"]}))


def test_enum_widened_is_ok():
    assert breaking_changes({"enum": ["x"]}, {"enum": ["x", "y"]}) == []


def test_type_narrowed_is_breaking():
    assert any("type" in c for c in breaking_changes(
        {"type": ["string", "null"]}, {"type": "string"}))


def test_type_widened_is_ok():
    assert breaking_changes({"type": "string"},
                            {"type": ["string", "null"]}) == []


def test_tightened_minimum_is_breaking():
    assert any("minimum" in c for c in breaking_changes(
        {"minimum": 0}, {"minimum": 1}))


def test_new_pattern_is_breaking():
    assert any("pattern" in c for c in breaking_changes(
        {}, {"pattern": "^x$"}))


def test_nested_property_change_detected():
    old = {"properties": {"meta": {"required": ["a"]}}}
    new = {"properties": {"meta": {"required": ["a", "b"]}}}
    assert any("meta" in c for c in breaking_changes(old, new))


def test_each_current_schema_is_compatible_with_itself():
    """每個 schema 與自身比對應為零破壞（comparator 健全性）。"""
    import json
    for f in _schema_files():
        d = json.loads(f.read_text(encoding="utf-8"))
        assert breaking_changes(d, d) == [], f"{f.name} 與自身比對不應有破壞"


# ── 2) git 基線守門 ──────────────────────────────────────────────────────────
def _schema_files() -> list[Path]:
    return (sorted((ROOT / "schemas").glob("*.json"))
            + sorted((ROOT / "strategies").glob("strategy-schema-*.json"))
            + sorted((ROOT / "brokers").glob("broker-schema-*.json")))


def _baseline_ref() -> str | None:
    for cmd in (["git", "describe", "--tags", "--abbrev=0"],
                ["git", "rev-parse", "origin/main"],
                ["git", "rev-parse", "HEAD~1"]):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def test_no_breaking_schema_change_vs_baseline():
    import json
    ref = _baseline_ref()
    if not ref:
        pytest.skip("找不到 git 基線（無 tag / origin/main / HEAD~1）")
    problems = {}
    for f in _schema_files():
        rel = f.relative_to(ROOT).as_posix()
        old = subprocess.run(["git", "show", f"{ref}:{rel}"],
                             capture_output=True, text=True, cwd=ROOT)
        if old.returncode != 0:
            continue  # 基線無此檔＝新增 schema，無破壞可言
        bc = breaking_changes(json.loads(old.stdout),
                              json.loads(f.read_text(encoding="utf-8")))
        if bc:
            problems[rel] = bc
    assert not problems, (
        "同名 schema 出現破壞性變更（會打爆未同步的 fork）；刻意破版請 bump 檔名：\n"
        + "\n".join(f"  {k}:\n    " + "\n    ".join(v) for k, v in problems.items()))
