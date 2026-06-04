"""
harvest.py — 稅務增益收割（Tax-Gain Harvesting）

兩種執行模式：
  計算模式（預設 / 由 main.py 呼叫）：
    分析當前持倉，計算可收割空間，回傳 HarvestPlan（含郵件確認連結）

  執行模式（--execute，由 GitHub Actions harvest.yml 觸發）：
    重新抓取當前倉位 → 重算 → 賣出 + 即刻回買 → 更新歷史記錄 → 寄確認信

稅務規則（2026，可更新至新年度）：
  聯邦 0% LTCG 級距上限：Single $49,450 / MFJ $98,900
  WA 州資本利得稅：7%（超過 $278,000 免稅額）
  假設所有持倉均已持有 > 1 年（Paper Trading 場景，實盤需核查持有期限）
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import urllib.parse
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 稅務常數（每年可更新）────────────────────────────────────────────────────
FEDERAL_0PCT = {
    "single": 49_450,   # 2026 Single
    "mfj":    98_900,   # 2026 Married Filing Jointly
}
WA_DEDUCTION  = 278_000   # WA 州 CG 免稅額
WA_RATE       = 0.07      # WA 7%
FED_NEXT_RATE = 0.15      # 超出 0% 級距的下一段聯邦稅率（15%，估算節稅用）

# ── 資料路徑 ─────────────────────────────────────────────────────────────────
DATA_DIR      = Path(__file__).parent / "data"
HARVEST_HIST  = DATA_DIR / "harvest_history.json"

# GitHub Pages 確認頁面（與 dashboard 同 repo）
DEFAULT_CONFIRM_PAGE = "https://itemhsu.github.io/tech-rebalance-dashboard/harvest_confirm.html"


# ── 資料結構 ─────────────────────────────────────────────────────────────────

@dataclass
class HarvestItem:
    ticker:         str
    shares:         int       # 建議收割股數（賣出後立刻回買）
    avg_cost:       float     # 每股平均成本
    current_price:  float     # 當前市價（下單時可能已變動）
    gain_per_share: float     # = current_price - avg_cost
    realized_gain:  float     # = gain_per_share × shares


@dataclass
class HarvestPlan:
    items:           list[HarvestItem]
    filing_status:   str
    ordinary_income: float
    wa_resident:     bool

    federal_space:   float   # 聯邦 0% 剩餘空間
    wa_space:        float   # WA 免稅額剩餘空間（非 WA 居民 = 999_999）
    harvest_room:    float   # = min(federal_space, wa_space)

    total_gain:      float   # 本次計劃實現的總增益
    tax_saved:       float   # 估算節稅金額（按下一稅率 15% 計算）
    as_of:           str     # 計算日期

    ytd_harvested:   float   # 本年度已收割累計（不含本次）
    confirm_url:     str = ""   # 郵件確認按鈕連結


# ── 歷史記錄 I/O ──────────────────────────────────────────────────────────────

def _current_year() -> int:
    return datetime.now(timezone(timedelta(hours=8))).year


def load_harvest_history() -> dict:
    """載入本年度收割記錄（不存在則回傳空記錄）。"""
    if not HARVEST_HIST.exists():
        return {"year": _current_year(), "ytd_harvested": 0.0, "events": []}
    with open(HARVEST_HIST, encoding="utf-8") as f:
        hist = json.load(f)
    # 若跨年，重置
    if hist.get("year") != _current_year():
        return {"year": _current_year(), "ytd_harvested": 0.0, "events": []}
    return hist


def save_harvest_history(hist: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(HARVEST_HIST, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    logger.info("收割歷史已更新：本年累計 $%.2f", hist["ytd_harvested"])


def record_harvest_event(items: list[HarvestItem], total_gain: float) -> None:
    """將本次收割事件寫入 harvest_history.json。"""
    hist = load_harvest_history()
    hist["ytd_harvested"] = hist.get("ytd_harvested", 0.0) + total_gain
    hist.setdefault("events", []).append({
        "date":       date.today().isoformat(),
        "total_gain": round(total_gain, 2),
        "items": [
            {
                "ticker":        it.ticker,
                "shares":        it.shares,
                "gain_per_share": round(it.gain_per_share, 4),
                "realized_gain":  round(it.realized_gain, 2),
            }
            for it in items
        ],
    })
    save_harvest_history(hist)


# ── 主計算邏輯 ────────────────────────────────────────────────────────────────

def compute_harvest(
    positions,                       # list of portfolio.Position
    filing_status: str   = "single",
    wa_resident:   bool  = True,
    ordinary_income: float = 10_000,
    confirm_token:   str = "",       # GitHub PAT，用於生成確認連結
    confirm_page:    str = DEFAULT_CONFIRM_PAGE,
) -> Optional[HarvestPlan]:
    """
    根據當前持倉計算可收割的增益，回傳 HarvestPlan。
    若無可收割項目（全部虧損或空間為 0）回傳 None。
    """
    filing_status = filing_status.lower()
    if filing_status not in FEDERAL_0PCT:
        logger.warning("未知 filing_status=%s，改用 single", filing_status)
        filing_status = "single"

    # ── 計算稅務空間 ─────────────────────────────────────────────────────────
    hist           = load_harvest_history()
    ytd_harvested  = hist.get("ytd_harvested", 0.0)

    federal_limit  = FEDERAL_0PCT[filing_status]
    federal_space  = max(0.0, federal_limit - ordinary_income - ytd_harvested)

    if wa_resident:
        wa_space   = max(0.0, WA_DEDUCTION - ytd_harvested)
    else:
        wa_space   = 999_999.0

    harvest_room   = min(federal_space, wa_space)

    if harvest_room <= 0:
        logger.info("收割空間為 0（本年已用盡或普通所得太高），跳過")
        return None

    # ── 找出有帳面獲利的持倉（候選）──────────────────────────────────────────
    candidates = []
    for p in positions:
        gain_per_share = p.current_price - p.avg_entry_price
        if gain_per_share <= 0:
            continue   # 虧損或打平，不需收割
        total_gain = gain_per_share * p.qty
        if total_gain < 1.0:
            continue   # 增益太小
        candidates.append((p, gain_per_share, total_gain))

    if not candidates:
        logger.info("無含浮盈持倉，無需收割")
        return None

    # ── 按每股增益降冪排序（先收效益最高的）────────────────────────────────
    candidates.sort(key=lambda x: x[1], reverse=True)

    items          = []
    remaining_room = harvest_room

    for p, gain_per_share, _ in candidates:
        if remaining_room <= 0:
            break
        # 最多收割多少股才不超出空間
        max_shares = min(int(p.qty), math.floor(remaining_room / gain_per_share))
        if max_shares <= 0:
            continue
        realized = gain_per_share * max_shares
        items.append(HarvestItem(
            ticker        = p.symbol,
            shares        = max_shares,
            avg_cost      = round(p.avg_entry_price, 4),
            current_price = round(p.current_price, 4),
            gain_per_share= round(gain_per_share, 4),
            realized_gain = round(realized, 2),
        ))
        remaining_room -= realized

    if not items:
        return None

    total_gain = sum(it.realized_gain for it in items)
    tax_saved  = round(total_gain * FED_NEXT_RATE, 2)

    # ── 生成確認連結 ──────────────────────────────────────────────────────────
    confirm_url = ""
    if confirm_token:
        tickers_str = ",".join(it.ticker for it in items)
        fragment = urllib.parse.urlencode({
            "token":  confirm_token,
            "date":   date.today().isoformat(),
            "gain":   f"{total_gain:.0f}",
            "saved":  f"{tax_saved:.0f}",
            "tickers": tickers_str,
        })
        confirm_url = f"{confirm_page}#{fragment}"

    plan = HarvestPlan(
        items          = items,
        filing_status  = filing_status,
        ordinary_income= ordinary_income,
        wa_resident    = wa_resident,
        federal_space  = round(federal_space, 2),
        wa_space       = round(wa_space, 2),
        harvest_room   = round(harvest_room, 2),
        total_gain     = round(total_gain, 2),
        tax_saved      = tax_saved,
        as_of          = date.today().isoformat(),
        ytd_harvested  = ytd_harvested,
        confirm_url    = confirm_url,
    )
    logger.info(
        "收割計劃：%d 檔，增益 $%.0f，估算節稅 $%.0f",
        len(items), total_gain, tax_saved,
    )
    return plan


# ── 執行收割（賣出 + 即刻回買）────────────────────────────────────────────────

def execute_harvest(
    client,                   # trader.AlpacaClient
    items: list[HarvestItem],
    dry_run: bool = False,
) -> bool:
    """
    依序執行：先賣出所有候選股，等待成交，再以市價回買相同股數。
    回傳 True 表示全部訂單送出成功（不保證成交）。
    """
    from trader import execute_rebalance
    from portfolio import RebalanceOrder

    if dry_run:
        logger.info("[DRY RUN] 模擬收割訂單：")
        for it in items:
            logger.info(
                "  SELL %s ×%d（增益 $%.2f/股）→ BUY 回",
                it.ticker, it.shares, it.gain_per_share,
            )
        return True

    # 建立 SELL 訂單（先賣）
    sells = [
        RebalanceOrder(
            symbol          = it.ticker,
            action          = "SELL",
            qty             = it.shares,
            reason          = "tax_harvest",
            estimated_value = it.current_price * it.shares,
        )
        for it in items
    ]
    # 建立 BUY 訂單（立刻回買，成本墊高）
    buys = [
        RebalanceOrder(
            symbol          = it.ticker,
            action          = "BUY",
            qty             = it.shares,
            reason          = "tax_harvest_rebuy",
            estimated_value = it.current_price * it.shares,
        )
        for it in items
    ]

    all_orders = sells + buys

    # ── 下單前：若任一收割股票的 SELL 已在 Alpaca 佇列，立即中止 ─────────────
    # 原因：execute_rebalance 會跳過重複的 SELL，但 BUY 仍會送出（不同 side key），
    # 導致持倉翻倍而成本基礎未步升，收割目的完全落空。
    try:
        _HARVEST_BLOCK_STATUSES = {"new", "pending_new", "accepted", "held", "partially_filled"}
        open_orders = client.get_open_orders()
        blocked = [
            it.ticker for it in items
            if any(
                o["symbol"] == it.ticker
                and o.get("side") == "sell"
                and o.get("status", "") in _HARVEST_BLOCK_STATUSES
                for o in open_orders
            )
        ]
        if blocked:
            logger.warning(
                "收割中止：下列股票已有賣單在佇列，為避免 BUY 在 SELL 前執行而持倉翻倍，"
                "跳過本次收割：%s",
                blocked,
            )
            return False
    except Exception as exc:
        logger.warning("無法檢查收割前佇列狀態（%s），繼續執行", exc)

    order_ids = execute_rebalance(client, all_orders, dry_run=False)

    # ── 驗證 SELL 訂單是否全數送出 ───────────────────────────────────────────
    # execute_rebalance 依序處理 SELL → BUY；order_ids 前段為 SELL、後段為 BUY。
    # 若 order_ids 總數少於 sells 數量，代表至少一筆 SELL 被跳過，
    # 此時應回報失敗，避免持倉不一致被掩蓋。
    if len(order_ids) < len(sells):
        logger.error(
            "收割訂單未完整送出（預期賣單 %d 筆，實際送出 %d 筆）。"
            "部分 SELL 可能被跳過，請手動確認帳戶持倉後重新執行。",
            len(sells), len(order_ids),
        )
        return False

    logger.info(
        "收割訂單送出完成：%d / %d 筆（SELL %d + BUY %d）",
        len(order_ids), len(all_orders), len(sells), len(buys),
    )
    return True


# ── CLI 入口（供 GitHub Actions harvest.yml 呼叫）────────────────────────────

def main() -> None:
    """
    GitHub Actions 執行模式：
      python harvest.py --execute [--dry-run]
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Tax-Gain Harvesting 執行器")
    parser.add_argument("--execute",  action="store_true",
                        help="實際執行收割訂單（否則只計算顯示）")
    parser.add_argument("--dry-run",  action="store_true",
                        help="模擬執行，不送出實際訂單")
    parser.add_argument("--filing-status", default="single",
                        choices=["single", "mfj"])
    parser.add_argument("--ordinary-income", type=float,
                        default=float(os.environ.get("HARVEST_ORDINARY_INCOME", "10000")))
    parser.add_argument("--wa-resident", type=lambda x: x.lower() == "true",
                        default=os.environ.get("HARVEST_WA_RESIDENT", "true").lower() == "true")
    args = parser.parse_args()

    # 載入 .env（本機開發）
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # 取得 Alpaca client
    try:
        import trader as tr
        client = tr.client_from_env()
    except KeyError as e:
        logger.error("缺少環境變數：%s", e)
        sys.exit(1)

    # 取得當前持倉
    positions = client.get_current_positions()
    if not positions:
        logger.info("無持倉，結束")
        return

    # 計算收割計劃
    plan = compute_harvest(
        positions       = positions,
        filing_status   = args.filing_status,
        wa_resident     = args.wa_resident,
        ordinary_income = args.ordinary_income,
    )

    if plan is None:
        logger.info("無收割機會（無浮盈或空間耗盡），結束")
        return

    # 列印計劃摘要
    logger.info("=" * 55)
    logger.info("稅務增益收割計劃 (%s)", plan.as_of)
    logger.info("  報稅身份  : %s", plan.filing_status)
    logger.info("  普通所得  : $%.0f", plan.ordinary_income)
    logger.info("  聯邦空間  : $%.0f", plan.federal_space)
    logger.info("  WA 空間   : $%.0f", plan.wa_space if plan.wa_resident else 9999999)
    logger.info("  收割空間  : $%.0f", plan.harvest_room)
    logger.info("  計劃實現  : $%.2f", plan.total_gain)
    logger.info("  估算節稅  : $%.2f (@15%%)", plan.tax_saved)
    logger.info("-" * 55)
    for it in plan.items:
        logger.info(
            "  %-6s ×%4d  成本 $%.2f → 現價 $%.2f  增益 $%.2f",
            it.ticker, it.shares, it.avg_cost, it.current_price, it.realized_gain,
        )
    logger.info("=" * 55)

    if not args.execute:
        logger.info("（計算模式，如需執行請加 --execute）")
        return

    # 執行收割
    dry = args.dry_run or os.environ.get("DRY_RUN", "false").lower() == "true"
    success = execute_harvest(client, plan.items, dry_run=dry)

    if success and not dry:
        # 記錄本次事件
        record_harvest_event(plan.items, plan.total_gain)
        logger.info("✅ 收割完成，歷史已更新")

        # 寄確認信
        try:
            import email_report as er
            import portfolio as pf
            state_path = pf.STATE_PATH
            if state_path.exists():
                state = pf.load_state()
                er.send_harvest_confirm_email(plan, state)
        except Exception as e:
            logger.warning("收割確認信寄送失敗（不影響主流程）：%s", e)

    elif dry:
        logger.info("[DRY RUN] 收割模擬完成，不實際下單也不更新歷史")


if __name__ == "__main__":
    main()
