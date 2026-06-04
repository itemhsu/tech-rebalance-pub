"""engine/paths.py 與 TR_WORKDIR 解耦驗收（兩 repo 架構 P0）。

證明：未設 TR_WORKDIR → 行為與舊版相同（workdir==package_root）；
設了 → 使用者設定/資料(accounts.json)解析到外部目錄，引擎資產(strategies)不動。
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_default_workdir_equals_package_root(monkeypatch):
    monkeypatch.delenv("TR_WORKDIR", raising=False)
    import engine.paths as paths
    importlib.reload(paths)
    assert paths.workdir() == paths.package_root()


def test_tr_workdir_overrides_user_location(monkeypatch, tmp_path):
    monkeypatch.setenv("TR_WORKDIR", str(tmp_path))
    import engine.paths as paths
    importlib.reload(paths)
    assert paths.workdir() == tmp_path
    # 引擎資產不受 TR_WORKDIR 影響
    assert paths.package_root() == ROOT


def test_run_account_reads_accounts_from_workdir(monkeypatch, tmp_path):
    """run_account 從 TR_WORKDIR 讀 accounts.json，不是引擎目錄。"""
    monkeypatch.setenv("TR_WORKDIR", str(tmp_path))
    (tmp_path / "accounts.json").write_text(
        json.dumps({"accounts": [{"id": "9", "strategy": "top10",
                                  "secret_prefix": "ACC9", "enabled": True}]}),
        encoding="utf-8")
    import engine.paths as paths
    importlib.reload(paths)
    import run_account
    importlib.reload(run_account)
    accts = run_account._load_accounts_json()
    assert [a["id"] for a in accts] == ["9"]      # 讀到的是 tmp 的、不是引擎的


def test_engine_assets_stay_in_package(monkeypatch, tmp_path):
    """strategies/ 等引擎資產即使設了 TR_WORKDIR 仍從 package_root 讀。"""
    monkeypatch.setenv("TR_WORKDIR", str(tmp_path))
    import engine.paths as paths
    importlib.reload(paths)
    # 引擎自帶策略仍在
    assert (paths.package_root() / "strategies" / "top10.json").exists()
    # tmp 工作目錄沒有 strategies → 證明兩者分離
    assert not (paths.workdir() / "strategies").exists()


def teardown_module(module):
    """還原 paths/run_account 模組狀態，避免污染其他測試。"""
    import engine.paths as paths
    importlib.reload(paths)
    import run_account
    importlib.reload(run_account)
