"""pyproject 打包守門（兩 repo 架構 P1a）。

保證引擎可 pip 安裝、CLI entry point 存在、relative 資產可由 package_root 定位。
完整 wheel 內含 strategies/schemas（給第三方安裝）屬 P1b，待資產搬入套件後補。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_pyproject_declares_package_and_cli():
    txt = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "tech-rebalance"' in txt
    assert "version = " in txt
    assert 'run-account = "run_account:main"' in txt   # CLI entry point
    # 執行時相依（非 dev）
    for dep in ("alpaca-py", "requests", "jsonschema", "pandas"):
        assert dep in txt


def test_run_account_main_is_callable():
    import run_account
    assert callable(run_account.main)


def test_main_parses_args_without_executing(monkeypatch):
    """--help 應在解析階段即退出（不需任何金鑰/網路）。"""
    import run_account
    import pytest
    with pytest.raises(SystemExit) as ei:
        run_account.main(["--help"])
    assert ei.value.code == 0


def test_engine_assets_resolvable_via_package_root():
    from engine.paths import package_root
    p = package_root()
    assert (p / "strategies" / "top10.json").exists()
    assert (p / "schemas" / "data-schema-v1.json").exists()
    assert (p / "brokers" / "alpaca.json").exists()


def test_assets_bundled_into_wheel_config():
    """P1b：strategies/ schemas/ 須是套件 + 宣告 package-data，wheel 才含 *.json。"""
    assert (ROOT / "strategies" / "__init__.py").exists()
    assert (ROOT / "schemas" / "__init__.py").exists()
    assert (ROOT / "data" / "__init__.py").exists()
    txt = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'strategies = ["*.json"]' in txt
    assert 'schemas = ["*.json"]' in txt
    assert '"strategies*"' in txt and '"schemas*"' in txt and '"data*"' in txt
    # data/ 只包引擎參考資料兩檔（使用者 state 不進 wheel）
    assert '"universe.json"' in txt and '"shares_outstanding.json"' in txt


def test_engine_refdata_resolvable_via_package_root():
    """選股需要的 data/universe.json + shares_outstanding.json 隨引擎可定位。"""
    from engine.paths import package_root
    p = package_root()
    assert (p / "data" / "universe.json").exists()
    assert (p / "data" / "shares_outstanding.json").exists()
