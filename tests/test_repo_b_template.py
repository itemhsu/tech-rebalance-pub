"""Repo B 範本守門（兩 repo 架構 P2）。

確保薄殼範本的 accounts.json 合法、薄 workflow 正確、引擎發版 CI 存在。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import validate

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TPL = ROOT / "examples" / "repo-b-template"


def test_template_accounts_validates_against_schema():
    schema = json.loads((ROOT / "schemas" / "accounts-schema-v1.json").read_text())
    accts = json.loads((TPL / "accounts.json").read_text())
    validate(accts, schema)                     # 範本帳戶須通過引擎 schema


def test_thin_workflow_is_minimal_and_correct():
    wf = (TPL / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    import yaml
    yaml.safe_load(wf)                          # YAML 合法
    assert "TR_WORKDIR" in wf                   # 引擎讀寫本 repo
    assert "run-account --account all" in wf    # 用 CLI entry point
    assert "tech-rebalance @ git+" in wf        # 以套件安裝引擎
    assert "@v" in wf                           # 釘版本
    assert "git push" in wf                     # commit data 回本 repo


def test_engine_release_workflow_exists():
    rel = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    import yaml
    yaml.safe_load(rel)
    assert "tags:" in rel and "v*" in rel       # tag 觸發
    assert "python -m build" in rel             # 建 wheel
    assert "strategies/" in rel and "schemas/" in rel   # 驗證資產有打包


def test_template_has_no_real_secrets():
    """範本不得含真實金鑰/個人 email。"""
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in TPL.rglob("*") if p.is_file())
    import re
    emails = {e for e in re.findall(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", blob)
              if not e.endswith("example.com") and "noreply" not in e}
    assert not emails, f"範本含真實 email：{emails}"
    assert "ALPACA_KEY=" not in blob or "secrets." in blob   # 金鑰只能是 secrets 參照
