"""engine/sinopac_selftest.py — 永豐模擬下單 selftest（驗證真實下單路徑）。

下一張零股測試單（預設 2330.TW × 1 股 market），用 trade.status.status 判斷成功：
PendingSubmit / Submitted 即代表模擬委託成功（官方測試準則，與帳戶有無資金無關）。

用法（雲端）：設 ACC{id}_API_KEY/SECRET → `python -m engine.sinopac_selftest`
環境變數：
  SELFTEST_SYMBOL  測試代號（預設 2330.TW）
  SELFTEST_SIDE    buy/sell（預設 buy）
"""
from __future__ import annotations

import os
import sys

_OK_STATUS = {"PendingSubmit", "PreSubmitted", "Submitted", "Filled", "Filling", "PartFilled"}


def main() -> int:
    from engine.accounts import load_accounts
    from brokers.registry import load_broker_spec
    from brokers.sinopac_client import SinoPacClient

    accs = [a for a in load_accounts()
            if (getattr(a, "broker", None) == "sinopac") and getattr(a, "enabled", True)]
    if not accs:
        print("[selftest] 找不到 enabled 的 sinopac 帳戶")
        return 1
    acc = accs[0]
    pfx = getattr(acc, "secret_prefix", None) or f"ACC{acc.id}"
    key = os.environ.get(f"{pfx}_API_KEY", "")
    sec = os.environ.get(f"{pfx}_API_SECRET", "")
    if not key or not sec:
        print(f"[selftest] 缺 {pfx}_API_KEY / {pfx}_API_SECRET")
        return 1

    spec = load_broker_spec("sinopac")
    client = SinoPacClient(spec, {"API_KEY": key, "API_SECRET": sec}, environment="paper")

    sym = os.environ.get("SELFTEST_SYMBOL", "2330.TW")
    side = os.environ.get("SELFTEST_SIDE", "buy")
    print(f"[selftest] 帳戶 #{acc.id}（{pfx}）下測試單：{sym} × 1 股 {side} market（零股·模擬）")

    try:
        res = client.place_order(sym, qty=1, side=side, order_type="market")
    except Exception as e:   # noqa: BLE001
        print(f"[selftest] ❌ place_order 例外：{type(e).__name__}: {e}")
        return 1

    status = (res.raw or {}).get("status", res.status)
    msg = (res.raw or {}).get("msg", "")
    ok = status in _OK_STATUS
    print(f"[selftest] order_id={res.order_id}  status={status}  msg={msg!r}")
    if ok:
        print(f"[selftest] ✅ 模擬委託成功（status={status}）")
        return 0
    print(f"[selftest] ❌ 委託未成功（status={status}）—— 請看上面 msg")
    return 1


if __name__ == "__main__":
    sys.exit(main())
