#!/usr/bin/env python3
"""scripts/send_test_email.py — 寄一封測試信給寄件人自己（雲端 test_email.yml 用）。

讀 EMAIL_SENDER / EMAIL_PASSWORD（Gmail App Password）環境變數，
寄件人 → 寄件人。成功 exit 0、失敗 exit 1（讓 workflow conclusion 反映結果）。
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys


def main() -> int:
    sender = os.environ.get("EMAIL_SENDER", "").strip()
    password = os.environ.get("EMAIL_PASSWORD", "").strip()
    if not sender or not password:
        print("❌ 缺 EMAIL_SENDER 或 EMAIL_PASSWORD")
        return 1
    msg = (f"From: {sender}\r\nTo: {sender}\r\n"
           f"Subject: [測試] 交易系統 — Email 設定正常\r\n\r\n"
           f"收到這封信代表你的 Email 發送設定正確。")
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(sender, password)
            s.sendmail(sender, [sender], msg.encode("utf-8"))
        print(f"✅ 測試信已寄至 {sender}")
        return 0
    except smtplib.SMTPAuthenticationError:
        print("❌ 驗證失敗：請確認 EMAIL_PASSWORD 是 Gmail App Password")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"❌ 寄送失敗：{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
