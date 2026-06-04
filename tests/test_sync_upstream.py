"""scripts/sync_upstream.sh 的守門測試（fork 相容性計劃 §5）。

bash 腳本難以完整單測，但可保證：語法正確、可執行、且保留了所有 fork 私有路徑。
若日後有人新增私有資料目錄卻忘了加進 PRIVATE_PATHS，這裡提醒。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sync_upstream.sh"


def test_script_exists_and_executable():
    assert SCRIPT.exists(), "scripts/sync_upstream.sh 不存在"
    assert SCRIPT.stat().st_mode & 0o111, "sync_upstream.sh 未設可執行權限"


def test_bash_syntax_ok():
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, f"bash 語法錯誤：{r.stderr}"


def test_protects_all_fork_private_paths():
    """凡是 fork 會自行客製/產生的 tracked 路徑，都應在 PRIVATE_PATHS 內。"""
    text = SCRIPT.read_text(encoding="utf-8")
    for p in ("accounts.json", "data", "d2p2t6/data", "weekly_top10/data"):
        assert f'"{p}"' in text, f"sync_upstream.sh 未保護私有路徑 {p}"


def test_has_dry_run_and_clean_tree_guard():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--dry-run" in text, "缺 --dry-run 模式"
    assert "git status --porcelain" in text, "缺『工作目錄乾淨』守門"
    assert "checkout --ours" in text, "缺『私有檔保留本地版本』邏輯"
