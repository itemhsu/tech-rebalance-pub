"""brokers/cashflows.py — 券商活動紀錄 → 外部現金流（入金/出金）正規化。

Alpaca Account Activities：CSD=入金、CSW=出金、JNLC=現金 journal（依正負）。
FILL/DIV/FEE/INT 等不是外部現金流，忽略。
回 [{date, type: deposit|withdrawal, amount(正數)}]。
"""
from __future__ import annotations

ALPACA_CASH_ACTIVITY_TYPES = "CSD,CSW,JNLC"


def parse_alpaca_activities(acts) -> list:
    out = []
    for a in acts or []:
        if not isinstance(a, dict):
            continue
        t = (a.get("activity_type") or "").upper()
        try:
            amt = float(a.get("net_amount") or 0)
        except (TypeError, ValueError):
            continue
        if amt == 0:
            continue
        day = a.get("date") or (a.get("transaction_time") or "")[:10]
        if t == "CSD" or (t == "JNLC" and amt > 0):
            out.append({"date": day, "type": "deposit", "amount": abs(amt)})
        elif t == "CSW" or (t == "JNLC" and amt < 0):
            out.append({"date": day, "type": "withdrawal", "amount": abs(amt)})
    return out
