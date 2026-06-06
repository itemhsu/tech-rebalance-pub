"""engine/refresh_nav.py — tr-refresh-nav：查每個 enabled 帳戶的即時 NAV。

唯讀（只查券商餘額、絕不下單），與交易路徑隔離，失敗也不影響下單。
寫出 data/nav_snapshot.json = {account_id: {nav, cash, ts}}，供 GUI「即時 NAV」用。
workflow 餵 ACC{id}_ALPACA_KEY 等 secret（與 daily.yml 同來源）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone


def main() -> int:
    from engine.accounts import load_accounts
    from engine.paths import workdir
    from run_account import _resolve_credentials
    from brokers.from_env import build_client_for_account

    snap: dict = {}
    for acc in load_accounts():
        if not getattr(acc, "enabled", True):
            continue
        aid = acc.id
        prefix = f"ACC{aid}"
        broker = getattr(acc, "broker", "alpaca") or "alpaca"
        env_name = getattr(acc, "environment", "paper") or "paper"
        try:
            creds, base_url, missing = _resolve_credentials(prefix, broker)
            if missing:
                snap[aid] = {"error": f"缺金鑰：{', '.join(missing)}"}
                print(f"#{aid}: 缺金鑰 {missing}")
                continue
            os.environ[f"{prefix}_BROKER"] = broker
            os.environ[f"{prefix}_ENVIRONMENT"] = env_name
            os.environ[f"{prefix}_BASE_URL"] = base_url
            for plain, val in creds.items():
                os.environ[f"{prefix}_{plain}"] = val
            client = build_client_for_account(aid)
            nav, cash = client.get_account_nav()
            snap[aid] = {
                "nav": float(nav), "cash": float(cash),
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            print(f"#{aid}: NAV={nav:.2f} cash={cash:.2f}")
        except Exception as e:  # noqa: BLE001  單一帳戶失敗不影響其他
            snap[aid] = {"error": str(e)[:160]}
            print(f"#{aid}: FAIL {type(e).__name__}: {e}")

    out = workdir() / "data" / "nav_snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ nav_snapshot.json 已寫出（{len(snap)} 帳戶）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
