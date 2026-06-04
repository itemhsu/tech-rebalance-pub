"""
scripts/update_index.py — 從 dashboard repo 讀取既有 index.json，合併今日日期後更新。

用法（CI 環境）：
  python scripts/update_index.py --account 1
  python scripts/update_index.py --account 2

workflow 在 migrate_to_mvp.py 之後執行此腳本，確保 index.json 包含所有歷史日期。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

DASHBOARD_REPO = "itemhsu/tech-rebalance-dashboard"


def fetch_remote_index(account_id: str) -> list[str]:
    """從 GitHub raw content 讀取既有 index.json 的 dates。"""
    url = (
        f"https://raw.githubusercontent.com/{DASHBOARD_REPO}/main"
        f"/{account_id}/index.json"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("dates", [])
    except Exception as e:
        print(f"[update_index] 無法讀取遠端 index（{e}），使用本地資料", file=sys.stderr)
        return []


def update_index(account_id: str, output_dir: Path) -> None:
    acct_dir = output_dir / account_id
    index_path = acct_dir / "index.json"

    if not index_path.exists():
        print(f"[update_index] {index_path} 不存在，跳過", file=sys.stderr)
        return

    # 讀取本地（今日）index
    local = json.loads(index_path.read_text(encoding="utf-8"))
    local_dates: list[str] = local.get("dates", [])

    # 讀取遠端歷史
    remote_dates = fetch_remote_index(account_id)

    # 合併去重、降序排列
    merged = sorted(set(local_dates + remote_dates), reverse=True)
    result = {"dates": merged, "latest": merged[0] if merged else ""}

    index_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"[update_index] 帳戶 {account_id}: index.json 共 {len(merged)} 筆，最新 {result['latest']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, help="帳戶 ID（例：1 或 2）")
    parser.add_argument("--output-dir", default="mvp_data", help="mvp_data 目錄")
    args = parser.parse_args()
    update_index(args.account, Path(args.output_dir))


if __name__ == "__main__":
    main()
