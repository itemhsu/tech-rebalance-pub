"""
tests/test_unit12_smoke.py — Unit 12: 端對端煙霧測試

驗證完整部署管線產出的靜態資產正確性：
  - accounts.json 格式正確
  - mvp_dashboard.html 存在且含必要元素
  - mvp_data/1/data.json 通過 schema 驗證（若存在）
  - mvp_data/2/data.json 通過 schema 驗證（若存在）
  - 遷移腳本 --strategy 旗標正確運作
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.accounts import load_accounts
from engine.data_validator import validate_data_json

MVP_DATA = ROOT / "mvp_data"
ACCOUNTS_JSON    = ROOT / "accounts.json"
DASHBOARD_HTML   = ROOT / "mvp_dashboard.html"


# ══════════════════════════════════════════════════════════════════════════════
#  accounts.json
# ══════════════════════════════════════════════════════════════════════════════

def test_accounts_json_exists():
    assert ACCOUNTS_JSON.exists(), "accounts.json 必須存在於 repo 根目錄"


def test_accounts_json_is_valid():
    accounts = load_accounts(ACCOUNTS_JSON)
    assert len(accounts) >= 1


def test_accounts_json_has_top10():
    accounts = load_accounts(ACCOUNTS_JSON)
    strategies = {a.strategy for a in accounts}
    assert "top10" in strategies


def test_accounts_json_has_d2p2t6():
    accounts = load_accounts(ACCOUNTS_JSON)
    strategies = {a.strategy for a in accounts}
    assert "d2p2t6" in strategies


def test_accounts_json_ids_are_unique():
    accounts = load_accounts(ACCOUNTS_JSON)
    ids = [a.id for a in accounts]
    assert len(ids) == len(set(ids)), "帳戶 ID 必須唯一"


def test_accounts_json_all_have_labels():
    accounts = load_accounts(ACCOUNTS_JSON)
    for a in accounts:
        assert a.label.strip(), f"帳戶 {a.id} 缺少 label"


# ══════════════════════════════════════════════════════════════════════════════
#  mvp_dashboard.html
# ══════════════════════════════════════════════════════════════════════════════

def test_mvp_dashboard_exists():
    assert DASHBOARD_HTML.exists(), "mvp_dashboard.html 必須存在於 repo 根目錄"


def test_mvp_dashboard_has_doctype():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html


def test_mvp_dashboard_fetches_accounts_json():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "accounts.json" in html


def test_mvp_dashboard_fetches_data_json():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "data.json" in html


def test_mvp_dashboard_has_supported_schema_version():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert "SUPPORTED_SCHEMA_VERSION" in html
    assert '"1.0"' in html or "'1.0'" in html


def test_mvp_dashboard_has_nav_chart():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert 'id="nav-chart"' in html


def test_mvp_dashboard_has_kpi_section():
    html = DASHBOARD_HTML.read_text(encoding="utf-8")
    assert 'id="kpi-nav"' in html


# ══════════════════════════════════════════════════════════════════════════════
#  mvp_data/1/data.json (TOP10)
# ══════════════════════════════════════════════════════════════════════════════

TOP10_DATA = MVP_DATA / "1" / "data.json"


@pytest.mark.skipif(not TOP10_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_top10_data_passes_schema():
    data = json.loads(TOP10_DATA.read_text())
    validate_data_json(data)   # 不應 raise


@pytest.mark.skipif(not TOP10_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_top10_schema_version():
    data = json.loads(TOP10_DATA.read_text())
    assert data["meta"]["schema_version"] == "1.0"


@pytest.mark.skipif(not TOP10_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_top10_strategy_field():
    data = json.loads(TOP10_DATA.read_text())
    assert data["meta"]["strategy"] == "top10"


@pytest.mark.skipif(not TOP10_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_top10_account_id():
    data = json.loads(TOP10_DATA.read_text())
    assert str(data["meta"]["account_id"]) == "1"


@pytest.mark.skipif(not TOP10_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_top10_has_positions():
    data = json.loads(TOP10_DATA.read_text())
    assert isinstance(data.get("positions"), list)


@pytest.mark.skipif(not TOP10_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_top10_nav_positive():
    data = json.loads(TOP10_DATA.read_text())
    assert data["summary"]["nav"] > 0


@pytest.mark.skipif(not TOP10_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_top10_rankings_type():
    data = json.loads(TOP10_DATA.read_text())
    assert data["rankings"]["type"] == "market_cap_list"


# ══════════════════════════════════════════════════════════════════════════════
#  mvp_data/2/data.json (D2P2T6)
# ══════════════════════════════════════════════════════════════════════════════

D2P2T6_DATA = MVP_DATA / "2" / "data.json"


@pytest.mark.skipif(not D2P2T6_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_d2p2t6_data_passes_schema():
    data = json.loads(D2P2T6_DATA.read_text())
    validate_data_json(data)


@pytest.mark.skipif(not D2P2T6_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_d2p2t6_schema_version():
    data = json.loads(D2P2T6_DATA.read_text())
    assert data["meta"]["schema_version"] == "1.0"


@pytest.mark.skipif(not D2P2T6_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_d2p2t6_strategy_field():
    data = json.loads(D2P2T6_DATA.read_text())
    assert data["meta"]["strategy"] == "d2p2t6"


@pytest.mark.skipif(not D2P2T6_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_d2p2t6_account_id():
    data = json.loads(D2P2T6_DATA.read_text())
    assert str(data["meta"]["account_id"]) == "2"


@pytest.mark.skipif(not D2P2T6_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_d2p2t6_rankings_type():
    data = json.loads(D2P2T6_DATA.read_text())
    assert data["rankings"]["type"] == "universe_groups"


@pytest.mark.skipif(not D2P2T6_DATA.exists(), reason="需先執行 migrate_to_mvp.py")
def test_mvp_d2p2t6_nav_positive():
    data = json.loads(D2P2T6_DATA.read_text())
    assert data["summary"]["nav"] > 0


# ══════════════════════════════════════════════════════════════════════════════
#  遷移腳本 CLI -- strategy 旗標
# ══════════════════════════════════════════════════════════════════════════════

def test_migrate_script_strategy_top10_only(tmp_path):
    """--strategy top10 只產生帳戶 #1 的 data.json，不產生 #2。"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_to_mvp.py"),
         "--strategy", "top10", "--output-dir", str(tmp_path)],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "1" / "data.json").exists()
    assert not (tmp_path / "2" / "data.json").exists()


def test_migrate_script_strategy_d2p2t6_only(tmp_path):
    """--strategy d2p2t6 只產生帳戶 #2 的 data.json，不產生 #1。"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_to_mvp.py"),
         "--strategy", "d2p2t6", "--output-dir", str(tmp_path)],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "2" / "data.json").exists()
    assert not (tmp_path / "1" / "data.json").exists()


def test_migrate_script_strategy_all(tmp_path):
    """--strategy all（預設）產生兩個帳戶的 data.json。"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_to_mvp.py"),
         "--strategy", "all", "--output-dir", str(tmp_path)],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "1" / "data.json").exists()
    assert (tmp_path / "2" / "data.json").exists()


def test_migrate_script_dry_run_creates_no_files(tmp_path):
    """--dry-run 不應產生任何檔案。"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_to_mvp.py"),
         "--dry-run", "--output-dir", str(tmp_path)],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "1" / "data.json").exists()
    assert not (tmp_path / "2" / "data.json").exists()


def test_migrate_output_passes_schema_validation(tmp_path):
    """遷移後的兩個帳戶 data.json 均通過 schema 驗證。"""
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate_to_mvp.py"),
         "--output-dir", str(tmp_path)],
        capture_output=True, text=True, check=True
    )
    for account_dir in [tmp_path / "1", tmp_path / "2"]:
        data = json.loads((account_dir / "data.json").read_text())
        validate_data_json(data)
