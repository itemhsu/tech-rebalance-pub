"""engine/publish_dashboard.py — 生成 mvp dashboard 資料並推到 dashboard repo。

薄殼每日 workflow 跑完 run-account 後呼叫 `tr-publish-dashboard`：
  1. generate_all → mvp_data/{id}/data.json + index.json（純資料驅動）
  2. 複製 accounts.json 進 mvp_data
  3. 若有 PAGES_TOKEN：clone {GITHUB_REPOSITORY}-dashboard，覆蓋資料後 push
     （保留 dashboard 既有的 mvp_dashboard.html 等檢視頁）

無 PAGES_TOKEN（或非 CI）→ 只在本地生成、跳過發佈，回 0（不讓 workflow 失敗）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def main() -> int:
    from engine.report_generator import generate_all
    from engine.paths import workdir

    wd = workdir()
    out = wd / "mvp_data"
    out.mkdir(parents=True, exist_ok=True)

    print("▶ 生成 mvp 資料（資料驅動）…")
    results = generate_all(out, dry_run=False)
    for aid, st in results.items():
        print(f"   #{aid}: {st}")

    # accounts.json 一併帶上（dashboard 帳戶切換用）
    acc = wd / "accounts.json"
    if acc.exists():
        shutil.copy(acc, out / "accounts.json")

    token = os.environ.get("PAGES_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()   # owner/tech-rebalance
    if not token or not repo:
        print("ℹ️ 無 PAGES_TOKEN 或 GITHUB_REPOSITORY → 只在本地生成 mvp_data，跳過發佈")
        return 0

    dash = f"{repo}-dashboard"
    tmp = Path("/tmp/dash-publish")
    shutil.rmtree(tmp, ignore_errors=True)
    url = f"https://x-access-token:{token}@github.com/{dash}.git"
    print(f"▶ clone dashboard repo：{dash}")
    r = _run(["git", "clone", "--depth", "1", url, str(tmp)])
    if r.returncode != 0:
        print("FAIL clone dashboard：", (r.stderr or "")[:300])
        return 1

    # 覆蓋資料（保留 dashboard 既有檢視頁如 mvp_dashboard.html）
    for item in out.iterdir():
        dst = tmp / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy(item, dst)

    _run(["git", "-C", str(tmp), "config", "user.name", "Dashboard Bot"])
    _run(["git", "-C", str(tmp), "config", "user.email", "bot@users.noreply.github.com"])
    _run(["git", "-C", str(tmp), "add", "-A"])
    if _run(["git", "-C", str(tmp), "diff", "--staged", "--quiet"]).returncode == 0:
        print("ℹ️ dashboard 無變更，跳過")
        return 0
    _run(["git", "-C", str(tmp), "commit", "-m", "chore: dashboard data update"])
    p = _run(["git", "-C", str(tmp), "push"])
    if p.returncode != 0:
        print("FAIL push dashboard：", (p.stderr or "")[:300])
        return 1
    print(f"✅ dashboard 已發佈：{dash}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
