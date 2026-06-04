"""每日 workflow 冪等保護：檢查所有日報帳戶今日是否都已執行。

寫 `skip=true|false` 到 $GITHUB_OUTPUT，由 workflow guard 步驟讀取。
"""
import datetime
import json
import os
import pathlib

import os as _os
ROOT = pathlib.Path(_os.environ.get("TR_WORKDIR") or pathlib.Path(__file__).resolve().parent.parent)
DAILY_ACCOUNT_IDS = {"1", "2", "3"}  # 本 workflow 負責的帳戶


def main() -> int:
    accounts_raw = json.loads((ROOT / "accounts.json").read_text())["accounts"]
    today = datetime.date.today().isoformat()

    active = [
        a for a in accounts_raw
        if a.get("enabled", True)
        and a.get("data_dir")
        and str(a["id"]) in DAILY_ACCOUNT_IDS
    ]

    results = {}
    for a in active:
        state_path = pathlib.Path(a["data_dir"]) / "portfolio_state.json"
        if state_path.exists():
            results[a["id"]] = json.loads(state_path.read_text()).get("date", "")
        else:
            results[a["id"]] = ""
        print(f"帳戶 #{a['id']} ({a['strategy']}): {results[a['id']]}", flush=True)

    all_done = bool(results) and all(v == today for v in results.values())
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"skip={'true' if all_done else 'false'}\n")

    if all_done:
        print(f"所有帳戶今日（{today}）皆已執行，備援排程跳過")
    else:
        pending = [aid for aid, d in results.items() if d != today]
        print(f"待執行帳戶：{pending}  今日：{today}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
