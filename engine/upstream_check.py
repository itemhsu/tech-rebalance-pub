"""engine/upstream_check.py — 偵測 fork 引擎是否落後上游（fork 相容性計劃 §5）。

每日報告若偵測到落後上游，加一行柔性提示。**任何失敗一律回 None（不提示）**，
所以絕不會破壞或洗版每日郵件；對上游本尊（local==upstream）則自然回 0→無提示。

偵測：GitHub compare API 比對本地 HEAD（GITHUB_SHA）與上游分支 HEAD。
私有上游需有讀取權限；無權限/網路失敗/跨 fork 無共同祖先 → 靜默回 None。
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

UPSTREAM_REPO = os.environ.get("UPSTREAM_REPO", "itemhsu/tech-rebalance")
UPSTREAM_BRANCH = os.environ.get("UPSTREAM_BRANCH", "main")


def _local_sha(runner: Callable) -> Optional[str]:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha.strip()
    try:
        r = runner(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def behind_count(upstream: str = UPSTREAM_REPO, branch: str = UPSTREAM_BRANCH,
                 runner: Callable = subprocess.run) -> Optional[int]:
    """回傳「上游比本地多幾個 commit」；無法判定→None。"""
    local = _local_sha(runner)
    if not local:
        return None
    try:
        head = runner(["gh", "api", f"repos/{upstream}/commits/{branch}", "--jq", ".sha"],
                      capture_output=True, text=True, timeout=20)
        if head.returncode != 0 or not head.stdout.strip():
            return None
        up_sha = head.stdout.strip()
        if up_sha == local:
            return 0
        cmp = runner(["gh", "api", f"repos/{upstream}/compare/{local}...{up_sha}",
                      "--jq", ".ahead_by"], capture_output=True, text=True, timeout=20)
        if cmp.returncode != 0:
            return None
        return int(cmp.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def behind_notice(upstream: str = UPSTREAM_REPO, branch: str = UPSTREAM_BRANCH,
                  runner: Callable = subprocess.run) -> Optional[str]:
    """落後上游時回一行柔性提示；否則 None。"""
    n = behind_count(upstream, branch, runner)
    if n and n > 0:
        return (f"🔄 你的引擎落後上游 {n} 個更新。建議同步以取得最新修復"
                "（App 精靈「⑧ 從上游同步引擎」或 scripts/sync_upstream.sh）。")
    return None


_NOTICE_CACHE: dict = {}


def cached_behind_notice() -> Optional[str]:
    """單一行程內只查一次（多帳戶共用）。"""
    if "v" not in _NOTICE_CACHE:
        _NOTICE_CACHE["v"] = behind_notice()
    return _NOTICE_CACHE["v"]
