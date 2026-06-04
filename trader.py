"""
trader.py — Alpaca API 交易執行
封裝所有 Alpaca REST API 呼叫，提供統一的交易介面。
支援 Paper Trading 與 Live Trading（透過 base_url 切換）。
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import date
from typing import Optional

import requests

from portfolio import Position, RebalanceOrder

logger = logging.getLogger(__name__)

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL  = "https://api.alpaca.markets"
DATA_URL  = "https://data.alpaca.markets"


class AuthenticationError(Exception):
    pass


class AlpacaClient:
    """Alpaca REST API 客戶端。"""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = PAPER_URL,
        data_url: str = DATA_URL,
    ):
        self.api_key    = api_key
        self.secret_key = secret_key
        self.base_url   = base_url.rstrip("/")
        self.data_url   = data_url.rstrip("/")
        self.is_paper   = "paper" in base_url
        self._headers   = {
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type":        "application/json",
            "Accept":              "application/json",
        }
        logger.info(
            "AlpacaClient 初始化（%s 模式）",
            "Paper" if self.is_paper else "LIVE ⚠️",
        )

    # ── 內部 HTTP 工具 ────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        url: str,
        max_retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        """帶指數退避的 HTTP 請求。"""
        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, url, headers=self._headers, timeout=15, **kwargs
                )
                if resp.status_code == 401:
                    raise AuthenticationError("Alpaca API 金鑰無效，請確認 ALPACA_API_KEY / SECRET。")
                if resp.status_code == 403:
                    raise PermissionError(f"Alpaca API 無存取權限：{url}")
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limit (429)，等待 %ds…", wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("Server error %d，等待 %ds…", resp.status_code, wait)
                    time.sleep(wait)
                    if attempt == max_retries - 1:
                        resp.raise_for_status()
                    continue
                return resp
            except (AuthenticationError, PermissionError):
                raise
            except requests.RequestException as e:
                wait = 2 ** attempt
                logger.warning("HTTP 請求失敗（attempt %d/%d）：%s，等待 %ds",
                               attempt + 1, max_retries, e, wait)
                time.sleep(wait)
                if attempt == max_retries - 1:
                    raise
        raise RuntimeError(f"超過重試次數：{url}")

    # ── 交易日曆 ──────────────────────────────────────────────────────────────

    def is_trading_day(self, check_date: Optional[date] = None) -> bool:
        """呼叫 /v2/calendar 確認指定日期是否為美股交易日。"""
        d = (check_date or date.today()).isoformat()
        resp = self._request("GET", f"{self.base_url}/v2/calendar",
                             params={"start": d, "end": d})
        calendar = resp.json()
        result = len(calendar) > 0
        logger.info("%s %s交易日", d, "是" if result else "不是")
        return result

    # ── 帳戶資訊 ──────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """取得帳戶資訊（equity、cash、portfolio_value 等）。"""
        resp = self._request("GET", f"{self.base_url}/v2/account")
        return resp.json()

    def get_account_nav(self) -> tuple[float, float]:
        """回傳 (equity_nav, cash)。"""
        acc  = self.get_account()
        nav  = float(acc.get("equity", acc.get("portfolio_value", 0)))
        cash = float(acc.get("cash", 0))
        logger.info("帳戶 NAV: $%.2f  現金: $%.2f", nav, cash)
        return nav, cash

    # ── 持倉 ──────────────────────────────────────────────────────────────────

    def get_current_positions(self) -> list[Position]:
        """取得所有現有持倉，轉換為 Position 物件。"""
        resp  = self._request("GET", f"{self.base_url}/v2/positions")
        raw   = resp.json()
        result = []
        for p in raw:
            qty      = float(p["qty"])
            avg_px   = float(p["avg_entry_price"])
            curr_px  = float(p["current_price"])
            mkt_val  = float(p["market_value"])
            unreal   = float(p["unrealized_pl"])
            cost     = qty * avg_px
            plpc     = unreal / cost if cost > 0 else 0.0
            result.append(Position(
                symbol=p["symbol"],
                qty=qty,
                avg_entry_price=avg_px,
                current_price=curr_px,
                market_value=mkt_val,
                unrealized_pl=unreal,
                unrealized_plpc=plpc,
            ))
        logger.info("現有持倉：%d 檔", len(result))
        return result

    # ── 訂單 ──────────────────────────────────────────────────────────────────

    def submit_market_order(
        self,
        symbol: str,
        qty: float,
        side: str,            # "buy" | "sell"
        time_in_force: str = "day",
    ) -> dict:
        """送出市價單（支援 fractional shares）。"""
        whole_qty = int(math.floor(qty))   # 整股，不用 fractional
        if whole_qty <= 0:
            logger.warning("整股數量為 0，跳過 %s %s", side, symbol)
            return {}
        body = {
            "symbol":        symbol,
            "qty":           str(whole_qty),
            "side":          side,
            "type":          "market",
            "time_in_force": time_in_force,
        }
        resp = self._request("POST", f"{self.base_url}/v2/orders", json=body)
        if resp.status_code in (200, 201):
            order = resp.json()
            logger.info(
                "訂單送出：%s %s × %s  order_id=%s",
                side.upper(), symbol, qty, order.get("id", "?"),
            )
            return order
        else:
            logger.error("訂單失敗：%s %s × %s  status=%d  %s",
                         side, symbol, qty, resp.status_code, resp.text[:200])
            return {}

    def get_order(self, order_id: str) -> dict:
        """查詢單一訂單狀態。"""
        resp = self._request("GET", f"{self.base_url}/v2/orders/{order_id}")
        return resp.json()

    def wait_for_fills(
        self,
        order_ids: list[str],
        timeout_seconds: int = 90,
        poll_interval: int   = 5,
    ) -> dict[str, dict]:
        """
        輪詢訂單直到全部 filled / canceled / expired，或逾時。
        回傳 {order_id: order_dict}。
        """
        results: dict[str, dict] = {}
        pending = set(order_ids)
        elapsed = 0

        while pending and elapsed < timeout_seconds:
            for oid in list(pending):
                order = self.get_order(oid)
                status = order.get("status", "")
                if status in ("filled", "canceled", "expired", "replaced"):
                    results[oid] = order
                    pending.discard(oid)
                    logger.info(
                        "訂單 %s %s（%s × %s @ $%s）",
                        oid[:8], status,
                        order.get("symbol"), order.get("filled_qty"),
                        order.get("filled_avg_price", "?"),
                    )
            if pending:
                time.sleep(poll_interval)
                elapsed += poll_interval

        if pending:
            logger.warning("訂單逾時未成交：%s", [o[:8] for o in pending])
            for oid in pending:
                try:
                    self._request("DELETE", f"{self.base_url}/v2/orders/{oid}")
                    logger.info("已取消逾時訂單：%s", oid[:8])
                except Exception as e:
                    logger.error("取消訂單失敗 %s：%s", oid[:8], e)
                results[oid] = self.get_order(oid)

        return results

    def cancel_all_open_orders(self) -> None:
        """取消所有未成交訂單（清理用）。"""
        self._request("DELETE", f"{self.base_url}/v2/orders")
        logger.info("已送出取消所有未成交訂單指令")

    def get_open_orders(self) -> list[dict]:
        """
        取得所有狀態為 open / pending_new / accepted 的訂單。
        用來在下單前檢查是否已有相同 (symbol, side) 的掛單，避免重複下單。
        """
        resp = self._request(
            "GET",
            f"{self.base_url}/v2/orders",
            params={"status": "open", "limit": 500},
        )
        orders = resp.json()
        logger.info("目前佇列中有 %d 筆掛單", len(orders))
        return orders

    def get_asset(self, symbol: str) -> dict:
        """查詢股票資訊（fractionable、tradable 等）。"""
        resp = self._request("GET", f"{self.base_url}/v2/assets/{symbol}")
        return resp.json()


# ── 執行再平衡（SELL → 等待 → BUY）─────────────────────────────────────────
def execute_rebalance(
    client: AlpacaClient,
    orders: list[RebalanceOrder],
    dry_run: bool = False,
    *,
    account_id: str = "",
    strategy: str = "",
) -> list[str]:
    """
    依序執行再平衡訂單：
    1. 先執行所有 SELL
    2. 等待 SELL 成交（市場開盤中才等待，休市時不等）
    3. 再執行所有 BUY
    - 開盤中：day 訂單，等待成交（timeout 120s）
    - 休市中：opg 訂單（at-open），開盤時自動成交，不等待
    回傳已送出訂單的 order_id 清單（dry_run=True 時回傳空清單）。
    """
    # 結構化事件 log（import 失敗時不影響核心邏輯）
    try:
        import trade_log
    except ImportError:
        trade_log = None  # type: ignore

    if not orders:
        logger.info("無再平衡訂單需要執行")
        return []

    sells = [o for o in orders if o.action == "SELL"]
    buys  = [o for o in orders if o.action == "BUY"]

    if dry_run:
        logger.info("[DRY RUN] 模擬訂單（不實際下單，不寫成交事件）：")
        for o in orders:
            logger.info("  [DRY] %s %s × %.6f（%s, ~$%.2f）",
                        o.action, o.symbol, o.qty, o.reason, o.estimated_value)
        return []

    # ── 跨日對帳：補記上次休市排隊、開盤後才成交的訂單下落 ────────────────────
    if trade_log and account_id:
        try:
            reconcile_outcomes(client, account_id, strategy, trade_log=trade_log)
        except Exception as exc:  # noqa: BLE001（對帳失敗不影響今日下單）
            logger.warning("跨日對帳略過：%s", exc)

    # 判斷市場是否開盤
    try:
        clock = client._request("GET", f"{client.base_url}/v2/clock").json()
        market_open = clock.get("is_open", False)
    except Exception:
        market_open = False

    # fractional shares 只能用 day TIF（Alpaca 限制）
    tif = "day"
    if market_open:
        logger.info("市場開盤中，訂單將即時成交（day）")
    else:
        logger.info("市場休市，送出 day 訂單，將於開盤時（09:30 ET）自動成交")

    order_ids: list[str] = []

    # ── 下單前：抓取現有佇列掛單，建立 {(symbol, side)} 集合 ──────────────────
    try:
        existing_orders = client.get_open_orders()
        # 佇列中視為「佔位」的狀態（只封鎖真正活躍的掛單）：
        # - "partially_filled" 排除：部分成交的舊單不應阻擋今日補足剩餘缺口的新單
        # - "done_for_day" 排除：當日到期未成交的舊單，應重新送出而非跳過
        # - "pending_new"/"accepted" 包含：雖為毫秒級過渡態，仍納入防護以涵蓋快速重跑場景
        _PENDING_STATUSES = {"new", "pending_new", "accepted", "held"}
        pending_keys: set[tuple[str, str]] = {
            (ord_["symbol"], ord_["side"])
            for ord_ in existing_orders
            if ord_.get("status", "") in _PENDING_STATUSES
        }
        if pending_keys:
            logger.info(
                "佇列中已有 %d 個 (symbol, side) 掛單，下單前將自動跳過重複：%s",
                len(pending_keys),
                sorted(pending_keys),
            )
    except Exception as exc:
        logger.warning("無法取得現有掛單（跳過重複檢查）：%s", exc)
        pending_keys = set()

    submitted: list[tuple[str, "RebalanceOrder"]] = []  # (order_id, order) 供事後追蹤下落

    # Phase 1: SELL
    sell_ids = []
    for o in sells:
        key = (o.symbol, "sell")
        if key in pending_keys:
            logger.warning("跳過重複賣單：%s（佇列中已有掛單）", o.symbol)
            continue
        result = client.submit_market_order(o.symbol, o.qty, "sell", time_in_force=tif)
        oid = result.get("id")
        if oid:
            sell_ids.append(oid)
            order_ids.append(oid)
            submitted.append((oid, o))
            pending_keys.add(key)   # 加入已送出集合，防止同批次內重複
            if trade_log and account_id:
                trade_log.record_order_submit(
                    account_id=account_id, strategy=strategy,
                    symbol=o.symbol, action="SELL", qty=o.qty,
                    order_id=oid, reason=o.reason,
                )

    if sell_ids:
        if market_open:
            logger.info("等待 %d 筆賣單成交…", len(sell_ids))
            client.wait_for_fills(sell_ids, timeout_seconds=120)
        else:
            logger.info("%d 筆賣單已送出，等待開盤成交", len(sell_ids))

    # Phase 2: BUY
    buy_ids = []
    for o in buys:
        key = (o.symbol, "buy")
        if key in pending_keys:
            logger.warning("跳過重複買單：%s（佇列中已有掛單）", o.symbol)
            continue
        result = client.submit_market_order(o.symbol, o.qty, "buy", time_in_force=tif)
        oid = result.get("id")
        if oid:
            buy_ids.append(oid)
            order_ids.append(oid)
            submitted.append((oid, o))
            pending_keys.add(key)   # 加入已送出集合，防止同批次內重複
            if trade_log and account_id:
                trade_log.record_order_submit(
                    account_id=account_id, strategy=strategy,
                    symbol=o.symbol, action="BUY", qty=o.qty,
                    order_id=oid, reason=o.reason,
                )

    if buy_ids:
        if market_open:
            logger.info("等待 %d 筆買單成交…", len(buy_ids))
            client.wait_for_fills(buy_ids, timeout_seconds=120)
        else:
            logger.info("%d 筆買單已送出，等待開盤（09:30 ET）成交", len(buy_ids))

    # ── 追蹤訂單下落：逐單查最終狀態，記 ORDER_FILLED / REJECTED / PARTIAL ──────
    if trade_log and account_id:
        _record_outcomes(client, submitted, trade_log, account_id, strategy)

    logger.info("再平衡完成：共送出 %d 筆訂單", len(order_ids))
    return order_ids


def _record_outcomes(client, submitted, trade_log, account_id: str, strategy: str) -> None:
    """送單後逐筆查最終狀態並記事件，補上「交易指令的下落」。

    - filled            → ORDER_FILLED（含成交均價、成交量）
    - rejected/canceled → ORDER_REJECTED
    - 部分成交           → ORDER_FILLED（標 partial）
    - 仍 pending（休市排隊，開盤後才成交）→ 不記終態，留待跨日對帳補上
    """
    for oid, o in submitted:
        try:
            od = client.get_order(oid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("查單 %s 失敗：%s", oid[:8], exc)
            continue
        status = (od.get("status") or "").lower()
        filled_qty = float(od.get("filled_qty") or 0)
        avg = float(od.get("filled_avg_price") or 0)
        if status == "filled" or (filled_qty >= o.qty - 1e-9 and filled_qty > 0):
            trade_log.record_order_fill(
                account_id=account_id, strategy=strategy, symbol=o.symbol,
                action=o.action, qty=filled_qty, order_id=oid,
                filled_avg_price=avg, reason=o.reason)
        elif status in ("rejected", "canceled", "cancelled", "expired") and filled_qty == 0:
            trade_log.record_order_reject(
                account_id=account_id, strategy=strategy, symbol=o.symbol,
                action=o.action, qty=o.qty, reason=o.reason, error=f"status={status}")
        elif filled_qty > 0:
            trade_log.record_order_fill(
                account_id=account_id, strategy=strategy, symbol=o.symbol,
                action=o.action, qty=filled_qty, order_id=oid,
                filled_avg_price=avg, reason=f"{o.reason}(partial)")
        else:
            logger.info("訂單 %s（%s %s）尚未成交（status=%s），待跨日對帳",
                        oid[:8], o.action, o.symbol, status)


def reconcile_outcomes(client, account_id: str, strategy: str = "",
                       *, trade_log=None, lookback: int = 300,
                       stale_days: int = 3) -> int:
    """對帳：補記「已送出但尚無 FILLED/REJECTED」的訂單最終下落。

    解決「休市排隊、開盤後才成交」的單 —— 隔日 run 開始時呼叫，把昨天 pending 的
    訂單查最新狀態並補記事件。超過 stale_days 天仍未結者記 ORDER_STALE 告警。
    回傳處理筆數（補記 + 告警）。
    """
    import datetime as _dt
    if trade_log is None:
        try:
            import trade_log as trade_log  # type: ignore
        except ImportError:
            return 0
    events = trade_log.read_events(account_id=account_id)[-lookback:]
    resolved = {e.get("order_id") for e in events
                if e.get("type") in ("ORDER_FILLED", "ORDER_REJECTED")}
    flagged = {e.get("order_id") for e in events if e.get("type") == "ORDER_STALE"}
    pending = {}
    for e in events:
        oid = e.get("order_id")
        if e.get("type") == "ORDER_SUBMITTED" and oid and oid not in resolved:
            pending[oid] = e   # 後寫覆蓋，保留最新一筆 submit 資訊

    now = _dt.datetime.now(_dt.timezone.utc)
    n = 0
    for oid, e in pending.items():
        try:
            od = client.get_order(oid)
        except Exception:  # noqa: BLE001
            od = {}
        status = (od.get("status") or "").lower()
        fq = float(od.get("filled_qty") or 0)
        avg = float(od.get("filled_avg_price") or 0)
        if status == "filled" or fq > 0:
            trade_log.record_order_fill(
                account_id=account_id, strategy=e.get("strategy", strategy),
                symbol=e.get("symbol", ""), action=e.get("action", ""),
                qty=fq, order_id=oid, filled_avg_price=avg,
                reason=(e.get("reason", "") + ("" if status == "filled" else "(partial)")))
            n += 1
        elif status in ("rejected", "canceled", "cancelled", "expired"):
            trade_log.record_order_reject(
                account_id=account_id, strategy=e.get("strategy", strategy),
                symbol=e.get("symbol", ""), action=e.get("action", ""),
                qty=float(e.get("qty") or 0), reason=e.get("reason", ""),
                error=f"status={status}")
            n += 1
        else:
            # 仍未結：超過 stale_days 天且未告警過 → 記 ORDER_STALE
            try:
                ts = _dt.datetime.fromisoformat((e.get("ts") or "").replace("Z", "+00:00"))
                age = (now - ts).days
            except ValueError:
                age = 0
            if age >= stale_days and oid not in flagged:
                trade_log.record_order_stale(
                    account_id=account_id, strategy=e.get("strategy", strategy),
                    symbol=e.get("symbol", ""), action=e.get("action", ""),
                    order_id=oid, age_days=age)
                logger.warning("訂單 %s（%s %s）已送出 %d 天仍未結 → ORDER_STALE",
                               oid[:8], e.get("action"), e.get("symbol"), age)
                n += 1
    if n:
        logger.info("跨日對帳：處理 %d 筆（補記 + 告警）", n)
    return n


# ── 從環境變數建立 client ─────────────────────────────────────────────────────
def client_from_env() -> AlpacaClient:
    """從環境變數建立 AlpacaClient（適合 GitHub Actions 使用）。"""
    api_key    = os.environ["ALPACA_API_KEY"]
    secret_key = os.environ["ALPACA_SECRET_KEY"]
    base_url   = os.environ.get("ALPACA_BASE_URL", PAPER_URL)
    return AlpacaClient(api_key=api_key, secret_key=secret_key, base_url=base_url)
