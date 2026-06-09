"""
run_account.py — 統一帳戶策略分派器

依據 accounts.json 的設定，注入標準 env vars 後 subprocess 呼叫
universal runner.py（P2 Day 13 之後，已無 legacy dispatch 分支）。

用法：
    python run_account.py --account 3
    python run_account.py --account 3 --dry-run
    python run_account.py --account 3 --date-override 2026-06-02
    python run_account.py --account all          # 依序執行所有 enabled 帳戶

切換策略：
    只需修改 accounts.json 中對應帳戶的 "strategy" 欄位，
    不需要改動本檔案或任何 workflow YAML。

環境變數規範：見 docs/env-vars.md
    GitHub Secret 命名：{secret_prefix}_ALPACA_KEY / _ALPACA_SECRET
    subprocess 內注入：ACCOUNT_ID / ACC{id}_BROKER / ACC{id}_ENVIRONMENT
                      / ACC{id}_API_KEY / ACC{id}_API_SECRET
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
from engine.paths import package_root, workdir  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("run_account")

PAPER_URL = "https://paper-api.alpaca.markets"


# ─────────────────────────────────────────────────────────────────────────────
# 公開入口
# ─────────────────────────────────────────────────────────────────────────────

def run_account(
    account_id:    str,
    dry_run:       bool = False,
    date_override: str  = "",
) -> int:
    """
    執行單一帳戶的策略。
    回傳 subprocess exit code（0 = 成功）。
    """
    # ── 讀 accounts.json ──────────────────────────────────────────────────────
    account = _load_account(account_id)
    if account is None:
        log.error("accounts.json 找不到帳戶 id='%s'", account_id)
        return 1

    if not account.get("enabled", True):
        log.info("帳戶 #%s (%s) enabled=false，跳過", account_id, account.get("label", ""))
        return 0

    strategy_id = account["strategy"]
    label       = account.get("label", f"帳戶 #{account_id}")
    # 新欄位 secret_prefix 優先；向下相容舊名 alpaca_secret_prefix
    prefix      = account.get("secret_prefix") or account.get("alpaca_secret_prefix")
    if not prefix:
        log.error("accounts.json 帳戶 #%s 缺 secret_prefix（或舊名 alpaca_secret_prefix）", account_id)
        return 1
    # 使用者資料目錄解析到 workdir()（預設同 repo root；TR_WORKDIR 可外置）
    data_dir    = str(workdir() / account.get("data_dir", f"data/{account_id}"))
    broker_id   = account.get("broker", "alpaca")
    environment = account.get("environment", "paper")

    log.info("=" * 60)
    log.info("帳戶 #%s  %s", account_id, label)
    log.info("策略：%s  資料目錄：%s", strategy_id, data_dir)
    log.info("=" * 60)

    # ── 確認策略 JSON 存在（runner.py 之後會載）──────────────────────────────
    if not (package_root() / "strategies" / f"{strategy_id}.json").exists():
        log.error("找不到策略檔案：strategies/%s.json", strategy_id)
        return 1

    # ── 從環境變數取金鑰（依券商：alpaca 用 _ALPACA_*；其餘依 required_env）──────
    creds, base_url, missing = _resolve_credentials(prefix, broker_id)
    if missing:
        log.error("%s 金鑰未設定。請設定環境變數：%s", broker_id, ", ".join(missing))
        return 1

    log.info("金鑰來源：%s（broker=%s，env=%s）",
             ", ".join(_source_map(prefix, broker_id).values()), broker_id, environment)

    # ── 建立 runner 環境 ──────────────────────────────────────────────────────
    env = _build_env(account, broker_id, environment, creds, dry_run, date_override)

    # ── 建立執行指令（一律走 universal runner.py）─────────────────────────────
    cmd = _build_cmd(strategy_id, account_id, data_dir, date_override, dry_run)

    log.info("執行：%s", " ".join(cmd))
    result = subprocess.run(cmd, env=env, cwd=str(package_root()))
    log.info("帳戶 #%s 結束  exit_code=%d", account_id, result.returncode)
    return result.returncode


_TW_BROKERS = {"sinopac"}


def _account_market(acct: dict) -> str:
    """回該帳戶所屬市場 'tw'/'us'，依券商 spec 的 market.currency 判定（TWD→tw）。

    讀 broker spec 失敗時退回券商名稱表（sinopac→tw，其餘→us）。
    """
    broker = acct.get("broker", "alpaca")
    try:
        from brokers.registry import load_broker_spec
        spec = load_broker_spec(broker)
        ccy = ((spec.get("market") or {}).get("currency") or "USD").upper()
        return "tw" if ccy == "TWD" else "us"
    except Exception:   # noqa: BLE001  spec 缺/壞不可擋住其他帳戶
        return "tw" if broker in _TW_BROKERS else "us"


def run_all_accounts(dry_run: bool = False, date_override: str = "",
                     market: str | None = None) -> None:
    """依序執行所有 enabled 帳戶。任一帳戶失敗不中止後續。

    market='tw'/'us' 時只跑該市場帳戶（依券商判定），供台股/美股各自的排程分流。
    """
    accounts = _load_accounts_json()
    results = {}
    for acct in accounts:
        if not acct.get("enabled", True):
            continue
        if market and _account_market(acct) != market:
            log.info("帳戶 #%s 市場=%s ≠ --market=%s，跳過",
                     acct.get("id"), _account_market(acct), market)
            continue
        rc = run_account(acct["id"], dry_run=dry_run, date_override=date_override)
        results[acct["id"]] = "success" if rc == 0 else "failure"

    if not results:
        log.info("沒有符合 --market=%s 的 enabled 帳戶", market)
        return

    log.info("=" * 60)
    log.info("全部帳戶執行結果：")
    for aid, status in results.items():
        icon = "✅" if status == "success" else "❌"
        log.info("  %s 帳戶 #%s: %s", icon, aid, status)
    log.info("=" * 60)

    if any(s == "failure" for s in results.values()):
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 環境變數建立
# ─────────────────────────────────────────────────────────────────────────────

def _build_env(
    account:       dict,
    broker_id:     str,
    environment:   str,
    creds:         dict,
    dry_run:       bool,
    date_override: str,
) -> dict:
    """
    建立 subprocess 執行環境。

    統一命名（registry.resolve_env_vars 依 spec.auth.required_env 讀取）：
      ACCOUNT_ID            當前執行的帳戶 id（runner.py 讀取）
      ACC{id}_BROKER        券商名稱（brokers/registry.py 讀取）
      ACC{id}_ENVIRONMENT   環境 paper/live/sandbox
      ACC{id}_<PLAIN>       每個 required_env 去 {PREFIX}_ 後的名稱（如 API_KEY/API_SECRET/ACCOUNT_ID）
      DRY_RUN / DATE_OVERRIDE  通用旗標
    """
    account_id = account["id"]
    env = os.environ.copy()

    if dry_run:
        env["DRY_RUN"] = "true"
    env["DATE_OVERRIDE"] = date_override

    env["ACCOUNT_ID"]                   = account_id
    env[f"ACC{account_id}_BROKER"]      = broker_id
    env[f"ACC{account_id}_ENVIRONMENT"] = environment
    # 依 broker required_env 注入（alpaca→API_KEY/API_SECRET；tradier→API_KEY/ACCOUNT_ID）
    for plain, value in creds.items():
        env[f"ACC{account_id}_{plain}"] = value

    return env


# ─────────────────────────────────────────────────────────────────────────────
# 指令建立
# ─────────────────────────────────────────────────────────────────────────────

def _build_cmd(
    strategy_id:   str,
    account_id:    str,
    data_dir:      str,
    date_override: str,
    dry_run:       bool,
) -> list[str]:
    """建立 subprocess 指令（一律 universal runner.py，P2 Day 13 之後）。"""
    cmd = [sys.executable, str(package_root() / "runner.py"), strategy_id,
           "--account", account_id,
           "--data-dir", data_dir]
    if date_override:
        cmd += ["--date-override", date_override]
    if dry_run:
        cmd += ["--dry-run"]
    return cmd


# ─────────────────────────────────────────────────────────────────────────────
# 輔助函式
# ─────────────────────────────────────────────────────────────────────────────

def _load_accounts_json() -> list[dict]:
    path = workdir() / "accounts.json"
    return json.loads(path.read_text(encoding="utf-8"))["accounts"]


def _load_account(account_id: str) -> dict | None:
    for acct in _load_accounts_json():
        if str(acct["id"]) == str(account_id):
            return acct
    return None


def _source_map(prefix: str, broker_id: str) -> dict:
    """回傳 {plain_key: GitHub-Secret 環境變數名}。

    - alpaca：沿用引擎既有命名 {PFX}_ALPACA_KEY / {PFX}_ALPACA_SECRET。
    - 其他券商：依 broker spec 的 auth.required_env（{PFX}_API_KEY / {PFX}_ACCOUNT_ID …）。
    """
    if broker_id == "alpaca":
        return {"API_KEY": f"{prefix}_ALPACA_KEY",
                "API_SECRET": f"{prefix}_ALPACA_SECRET"}
    try:
        from brokers.registry import load_broker_spec
        spec = load_broker_spec(broker_id)
        req = (spec.get("auth") or {}).get("required_env") or []
    except Exception:  # noqa: BLE001
        req = ["{PREFIX}_API_KEY"]
    out = {}
    for tpl in req:
        plain = tpl.replace("{PREFIX}_", "").replace("{PREFIX}", "")
        out[plain] = tpl.replace("{PREFIX}", prefix)
    return out


def _resolve_credentials(prefix: str, broker_id: str = "alpaca") -> tuple[dict, str, list]:
    """依券商讀取金鑰環境變數。

    回傳 (creds_dict, base_url, missing)：
      creds_dict = {plain_key: value}（已成功讀到的）
      missing    = 缺少的環境變數名清單（非空＝設定不全）
    """
    src = _source_map(prefix, broker_id)
    creds: dict = {}
    missing: list = []
    for plain, env_name in src.items():
        value = os.environ.get(env_name, "")
        if value:
            creds[plain] = value
        else:
            missing.append(env_name)
    base_url = os.environ.get(f"{prefix}_BASE_URL", PAPER_URL)
    return creds, base_url, missing


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """CLI 進入點（pip 安裝後的 `run-account` 指令）。"""
    parser = argparse.ArgumentParser(
        description="帳戶策略分派器 — 依 accounts.json 自動路由到對應 runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  run-account --account 3
  run-account --account 3 --dry-run
  run-account --account 3 --date-override 2026-06-02
  run-account --account all
        """,
    )
    parser.add_argument(
        "--account", "-a",
        required=True,
        help="帳戶 ID（accounts.json 中的 id 欄位），或 'all' 執行全部 enabled 帳戶",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅計算，不實際下單",
    )
    parser.add_argument(
        "--date-override",
        default="",
        metavar="YYYY-MM-DD",
        help="強制指定執行日期（測試用）",
    )
    parser.add_argument(
        "--market",
        choices=["tw", "us"],
        default=None,
        help="只跑指定市場的帳戶（依券商判定；台股/美股各自排程分流用）。"
             "搭配 --account all 使用。",
    )
    args = parser.parse_args(argv)

    if args.account.lower() == "all":
        run_all_accounts(dry_run=args.dry_run, date_override=args.date_override,
                         market=args.market)
        return 0
    return run_account(args.account, dry_run=args.dry_run, date_override=args.date_override)


if __name__ == "__main__":
    sys.exit(main())
