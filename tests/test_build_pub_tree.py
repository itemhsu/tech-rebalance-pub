"""build_pub_tree：白名單建樹 + 安全掃描（pub 拆分 S1）。最高優先：零個資外洩。"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_pub_tree as b


# ── A. 白名單 / 建樹 ─────────────────────────────────────────────────────────
def test_includes_engine_code():
    f = b.selected_files()
    for need in ("runner.py", "engine/paths.py", "strategies/top10.json",
                 "schemas/data-schema-v1.json", "pyproject.toml"):
        assert need in f, f"白名單漏了 {need}"


def test_data_filelevel_only_refdata():
    f = b.selected_files()
    assert "data/universe.json" in f and "data/shares_outstanding.json" in f
    # 帳戶狀態絕不入
    assert not any(x.startswith(("data/1/", "data/3/", "data/99/")) for x in f)
    assert "data/portfolio_state.json" not in f


def test_excludes_private():
    f = b.selected_files()
    assert "accounts.json" not in f
    assert ".github/workflows/daily_all_accounts.yml" not in f
    assert not any(x.startswith("tests/fixtures/golden/") for x in f)   # golden 排除
    assert not any(x.startswith(("d2p2t6/data", "weekly_top10/data")) for x in f)


def test_real_build_passes_scan(tmp_path):
    rc = b.build(tmp_path / "tree")
    assert rc == 0, "乾淨白名單樹應通過安全掃描"


# ── B. 安全掃描（最高優先）─────────────────────────────────────────────────
def _tree_with(tmp_path, rel, content=b"x"):
    d = tmp_path / "t"; (d / rel).parent.mkdir(parents=True, exist_ok=True)
    (d / rel).write_bytes(content)
    return d


def test_scan_rejects_accounts_json(tmp_path):
    d = _tree_with(tmp_path, "accounts.json")
    assert any("禁列" in v for v in b.scan_tree(d))


def test_scan_rejects_state_files(tmp_path):
    d = _tree_with(tmp_path, "data/3/portfolio_state.json")
    assert b.scan_tree(d)
    d2 = _tree_with(tmp_path, "data/3/trade_events.jsonl")
    assert b.scan_tree(d2)


def test_scan_rejects_env_and_live_wf(tmp_path):
    assert b.scan_tree(_tree_with(tmp_path, ".env"))
    assert b.scan_tree(_tree_with(tmp_path, ".github/workflows/daily_all_accounts.yml"))


def test_scan_rejects_real_email(tmp_path):
    d = _tree_with(tmp_path, "x.py", b"RECIPIENT = 'real.person@" b"realmail.org'")
    assert any("email" in v for v in b.scan_tree(d))


def test_scan_allows_example_email(tmp_path):
    d = _tree_with(tmp_path, "x.py", b"to = 'user@example.com'")
    assert b.scan_tree(d) == []


def test_scan_rejects_github_pat(tmp_path):
    d = _tree_with(tmp_path, "x.txt", b"token=ghp_" + b"A" * 36)
    assert any("PAT" in v for v in b.scan_tree(d))


def test_scan_clean_tree_passes(tmp_path):
    d = _tree_with(tmp_path, "engine/paths.py", b"import os\n")
    assert b.scan_tree(d) == []
