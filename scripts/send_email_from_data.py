"""
scripts/send_email_from_data.py — 從 mvp_data/{id}/data.json 生成並發送每日郵件

Model-View 分離架構：
  Model：mvp_data/{id}/data.json（由 migrate_to_mvp.py 每日寫出）
  View ：engine/email_renderer.py（共用 HTML 模板，渲染所有帳戶）

用法：
  python scripts/send_email_from_data.py --account 1
  python scripts/send_email_from_data.py --account all
  python scripts/send_email_from_data.py --account 1,2,3
  python scripts/send_email_from_data.py --account all --dry-run   # 只渲染，不寄出
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from engine.email_renderer import render
from engine.strategy_loader import load_and_validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("send_email")

# ── 帳戶 → 策略 ID 對應（從 accounts.json 動態讀取，不再硬編）─────────────────
def _load_accounts() -> list[dict]:
    """讀 accounts.json 的 accounts 陣列。"""
    try:
        data = json.loads((ROOT / "accounts.json").read_text(encoding="utf-8"))
        return data.get("accounts", [])
    except Exception as e:
        logger.error("讀 accounts.json 失敗：%s", e)
        return []


def _account_strategy(account_id: str) -> str | None:
    """查指定帳戶的策略 id（從 accounts.json）。"""
    for acc in _load_accounts():
        if str(acc.get("id")) == str(account_id):
            return acc.get("strategy")
    return None


def _enabled_account_ids() -> list[str]:
    """所有 enabled 帳戶的 id（從 accounts.json）。"""
    return [str(acc["id"]) for acc in _load_accounts()
            if acc.get("enabled", True) and acc.get("strategy")]


def account_strategy_map() -> dict[str, str]:
    """{account_id: strategy_id}（從 accounts.json 動態建構）。

    取代舊的硬編 ACCOUNT_STRATEGY dict；供需要全表的呼叫者用。
    """
    return {str(acc["id"]): acc["strategy"]
            for acc in _load_accounts() if acc.get("strategy")}


DASHBOARD_BASE = "https://itemhsu.github.io/tech-rebalance-dashboard"


# ══════════════════════════════════════════════════════════════════════════════
#  Gmail SMTP 寄送（極簡：單一 sender + password；多收件人支援）
# ══════════════════════════════════════════════════════════════════════════════

def _send_via_smtp(
    subject: str,
    html_body: str,
    recipients: list,
    sender: str,
    password: str,
) -> bool:
    """用 Gmail SMTP 寄一封 multi-recipient 信。

    Parameters
    ----------
    recipients : list[str]  收件人 list（第一個 To、第二個 CC）。
    sender     : str        寄件人 email（同時是 SMTP 登入帳號）。
    password   : str        Gmail App Password（16 字元）。
    """
    import smtplib, ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not recipients:
        logger.error("SMTP 寄送時 recipients 為空")
        return False

    # 去重（保留順序）
    seen = set(); uniq = []
    for r in recipients:
        if r and r not in seen:
            seen.add(r); uniq.append(r)
    recipients = uniq

    to_addr = recipients[0]
    cc_addrs = recipients[1:]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = to_addr
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(sender, password)
            s.sendmail(sender, recipients, msg.as_string())
        logger.info("✅ SMTP 郵件已寄出 → %s%s",
                    to_addr,
                    f" (CC: {', '.join(cc_addrs)})" if cc_addrs else "")
        return True
    except smtplib.SMTPAuthenticationError as e:
        logger.error("SMTP 驗證失敗（Gmail 必須用 App Password）：%s", e)
        return False
    except Exception as e:
        logger.error("SMTP 寄送失敗：%s", e)
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  帳戶級收件人解析（從 accounts.json）
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_CC = os.environ.get("EMAIL_CC", "")  # 不硬寫個人信箱；需要 CC 自己設 EMAIL_CC


def _resolve_recipients(account_id: str) -> list:
    """從 accounts.json 取得指定帳戶的 email_recipients。

    規則：
      1. accounts.json 帳戶設 email_recipients → 用這個 list
      2. 若 list 只有 1 個且設了 EMAIL_CC → 自動補 EMAIL_CC 為 CC
      3. accounts.json 沒設 → fallback 到 env EMAIL_RECIPIENT
      4. 都沒則 raise
    """
    try:
        accounts = json.loads((ROOT / "accounts.json").read_text())["accounts"]
        for acc in accounts:
            if str(acc.get("id")) == str(account_id):
                rs = acc.get("email_recipients") or []
                if rs:
                    # 至多 2 個，第二個預設 DEFAULT_CC
                    primary = rs[0]
                    secondary = rs[1] if len(rs) >= 2 else (
                        DEFAULT_CC if primary != DEFAULT_CC else None
                    )
                    return [primary] + ([secondary] if secondary else [])
                break
    except Exception as e:
        logger.warning("讀 accounts.json 取 email_recipients 失敗：%s", e)

    # fallback：env EMAIL_RECIPIENT
    fallback = os.environ.get("EMAIL_RECIPIENT", "")
    if fallback:
        return [fallback]
    return []


# ══════════════════════════════════════════════════════════════════════════════
#  單帳戶發送
# ══════════════════════════════════════════════════════════════════════════════

def _report_date(data_path: Path) -> str:
    try:
        return str(json.loads(data_path.read_text(encoding="utf-8")).get("date", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def _log_result(account_id, report_date, subject, status, error, dry_run):
    """寫一筆結構化寄信日誌（dry-run 不寫，避免污染）。回傳 status。"""
    if not dry_run:
        try:
            from engine import email_log
            path = os.environ.get("EMAIL_LOG_PATH") or email_log.DEFAULT_PATH
            email_log.append(path, account_id, report_date, subject, status, error)
        except Exception as exc:  # noqa: BLE001（日誌失敗不該影響寄信判定）
            logger.warning("寫寄信日誌失敗：%s", exc)
    return status


def send_for_account(
    account_id: str,
    mvp_data_dir: Path,
    dry_run: bool = False,
) -> str:
    """為指定帳戶讀 data.json、渲染 HTML、Gmail SMTP 寄出，並寫結構化日誌。

    Returns: status 字串 —— "ok"（已寄）/ "skip"（當日無資料）/ "fail"（真失敗）。
    """
    data_path = mvp_data_dir / account_id / "data.json"
    report_date, subject = "", ""

    if not data_path.exists():
        logger.warning("帳戶 #%s data.json 不存在，跳過（%s）", account_id, data_path)
        return _log_result(account_id, "", "", "skip", "data.json 不存在", dry_run)

    report_date = _report_date(data_path)
    strategy_id = _account_strategy(account_id)
    if not strategy_id:
        logger.error("帳戶 #%s 在 accounts.json 找不到 strategy", account_id)
        return _log_result(account_id, report_date, "", "fail", "找不到 strategy", dry_run)

    try:
        strategy = load_and_validate(strategy_id)
    except Exception as exc:
        logger.error("帳戶 #%s 策略載入失敗：%s", account_id, exc)
        return _log_result(account_id, report_date, "", "fail", f"策略載入失敗：{exc}", dry_run)

    try:
        subject, html = render(data_path, ROOT / "strategies" / f"{strategy_id}.json")
    except Exception as exc:
        logger.error("帳戶 #%s 郵件渲染失敗：%s", account_id, exc)
        return _log_result(account_id, report_date, "", "fail", f"渲染失敗：{exc}", dry_run)

    logger.info("帳戶 #%s | 主旨：%s", account_id, subject)

    if dry_run:
        logger.info("[DRY RUN] 帳戶 #%s 郵件已渲染（不寄出），HTML 長度：%d 字元",
                    account_id, len(html))
        return _log_result(account_id, report_date, subject, "ok", "", dry_run)

    recipients = _resolve_recipients(account_id)
    if not recipients:
        logger.error("帳戶 #%s 找不到收件人", account_id)
        return _log_result(account_id, report_date, subject, "fail", "找不到收件人", dry_run)

    sender = os.environ.get("EMAIL_SENDER", "") or recipients[0]
    smtp_password = os.environ.get("EMAIL_PASSWORD", "").strip()
    if not smtp_password:
        logger.error("EMAIL_PASSWORD 未設定，無法寄信，帳戶 #%s", account_id)
        return _log_result(account_id, report_date, subject, "fail", "EMAIL_PASSWORD 未設", dry_run)

    logger.info("帳戶 #%s 走 Gmail SMTP（sender=%s, to=%s）", account_id, sender, recipients)
    ok = _send_via_smtp(subject, html, recipients, sender, smtp_password)
    return _log_result(account_id, report_date, subject,
                       "ok" if ok else "fail",
                       "" if ok else "SMTP 寄送失敗", dry_run)


# ══════════════════════════════════════════════════════════════════════════════
#  主程式
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="從 data.json 發送每日帳戶郵件")
    parser.add_argument(
        "--account",
        default="all",
        help='帳戶 ID（"1"、"2"、"3"、"1,2,3" 或 "all"，預設 all）',
    )
    parser.add_argument(
        "--mvp-data-dir",
        default=str(ROOT / "mvp_data"),
        help="mvp_data 目錄（預設：mvp_data/）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只渲染，不實際發送",
    )
    args = parser.parse_args()

    mvp_data_dir = Path(args.mvp_data_dir)

    # 解析帳戶清單
    if args.account.lower() == "all":
        account_ids = _enabled_account_ids()
    else:
        account_ids = [a.strip() for a in args.account.split(",")]

    logger.info("═" * 50)
    logger.info("send_email_from_data 啟動")
    logger.info("  模式   ：%s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("  帳戶   ：%s", ", ".join(f"#{a}" for a in account_ids))
    logger.info("  資料目錄：%s", mvp_data_dir)
    logger.info("═" * 50)

    results: dict[str, str] = {}
    for account_id in account_ids:
        logger.info("── 帳戶 #%s ────────────────────────────", account_id)
        results[account_id] = send_for_account(
            account_id=account_id,
            mvp_data_dir=mvp_data_dir,
            dry_run=args.dry_run,
        )

    # 摘要
    logger.info("═" * 50)
    _icon = {"ok": "✅ 成功", "skip": "⏭️ 略過（無資料）", "fail": "❌ 失敗"}
    ok_count = sum(1 for v in results.values() if v == "ok")
    data_present = [v for v in results.values() if v != "skip"]
    for aid, st in results.items():
        logger.info("  帳戶 #%s：%s", aid, _icon.get(st, st))
    logger.info("成功 %d / %d（有資料帳戶 %d）", ok_count, len(results), len(data_present))
    logger.info("═" * 50)

    # 有資料的帳戶全部失敗才回傳非零（無資料的 skip 不算失敗）
    if data_present and ok_count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
