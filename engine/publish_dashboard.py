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


def _ensure_inception_states() -> None:
    """帳號的「init page」：只有當帳戶『完全沒有 state』時，用即時 NAV 建一筆
    inception 起點（date=今天、當前 NAV/現金/持倉、無交易歷史），讓新帳戶任何日子
    都能立刻有 dashboard。

    一旦帳戶已有 state（交易過或已建過 inception）→ 完全不動，由交易 workflow 更新。
    所以：① 不污染交易歷史 ② 週末顯示最後交易日報告 ③ 哪裡點進來都一樣（同一份已發佈）。
    需要 broker secrets（workflow 提供 ACC{id}_*）。
    """
    from datetime import date
    from engine.accounts import load_accounts
    from engine.paths import workdir
    from run_account import _resolve_credentials
    from brokers.from_env import build_client_for_account
    import portfolio as pf

    for acc in load_accounts():
        if not getattr(acc, "enabled", True):
            continue
        aid = acc.id
        dd = workdir() / (getattr(acc, "data_dir", None) or f"data/{aid}")
        p = dd / "portfolio_state.json"
        if p.exists():
            continue                       # 已有 state → 交給交易 workflow，不碰
        prefix = f"ACC{aid}"
        broker = getattr(acc, "broker", "alpaca") or "alpaca"
        try:
            creds, base_url, missing = _resolve_credentials(prefix, broker)
            if missing:
                print(f"   #{aid}: 缺金鑰 {missing}，跳過 init")
                continue
            os.environ[f"{prefix}_BROKER"] = broker
            os.environ[f"{prefix}_ENVIRONMENT"] = getattr(acc, "environment", "paper") or "paper"
            os.environ[f"{prefix}_BASE_URL"] = base_url
            for plain, val in creds.items():
                os.environ[f"{prefix}_{plain}"] = val
            client = build_client_for_account(aid)
            nav, cash = client.get_account_nav()
            positions = client.get_current_positions()
            dd.mkdir(parents=True, exist_ok=True)
            state = pf.PortfolioState(
                date=date.today().isoformat(), nav=nav, cash=cash,
                positions=positions, top10=[], orders_executed=[], ranked_stocks=[],
            )
            pf.save_state(state, path=p)
            pf.append_history(state, path=dd / "portfolio_state_history.json")
            print(f"   #{aid}: init page（inception）NAV={nav:.2f} cash={cash:.2f}")
        except Exception as e:  # noqa: BLE001
            print(f"   #{aid}: init 失敗 {type(e).__name__}: {e}")


def main() -> int:
    from engine.report_generator import generate_all
    from engine.paths import workdir

    wd = workdir()
    out = wd / "mvp_data"
    out.mkdir(parents=True, exist_ok=True)

    # 新帳戶（無 state）→ 用即時 NAV 建 inception init page；有 state 的不動
    print("▶ 確保新帳戶有 init page（無 state 才建）…")
    _ensure_inception_states()

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
