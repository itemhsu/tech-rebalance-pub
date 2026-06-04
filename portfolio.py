"""
portfolio.py — 持倉管理與再平衡邏輯
計算再平衡訂單，管理持倉狀態的序列化/反序列化。
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

STATE_PATH         = Path(__file__).parent / "data" / "portfolio_state.json"
HISTORY_PATH       = Path(__file__).parent / "data" / "portfolio_state_history.json"

# ── 常數 ────────────────────────────────────────────────────────────────────
MIN_ORDER_VALUE    = 1.0    # USD，Alpaca fractional 訂單最小金額
CASH_BUFFER_PCT    = 0.01   # 下單時保留 1% 現金緩衝，應對 slippage
WEIGHT_TOLERANCE   = 0.02   # ±2% 容忍帶，帶內不調整
CASH_DEPLOY_THRESH = 0.01   # 現金超過 NAV 1% 才觸發部署
TOP_N              = 10
TARGET_WEIGHT      = 0.10


# ── 資料結構 ─────────────────────────────────────────────────────────────────
@dataclass
class Position:
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float         # = qty × current_price
    unrealized_pl: float        # = market_value - qty × avg_entry_price
    unrealized_plpc: float      # = unrealized_pl / (qty × avg_entry_price)


@dataclass
class RebalanceOrder:
    symbol: str
    action: str          # "BUY" | "SELL"
    qty: float
    reason: str          # "exit_top10" | "new_entrant" | "weight_adjust" | "cash_deployment"
    estimated_value: float = 0.0
    # ── 結構化欄位（提供給 trade_log 用，舊呼叫者預設為 0）────────────────────
    trigger: str = ""           # 觸發來源 (monthly_first_day / composition_change / ...)
    pre_qty: float = 0.0        # 下單前持股數
    post_qty: float = 0.0       # 下單後預期持股數
    current_weight: float = 0.0 # 下單前權重
    target_weight: float = 0.0  # 理論目標權重


@dataclass
class PortfolioState:
    date: str
    nav: float
    cash: float
    positions: list[Position] = field(default_factory=list)
    top10: list[str]          = field(default_factory=list)
    orders_executed: list[RebalanceOrder] = field(default_factory=list)
    ranked_stocks: list[dict] = field(default_factory=list)  # 完整市值排名快照


# ── 再平衡演算法 ─────────────────────────────────────────────────────────────
def calculate_rebalance(
    current_positions: list[Position],
    top10_symbols: list[str],
    current_prices: dict[str, float],
    account_nav: float,
    available_cash: float,
    target_weight: float = TARGET_WEIGHT,
    tolerance: float     = WEIGHT_TOLERANCE,
    trigger: str         = "",
    account_id: str      = "",
    strategy: str        = "",
) -> list[RebalanceOrder]:
    """
    核心再平衡演算法（Steps A-G）。

    ── 換股守則（minimum swap）──
    1. exit_top10：跌出 Top N 的股票才全清。
    2. continuing：持續在 Top N 的股票，只在偏離目標權重 > tolerance 時才動，
       且只下「差額」量，不全賣再全買。
    3. new_entrant：新進 Top N 才建倉。
    4. cash_deployment：賣 ORCL 後的閒置現金分散到剩餘 Top N，金額是「差額」。

    回傳需執行的訂單清單（SELL 在前，BUY 在後）。每筆 order 帶完整脈絡
    (pre_qty / post_qty / current_weight / target_weight / trigger)。
    """
    # 結構化事件 log；import 失敗時不影響核心邏輯
    try:
        import trade_log
    except ImportError:
        trade_log = None  # type: ignore

    orders: list[RebalanceOrder] = []

    if account_nav <= 0:
        logger.warning("account_nav <= 0，跳過再平衡")
        return orders

    # ── Step A：識別異動股票 ─────────────────────────────────────────────────
    current_syms   = {p.symbol for p in current_positions}
    top10_set      = set(top10_symbols)
    to_sell        = current_syms - top10_set      # 跌出前 N：全數賣出
    new_entrants   = top10_set   - current_syms    # 新進前 N：需買入
    continuing     = current_syms & top10_set      # 持續在前 N：視偏差調整

    pos_map = {p.symbol: p for p in current_positions}
    target_value = account_nav * target_weight

    def _emit_plan(order: RebalanceOrder, *, deviation: float = 0.0):
        """寫一筆 ORDER_PLANNED 事件到 jsonl。"""
        if trade_log is None or not account_id:
            return
        trade_log.record_order_plan(
            account_id=account_id, strategy=strategy,
            symbol=order.symbol, action=order.action,
            qty=order.qty, est_value=order.estimated_value,
            reason=order.reason, trigger=order.trigger,
            pre_qty=order.pre_qty, post_qty=order.post_qty,
            current_weight=order.current_weight,
            target_weight=order.target_weight,
        )

    # ── Step B：賣出跌出前 N 的股票（全清，因為已不在持有名單）────────────
    estimated_proceeds = 0.0
    for sym in sorted(to_sell):
        pos = pos_map[sym]
        qty = math.floor(pos.qty)
        if qty > 0:
            px = current_prices.get(sym) or pos.current_price
            val = qty * px
            cw = pos.market_value / account_nav if account_nav else 0.0
            o = RebalanceOrder(
                symbol=sym, action="SELL", qty=qty,
                reason="exit_top10", estimated_value=val,
                trigger=trigger,
                pre_qty=pos.qty, post_qty=0.0,
                current_weight=cw, target_weight=0.0,
            )
            orders.append(o); _emit_plan(o)
            estimated_proceeds += val
            logger.info("SELL %s × %d（exit_top10, ~$%.2f, weight %.1f%%→0%%）",
                        sym, qty, val, cw * 100)

    projected_cash = available_cash + estimated_proceeds

    # ── Step D：調整持續持股的偏差（容忍帶外才動，只下差額量）──────────────
    for sym in sorted(continuing):
        pos = pos_map[sym]
        px  = current_prices.get(sym, pos.current_price)
        if px <= 0:
            continue
        current_weight = pos.market_value / account_nav
        deviation = abs(current_weight - target_weight)

        if deviation <= tolerance:
            continue  # 容忍帶內，不調整 ← 這就是「最小量」精神

        diff = target_value - pos.market_value
        qty  = math.floor(abs(diff) / px)
        val  = qty * px

        if val < MIN_ORDER_VALUE:
            continue

        if diff > 0:
            o = RebalanceOrder(
                symbol=sym, action="BUY", qty=qty,
                reason="weight_adjust", estimated_value=val,
                trigger=trigger,
                pre_qty=pos.qty, post_qty=pos.qty + qty,
                current_weight=current_weight, target_weight=target_weight,
            )
            orders.append(o); _emit_plan(o, deviation=deviation)
            logger.info("BUY  %s × %d（weight_adjust %.1f%%→%.1f%%, +$%.2f）",
                        sym, qty, current_weight * 100, target_weight * 100, val)
        else:
            o = RebalanceOrder(
                symbol=sym, action="SELL", qty=qty,
                reason="weight_adjust", estimated_value=val,
                trigger=trigger,
                pre_qty=pos.qty, post_qty=pos.qty - qty,
                current_weight=current_weight, target_weight=target_weight,
            )
            orders.append(o); _emit_plan(o, deviation=deviation)
            logger.info("SELL %s × %d（weight_adjust %.1f%%→%.1f%%, -$%.2f）",
                        sym, qty, current_weight * 100, target_weight * 100, val)

    # ── Step E：買入新進前 N 名 ────────────────────────────────────────────
    for sym in sorted(new_entrants):
        px = current_prices.get(sym, 0.0)
        if px <= 0:
            logger.warning("無法取得 %s 報價，跳過 new_entrant 買入", sym)
            continue
        buy_val = min(target_value, projected_cash * (1 - CASH_BUFFER_PCT))
        qty     = math.floor(buy_val / px)
        val     = qty * px

        if val < MIN_ORDER_VALUE:
            continue

        o = RebalanceOrder(
            symbol=sym, action="BUY", qty=qty,
            reason="new_entrant", estimated_value=val,
            trigger=trigger,
            pre_qty=0.0, post_qty=qty,
            current_weight=0.0, target_weight=target_weight,
        )
        orders.append(o); _emit_plan(o)
        projected_cash -= val
        logger.info("BUY  %s × %d（new_entrant, ~$%.2f, 0%%→%.1f%%）",
                    sym, qty, val, target_weight * 100)

    # ── Step F：部署剩餘閒置現金（差額均分到剩餘 Top N）──────────────────
    cash_threshold = account_nav * CASH_DEPLOY_THRESH
    if projected_cash > cash_threshold:
        already_buying  = {o.symbol for o in orders if o.action == "BUY"}
        already_selling = {o.symbol for o in orders if o.action == "SELL"}
        targets = [s for s in top10_symbols
                   if s not in already_buying and s not in already_selling]

        if targets:
            cash_per = projected_cash / len(targets) * (1 - CASH_BUFFER_PCT)
            for sym in targets:
                px = current_prices.get(sym, 0.0)
                if px <= 0:
                    continue
                qty = math.floor(cash_per / px)
                val = qty * px
                if val < MIN_ORDER_VALUE:
                    continue
                pos = pos_map.get(sym)
                pre = pos.qty if pos else 0.0
                cw = (pos.market_value / account_nav) if pos and account_nav else 0.0
                o = RebalanceOrder(
                    symbol=sym, action="BUY", qty=qty,
                    reason="cash_deployment", estimated_value=val,
                    trigger=trigger,
                    pre_qty=pre, post_qty=pre + qty,
                    current_weight=cw, target_weight=target_weight,
                )
                orders.append(o); _emit_plan(o)
                logger.info("BUY  %s × %d（cash_deploy, +$%.2f, %.1f%%→%.1f%%）",
                            sym, qty, val, cw * 100, target_weight * 100)

    # ── Step G：排序（SELL 優先）─────────────────────────────────────────
    orders.sort(key=lambda o: (0 if o.action == "SELL" else 1, o.symbol))

    sells = [o for o in orders if o.action == "SELL"]
    buys  = [o for o in orders if o.action == "BUY"]

    # ── 換股守則 (minimum swap) 驗證 ──
    # 規則：若 continuing 中有股票，「不可能既在 SELL 又在 BUY」（除非容忍帶外
    # 出現精度問題）。同時也要證明「保留股的下單不超過總量」。
    swap_violation = []
    sell_syms = {o.symbol for o in sells}
    buy_syms = {o.symbol for o in buys}
    overlap = sell_syms & buy_syms
    if overlap:
        swap_violation.append(f"同檔同時出現 SELL+BUY：{sorted(overlap)}")

    # 保留股若 SELL 不可超過原持股量
    for o in sells:
        if o.symbol in continuing:
            pos = pos_map[o.symbol]
            if o.qty >= pos.qty:
                swap_violation.append(
                    f"{o.symbol} 保留股卻全清 ({o.qty}/{pos.qty})"
                )

    minimum_swap_ok = not swap_violation
    note = "PASS — 最小量換股守則通過" if minimum_swap_ok else \
           "VIOLATION — " + "; ".join(swap_violation)

    # 統計各 reason 個數
    reason_count = {"exit_top10": 0, "new_entrant": 0,
                    "weight_adjust": 0, "cash_deployment": 0}
    for o in orders:
        reason_count[o.reason] = reason_count.get(o.reason, 0) + 1

    logger.info(
        "再平衡計劃：continuing=%d, exit=%d, new=%d  → 賣 %d 筆 + 買 %d 筆  [%s]",
        len(continuing), len(to_sell), len(new_entrants),
        len(sells), len(buys),
        "保留股不全清" if minimum_swap_ok else "⚠️ 違反守則"
    )

    # 寫 REBALANCE_SUMMARY 結構化事件
    if trade_log is not None and account_id:
        try:
            from datetime import date as _date
            trade_log.record_summary(
                account_id=account_id, strategy=strategy,
                today=_date.today().isoformat(),
                continuing=len(continuing), exit_n=len(to_sell),
                new_entrant=len(new_entrants),
                weight_adjust=reason_count["weight_adjust"],
                cash_deploy=reason_count["cash_deployment"],
                sells=len(sells), buys=len(buys),
                minimum_swap_check=minimum_swap_ok,
                minimum_swap_note=note,
            )
        except Exception as e:
            logger.warning("trade_log.record_summary 失敗：%s", e)

    if not minimum_swap_ok:
        logger.error("⚠️ 最小量換股守則違反：%s", note)
        # 不阻斷流程，但會被收到 trade_log 內 minimum_swap_check=false，方便監控
    return orders


# ── 輔助：計算 NAV ────────────────────────────────────────────────────────────
def calculate_nav(positions: list[Position], cash: float) -> float:
    return cash + sum(p.market_value for p in positions)


# ── 持倉快照序列化 ────────────────────────────────────────────────────────────
def _to_dict(obj) -> dict:
    """遞迴轉換 dataclass 為 dict（含 list 內的 dataclass）。"""
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    try:
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    except TypeError:
        return obj


def save_state(state: PortfolioState, path: Path = STATE_PATH) -> None:
    """序列化持倉快照到 JSON 檔案。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_to_dict(state), f, ensure_ascii=False, indent=2)
    logger.info("持倉快照已儲存：%s", path)


def load_state(path: Path = STATE_PATH) -> Optional[PortfolioState]:
    """讀取持倉快照，不存在時回傳 None。"""
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    positions = [Position(**p) for p in data.get("positions", [])]
    orders    = [RebalanceOrder(**o) for o in data.get("orders_executed", [])]
    return PortfolioState(
        date=data["date"],
        nav=data["nav"],
        cash=data["cash"],
        positions=positions,
        top10=data.get("top10", []),
        orders_executed=orders,
        ranked_stocks=data.get("ranked_stocks", []),
    )


def append_history(state: PortfolioState, path: Path = HISTORY_PATH) -> None:
    """將今日 NAV 快照追加至歷史記錄檔。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {"initial_nav": state.nav, "start_date": state.date, "history": []}

    # 防重複（同日覆蓋）
    history["history"] = [
        h for h in history["history"] if h["date"] != state.date
    ]
    # 序列化 orders_executed（dataclass → dict，含 side 欄位供 migrate_to_mvp 使用）
    orders_serialized = []
    for o in state.orders_executed:
        orders_serialized.append({
            "symbol": o.symbol,
            "side":   o.action.lower(),   # "buy" / "sell"（相容 migrate_to_mvp）
            "qty":    o.qty,
            "price":  o.estimated_value / o.qty if o.qty else 0,
            "reason": o.reason,
        })

    history["history"].append({
        "date":            state.date,
        "nav":             round(state.nav, 2),
        "cash":            round(state.cash, 2),
        "top10":           state.top10,
        "orders_executed": orders_serialized,
        "trades_count":    len(orders_serialized),
    })
    # 按日期排序
    history["history"].sort(key=lambda h: h["date"])

    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    logger.info("NAV 歷史已更新：%s（共 %d 筆）", state.date, len(history["history"]))
