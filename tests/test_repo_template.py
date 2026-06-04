"""tests/test_repo_template.py — repo_template.json 三層驗證測試（C-16~C-24）。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas" / "repo-template-schema-v1.json").read_text())


def _valid(doc) -> bool:
    import jsonschema
    try:
        jsonschema.validate(doc, SCHEMA)
        return True
    except jsonschema.ValidationError:
        return False


def _base():
    return {"version": "1", "repo_b": [], "dashboard": []}


# ── 第一層：Schema ──────────────────────────────────────────────────────────
def test_c16_reject_unknown_policy():
    doc = _base()
    doc["repo_b"] = [{"path": "x", "policy": "rndr"}]          # typo
    assert not _valid(doc)


def test_c17_reject_render_without_src():
    doc = _base()
    doc["repo_b"] = [{"path": "x", "policy": "render"}]        # 缺 src
    assert not _valid(doc)


def test_c18_reject_placeholder_with_src():
    doc = _base()
    doc["repo_b"] = [{"path": "x", "policy": "placeholder", "src": "templates/y"}]
    assert not _valid(doc)


def test_c18b_reject_protected_with_src():
    doc = _base()
    doc["repo_b"] = [{"path": "x", "policy": "protected", "src": "templates/y"}]
    assert not _valid(doc)


def test_schema_accepts_valid_entries():
    doc = _base()
    doc["repo_b"] = [
        {"path": ".github/workflows/daily.yml", "policy": "render", "src": "templates/daily.yml"},
        {"path": "accounts.json", "policy": "protected"},
        {"path": "data/.gitkeep", "policy": "placeholder"},
    ]
    assert _valid(doc)


def test_schema_rejects_extra_field():
    doc = _base()
    doc["repo_b"] = [{"path": "x", "policy": "protected", "bogus": 1}]
    assert not _valid(doc)


# ── 第二層 + 第三層：validator 腳本（C-19~C-21, C-24）────────────────────────
def _run_validator() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_repo_template.py")],
        capture_output=True, text=True)


def test_c24_real_manifest_passes():
    """真實 repo_template.json 必須通過全部驗證（守住自己）。"""
    r = _run_validator()
    assert r.returncode == 0, r.stdout + r.stderr


def test_real_manifest_conforms_schema():
    doc = json.loads((ROOT / "repo_template.json").read_text())
    assert _valid(doc)


def test_every_render_src_exists():
    """C-20 的正向：真實 manifest 的每個 render src 都存在。"""
    doc = json.loads((ROOT / "repo_template.json").read_text())
    for section in ("repo_b", "dashboard"):
        for e in doc[section]:
            if e["policy"] == "render":
                assert (ROOT / e["src"]).is_file(), f"missing {e['src']}"


def test_no_orphan_templates():
    """C-21 的正向：templates/ 每個檔都被引用。"""
    doc = json.loads((ROOT / "repo_template.json").read_text())
    referenced = {e["src"] for sec in ("repo_b", "dashboard")
                  for e in doc[sec] if e["policy"] == "render"}
    tdir = ROOT / "templates"
    if tdir.is_dir():
        for f in tdir.rglob("*"):
            if f.is_file():
                assert str(f.relative_to(ROOT)) in referenced, f"orphan {f}"
