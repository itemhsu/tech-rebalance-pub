#!/usr/bin/env python3
"""Tradier sandbox 連線冒煙測試 — 唯讀，不下任何訂單。

用途：驗證 Tradier API token 能否成功認證 + 取行情。
這是 Phase 2（Tradier 整合）正式實作前的最小可行性驗證。

安全：token 從環境變數讀，不寫進程式碼。請自己帶 token 執行：

    TRADIER_SANDBOX_TOKEN=你的sandbox_token python3 scripts/tradier_smoke.py

只呼叫以下唯讀端點（不碰下單 / 帳戶異動）：
    GET /v1/markets/clock                      市場時鐘
    GET /v1/markets/quotes                     即時報價
    GET /v1/user/profile                       帳戶 profile（取 account_id）
    GET /v1/accounts/{account_id}/balances     帳戶餘額（唯讀）
"""
from __future__ import annotations

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

SANDBOX_BASE = "https://sandbox.tradier.com/v1"


def _get(path: str, token: str, params: str = "") -> tuple[int, dict]:
    url = f"{SANDBOX_BASE}{path}"
    if params:
        url += f"?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return e.code, {"error": body}
    except Exception as e:  # noqa: BLE001
        return -1, {"error": str(e)}


def main() -> int:
    token = os.environ.get("TRADIER_SANDBOX_TOKEN", "").strip()
    if not token:
        print("❌ 未設 TRADIER_SANDBOX_TOKEN 環境變數。")
        print("   執行方式：TRADIER_SANDBOX_TOKEN=xxx python3 scripts/tradier_smoke.py")
        return 2

    print(f"🔑 token 長度 {len(token)}（前4碼 {token[:4]}…，不顯示全文）")
    print(f"🌐 base：{SANDBOX_BASE}\n")

    ok = True

    # ① 市場時鐘（最基本的唯讀端點）
    code, data = _get("/markets/clock", token)
    if code == 200:
        clk = data.get("clock", {})
        print(f"✅ /markets/clock  → state={clk.get('state')} desc={clk.get('description')}")
    else:
        ok = False
        print(f"❌ /markets/clock  → HTTP {code}  {data.get('error', data)}")
        if code == 401:
            print("   401 = token 無效或過期。確認用的是 sandbox token（非 production）。")

    # ② 即時報價
    code, data = _get("/markets/quotes", token, "symbols=AAPL,NVDA")
    if code == 200:
        quotes = data.get("quotes", {}).get("quote", [])
        if isinstance(quotes, dict):
            quotes = [quotes]
        for q in quotes:
            print(f"✅ quote {q.get('symbol'):6} last={q.get('last')}  bid={q.get('bid')} ask={q.get('ask')}")
    else:
        ok = False
        print(f"❌ /markets/quotes → HTTP {code}  {data.get('error', data)}")

    # ③ 帳戶 profile（取 account_id — 餘額查詢與下單都需要）
    account_ids: list[str] = []
    code, data = _get("/user/profile", token)
    if code == 200:
        prof = data.get("profile", {})
        accts = prof.get("account", [])
        if isinstance(accts, dict):
            accts = [accts]
        print(f"✅ /user/profile   → name={prof.get('name')}")
        for a in accts:
            acct_no = a.get("account_number")
            if acct_no:
                account_ids.append(acct_no)
            print(f"     account_number={acct_no}  type={a.get('type')}  classification={a.get('classification')}")
    else:
        print(f"⚠️  /user/profile  → HTTP {code}（無法取 account_id，改用 TRADIER_ACCOUNT_ID 環境變數）")

    # 允許用環境變數覆寫 / 補上 account_id
    env_acct = os.environ.get("TRADIER_ACCOUNT_ID", "").strip()
    if env_acct and env_acct not in account_ids:
        account_ids.append(env_acct)

    # ④ 帳戶餘額（唯讀）
    if not account_ids:
        print("⚠️  無 account_id → 跳過餘額查詢。")
        print("    可手動指定：TRADIER_ACCOUNT_ID=xxx TRADIER_SANDBOX_TOKEN=xxx python3 scripts/tradier_smoke.py")
    for acct in account_ids:
        code, data = _get(f"/accounts/{acct}/balances", token)
        if code == 200:
            b = data.get("balances", {})
            print(f"✅ 餘額 {acct}：")
            print(f"     總值 total_equity   = {b.get('total_equity')}")
            print(f"     現金 total_cash     = {b.get('total_cash')}")
            print(f"     可動用 cash_available = {b.get('cash', {}).get('cash_available') if isinstance(b.get('cash'), dict) else 'n/a'}")
            print(f"     購買力 buying_power  = {b.get('margin', {}).get('stock_buying_power') if isinstance(b.get('margin'), dict) else b.get('cash', {}).get('cash_available') if isinstance(b.get('cash'), dict) else 'n/a'}")
            print(f"     未平倉損益 open_pl   = {b.get('open_pl')}  market_value={b.get('market_value')}")
        else:
            ok = False
            print(f"❌ 餘額 {acct} → HTTP {code}  {data.get('error', data)}")

    # ⑤ JSON-driven 引擎自我驗證（Phase C）：用 brokers/tradier.json + 通用引擎
    #    對真實 sandbox 取餘額/報價，證明「0 Python 的 spec」真的能運作。
    if account_ids:
        acct = account_ids[0]
        try:
            _ROOT = str(Path(__file__).resolve().parent.parent)
            if _ROOT not in sys.path:
                sys.path.insert(0, _ROOT)
            from brokers.registry import load_broker_spec
            from brokers.rest_broker import RestBrokerClient
            spec = load_broker_spec("tradier")
            client = RestBrokerClient(
                spec, {"API_KEY": token, "ACCOUNT_ID": acct}, environment="sandbox")
            bal = client.get_account_balance()
            px = client.get_latest_prices(["AAPL"])
            print(f"✅ 引擎驗證（RestBrokerClient + tradier.json，0 Python）：")
            print(f"     get_account_balance → nav={bal.nav} cash={bal.cash}")
            print(f"     get_latest_prices(AAPL) → {px.get('AAPL')}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"❌ 引擎驗證失敗：{e}")

    print()
    if ok:
        print("🎉 連得上！token 有效，行情 + 餘額 + 通用引擎全部正常 → Tradier JSON 整合可用。")
        return 0
    print("💥 連線失敗，看上面錯誤。最常見是 token 種類錯（prod vs sandbox）或已 revoke。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
