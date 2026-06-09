"""runner.py — universal strategy runner

取代每個策略一個 main.py 的反模式。完全 JSON-driven：
讀 strategies/{id}.json + accounts.json → 跑出 orders → 執行 → 存 state。

新增策略 = 寫 v3 JSON + accounts.json 加一筆 → 0 程式碼變動。

對應 backtest_anchor/tool_v2 的 SpecEngine（live 版）。

用法：
    python3 runner.py <strategy_id> [--account ID] [--data-dir PATH] [--dry-run]
    python3 runner.py top10 --account 1
    python3 runner.py mom_6m_t20 --account 3 --dry-run

對應 run_account.py dispatch（讀 accounts.json 後 subprocess 呼叫此檔）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# 兩 repo 地基：引擎資產 package_root() / 使用者資料 workdir()
from engine.paths import package_root, workdir  # noqa: E402

logger = logging.getLogger("runner")


# ════════════════════════════════════════════════════════════════════════
#  Universe 載入（已抽至 engine/universe_loader.py — P2-B）
# ════════════════════════════════════════════════════════════════════════
from engine.universe_loader import load_universe_groups  # noqa: E402


# ════════════════════════════════════════════════════════════════════════
#  Factor 計算（從 broker 抓資料）
# ════════════════════════════════════════════════════════════════════════

_MOMENTUM_RE = re.compile(r"^price_momentum_(\d+)m$")
_TRADING_DAYS_PER_MONTH = {1: 21, 3: 63, 6: 126, 9: 189, 12: 252}


def _parse_momentum_months(name: str) -> Optional[int]:
    m = _MOMENTUM_RE.match(name)
    return int(m.group(1)) if m else None


def _load_shares(symbols: List[str]) -> Dict[str, int]:
    """讀 data/shares_outstanding.json + 各策略子目錄的 shares 設定。"""
    shares: Dict[str, int] = {}
    # 主 data/
    p = package_root() / "data" / "shares_outstanding.json"
    if p.exists():
        j = json.loads(p.read_text(encoding="utf-8"))
        shares.update({k.upper(): int(v) for k, v in (j.get("shares") or {}).items()})
    return shares


def fetch_factor_values(
    needed: List[str],
    all_symbols: List[str],
    api_key: str,
    api_secret: str,
    market: str = "us",
) -> Dict[str, Dict[str, float]]:
    """抓所需 factor values。資料源依市場：us→Alpaca、tw→yfinance(.TW)。

    支援的 factor：
      "price"           — 最新收盤
      "market_cap"      — price × shares_outstanding
      "price_momentum_Nm" — N 個月動能
    """
    if market == "tw":
        from engine import yf_factors as mc   # 台股：yfinance（.TW），不需 API key
    else:
        import market_cap as mc               # 美股：Alpaca（即時 IEX）

    out: Dict[str, Dict[str, float]] = {}

    # 1. 最新價格（總是抓，多 factor 共用）
    needs_latest = ("price" in needed) or ("market_cap" in needed)
    if needs_latest:
        out["price"] = mc.fetch_latest_prices(
            all_symbols, api_key=api_key, secret_key=api_secret,
        )

    # 2. market_cap = price × shares（台股股數也走 yfinance）
    if "market_cap" in needed:
        shares = mc.load_shares(all_symbols) if market == "tw" else _load_shares(all_symbols)
        prices = out["price"]
        out["market_cap"] = {
            s: prices[s] * shares[s]
            for s in all_symbols
            if s in prices and shares.get(s, 0) > 0
        }

    # 3. price_momentum_Nm — 需要歷史 bars
    mom_factors = [f for f in needed if _parse_momentum_months(f) is not None]
    if mom_factors:
        max_months = max(_parse_momentum_months(f) for f in mom_factors)
        days_needed = _TRADING_DAYS_PER_MONTH.get(max_months, max_months * 21) + 30
        history = mc.fetch_bars_history_batch(
            all_symbols, api_key=api_key, secret_key=api_secret, days=days_needed,
        )
        # 用 history 最新一筆覆蓋 price (更準)
        if "price" not in out:
            out["price"] = {}
        for s, df in history.items():
            if df is not None and len(df) > 0:
                out["price"][s] = float(df["close"].iloc[-1])

        for f in mom_factors:
            months = _parse_momentum_months(f)
            td = _TRADING_DAYS_PER_MONTH.get(months, months * 21)
            vals: Dict[str, float] = {}
            for s, df in history.items():
                if df is not None and len(df) >= td + 1:
                    past = float(df["close"].iloc[-(td + 1)])
                    now = float(df["close"].iloc[-1])
                    if past > 0:
                        vals[s] = now / past - 1.0
            out[f] = vals

    return out


# ════════════════════════════════════════════════════════════════════════
#  Frequency 守門
# ════════════════════════════════════════════════════════════════════════

def _is_first_trading_day_of_month(client, today: date) -> bool:
    """判斷 today 是否為本月第一個交易日（呼叫 Alpaca /v2/calendar）。

    fail-closed：任何例外都回 False（寧可不下單也不重複下）。
    """
    try:
        first_of_month = today.replace(day=1)
        resp = client._request(
            "GET",
            f"{client.base_url}/v2/calendar",
            params={"start": first_of_month.isoformat(), "end": today.isoformat()},
        )
        calendar = resp.json()
        if not calendar:
            return False
        trading_dates = sorted(entry["date"] for entry in calendar)
        return today.isoformat() == trading_dates[0]
    except Exception as e:
        logger.warning("是否月初首交易日判斷失敗：%s（fail-closed）", e)
        return False


def should_snapshot_on_skip(trigger_code: str, dry_run: bool) -> bool:
    """守門擋下時是否仍要更新 NAV 快照（每日報告要新鮮）。

    交易日但非換股日（月度/週度頻率擋下）→ True：仍刷新 NAV、存 state、不交易。
    非交易日（假日/休市）→ False：當天沒有新 NAV，整個跳過。
    """
    if dry_run:
        return False
    return trigger_code != "non_trading_day"


def _save_nav_snapshot(client, data_dir, today, log) -> None:
    """非換股日：抓當前 NAV/持倉、保留上次選股/排名，存 state（未交易）。"""
    import json
    import portfolio as pf
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    nav, cash = client.get_account_nav()
    positions = client.get_current_positions()
    prev: dict = {}
    p = data_dir / "portfolio_state.json"
    if p.exists():
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            prev = {}
    state = pf.PortfolioState(
        date=today.isoformat(), nav=nav, cash=cash, positions=positions,
        top10=prev.get("top10") or [],
        orders_executed=[],
        ranked_stocks=prev.get("ranked_stocks") or [],
    )
    pf.save_state(state, path=p)
    pf.append_history(state, path=data_dir / "portfolio_state_history.json")
    log.info("非換股日：NAV 快照已更新（未交易）→ %s", data_dir)


def apply_force_override(should_run: bool, trigger_code: str) -> tuple[bool, bool, str]:
    """FORCE_REBALANCE=true 時覆蓋頻率守門（手動驗證下單 / 臨時手動換股）。

    回傳 (是否被強制覆蓋, 最終 should_run, 最終 trigger_code)。
    """
    if not should_run and os.environ.get("FORCE_REBALANCE", "").lower() == "true":
        return True, True, f"forced({trigger_code})"
    return False, should_run, trigger_code


def gate_check(spec: dict, client, today: date, dry_run: bool) -> tuple[bool, str]:
    """守門：回傳 (應該跑, trigger_code)。

    應該跑 = True → 繼續執行 rebalance
    應該跑 = False → 跳過（守門擋下）
    """
    reb = spec.get("rebalancing") or {}
    freq = reb.get("frequency", "daily")

    # 交易日基本檢查
    if not client.is_trading_day(today):
        return False, "non_trading_day"

    # dry_run 模式下不執行 frequency 守門（為了完整測試流程）
    if dry_run:
        return True, f"{freq}_dryrun"

    if freq == "monthly":
        rebal_on = reb.get("rebalance_on", "first_trading_day")
        if rebal_on == "first_trading_day":
            if not _is_first_trading_day_of_month(client, today):
                return False, "not_first_trading_day_of_month"
        return True, "monthly_first_day"

    if freq == "weekly":
        # 預設週五（與 backtest spec_engine._rebal_dates 對齊）
        dow_cfg = (reb.get("day_of_week") or "FRI").upper()
        dow_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}
        expected = dow_map.get(dow_cfg, 4)
        if today.weekday() != expected:
            return False, f"not_weekly_day_{dow_cfg}"
        return True, "weekly_scheduled"

    # daily
    return True, "daily_scheduled"


# ════════════════════════════════════════════════════════════════════════
#  Main entry
# ════════════════════════════════════════════════════════════════════════

def run(
    strategy_id: str,
    account_id: str,
    data_dir: Path,
    dry_run: bool = False,
    date_override: Optional[str] = None,
) -> int:
    """執行單一帳戶 + 策略的再平衡。回傳 exit code。"""
    log = logging.getLogger(f"runner.{strategy_id}")
    log.info("=" * 60)
    log.info("runner  account=%s  strategy=%s  dry_run=%s",
             account_id, strategy_id, dry_run)

    # ── Step 1: 載入策略 ─────────────────────────────────────────────
    spec_path = package_root() / "strategies" / f"{strategy_id}.json"
    if not spec_path.exists():
        log.error("策略檔不存在：%s", spec_path)
        return 1
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    log.info("策略：%s v%s", spec.get("meta", {}).get("name", strategy_id),
             spec.get("version", "?"))

    # ── Step 2: 建立 BrokerClient ───────────────────────────────────
    try:
        from brokers.from_env import build_client_for_account
        client = build_client_for_account(account_id)
        log.info("Broker：%s（環境：%s）", client.broker_id, client.environment)
    except Exception as e:
        log.error("建立 broker 客戶端失敗：%s", e)
        return 1

    # ── Step 3: 今日 + 守門 ─────────────────────────────────────────
    today = date.fromisoformat(date_override) if date_override else date.today()
    should_run, trigger_code = gate_check(spec, client, today, dry_run)
    forced, should_run, trigger_code = apply_force_override(should_run, trigger_code)
    if forced:
        log.warning("⚠️ FORCE_REBALANCE=true：覆蓋頻率守門，強制執行再平衡")
    if not should_run:
        log.info("守門擋下：%s（today=%s）", trigger_code, today)
        try:
            import trade_log as tl
            tl.record_skip(
                account_id=account_id, strategy=strategy_id,
                reason_code=trigger_code,
                reason_human=f"runner gate: {trigger_code}",
                today=today.isoformat(),
            )
        except Exception:
            pass
        # 交易日但非換股日 → 仍更新 NAV 快照，讓每日報告新鮮（只是不交易）
        if should_snapshot_on_skip(trigger_code, dry_run):
            try:
                _save_nav_snapshot(client, data_dir, today, log)
            except Exception as e:  # noqa: BLE001
                log.warning("非換股日 NAV 快照失敗：%s", e)
        return 0

    log.info("守門通過，trigger=%s", trigger_code)

    # ── Step 4: 載入 universe（market 由券商 spec 推定，供 market_group 解析）──
    market = "tw" if (getattr(client, "spec", {}) or {}).get(
        "market", {}).get("currency") == "TWD" else "us"
    groups = load_universe_groups(spec, market)
    all_syms = sorted({s for g in groups.values() for s in g})
    log.info("Universe：%d 檔（%d 組，market=%s）", len(all_syms), len(groups), market)

    # ── Step 5: 抓 factor values ────────────────────────────────────
    from engine.selection import required_factors, select_portfolio
    needed = required_factors(spec)
    log.info("需要 factors：%s", needed)

    factor_values = fetch_factor_values(
        needed, all_syms,
        api_key=getattr(client, "api_key", ""),
        api_secret=getattr(client, "api_secret", ""),
        market=market,
    )
    log.info("已取得 %d 個 factor", len(factor_values))

    # valid = 有最新報價的 symbol
    valid = set((factor_values.get("price") or {}).keys())

    # ── Step 6: 選股 ────────────────────────────────────────────────
    picks = select_portfolio(spec, groups, factor_values, valid_symbols=valid)
    log.info("選股結果：%d 檔 → %s", len(picks), picks)

    # ── Step 7: 帳戶狀態 + 算 rebalance ─────────────────────────────
    import portfolio as pf
    nav, cash = client.get_account_nav()
    positions = client.get_current_positions()
    log.info("帳戶 NAV=$%.2f 現金=$%.2f 持倉=%d", nav, cash, len(positions))

    prices = factor_values.get("price", {})
    target_weight = 1.0 / max(int(spec.get("portfolio", {}).get("target_n") or len(picks)), 1)

    orders = pf.calculate_rebalance(
        current_positions=positions,
        top10_symbols=picks,
        current_prices=prices,
        account_nav=nav,
        available_cash=cash,
        target_weight=target_weight,
        trigger=trigger_code,
        account_id=account_id,
        strategy=strategy_id,
    )

    # ── Step 8: 執行 ────────────────────────────────────────────────
    import trader as tr
    tr.execute_rebalance(
        client, orders, dry_run=dry_run,
        account_id=account_id, strategy=strategy_id,
    )

    # ── Step 9: 存 state ────────────────────────────────────────────
    if not dry_run and orders:
        nav, cash = client.get_account_nav()
        positions = client.get_current_positions()

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 候選池排名快照（含真實股價）→ dashboard/報告「市值前N候選池」用真實資料
    from engine.selection import universe_ranking
    mcap = factor_values.get("market_cap", {})
    chg  = factor_values.get("change_pct") or factor_values.get("chg_pct") or {}
    picks_set = set(picks)
    ranked_stocks = [
        {"symbol": s, "rank": i + 1,
         "price":      float(prices.get(s, 0.0) or 0.0),
         "market_cap": float(mcap.get(s, 0.0) or 0.0),
         "chg_pct":    float(chg.get(s, 0.0) or 0.0),
         "in_portfolio": s in picks_set}
        for i, s in enumerate(
            universe_ranking(spec, groups, factor_values, valid_symbols=valid))
    ]

    state = pf.PortfolioState(
        date=today.isoformat(),
        nav=nav, cash=cash,
        positions=positions,
        top10=picks,
        orders_executed=orders,
        ranked_stocks=ranked_stocks,
    )
    pf.save_state(state, path=data_dir / "portfolio_state.json")
    pf.append_history(state, path=data_dir / "portfolio_state_history.json")
    log.info("State 已儲存 → %s", data_dir)

    return 0


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Universal strategy runner")
    parser.add_argument("strategy", help="strategy id (對應 strategies/{id}.json)")
    # 預設 account id：優先新版 ACCOUNT_ID，向下相容舊版 TOP10_ACCOUNT_ID
    _default_acc = (os.environ.get("ACCOUNT_ID")
                    or os.environ.get("TOP10_ACCOUNT_ID")
                    or "1")
    parser.add_argument("--account", default=_default_acc,
                        help="account id（accounts.json 的 id 欄位）")
    parser.add_argument("--data-dir", default=None,
                        help="持倉資料目錄（預設 data/{account_id}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只計算不下單")
    parser.add_argument("--date-override", default=None,
                        help="覆寫今日（YYYY-MM-DD），測試用")
    args = parser.parse_args()

    dr = args.dry_run or os.environ.get("DRY_RUN", "").lower() == "true"
    dd = Path(args.data_dir) if args.data_dir else workdir() / "data" / args.account

    sys.exit(run(
        strategy_id=args.strategy,
        account_id=args.account,
        data_dir=dd,
        dry_run=dr,
        date_override=args.date_override,
    ))


if __name__ == "__main__":
    main()
