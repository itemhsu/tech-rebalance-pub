"""Alpaca 卷商 client — 實作 BrokerClient ABC。

對應 brokers/alpaca.json spec。

⚠️  [DEPRECATED — Phase D, 2026-06-02]
   Alpaca 已於 Phase B 改走通用 brokers/rest_broker.py（JSON-driven）。
   本檔僅保留為：
     (1) rollback 網 — alpaca.json 加回 "client_class" 即退回此 client
     (2) parity 測試的對拍基準（tests/brokers/test_alpaca_parity.py）
   待「4 個 Alpaca 帳戶 production 首輪走 RestBrokerClient 確認無異常」後刪除。
"""
from __future__ import annotations

import time
from datetime import date as _date
from typing import Any, Dict, List, Optional

import requests

from .base import (
    AccountBalance, BrokerAuthError, BrokerCapabilityError, BrokerClient,
    BrokerError, BrokerRateLimitError, OrderResult, Position,
)


# 簡單的指數退避 retry 設定
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0


class AlpacaClient(BrokerClient):
    """Alpaca REST API client。

    建構子已由 BrokerClient.__init__ 處理 spec / env / environment 驗證。
    """

    def __init__(self, spec: dict, env: Dict[str, str], environment: str = "paper") -> None:
        super().__init__(spec, env, environment)

        # 從 env 拿 API key / secret
        self.api_key = env.get("API_KEY", "")
        self.api_secret = env.get("API_SECRET", "")
        if not self.api_key or not self.api_secret:
            raise BrokerAuthError("AlpacaClient 需要 API_KEY 與 API_SECRET")

        # base URLs
        self.base_url = self.env_config["base_url"].rstrip("/")
        md = spec.get("market_data", {}) or {}
        self.data_url = md.get("data_url", "https://data.alpaca.markets").rstrip("/")
        self.calendar_endpoint = md.get("calendar_endpoint", "/v2/calendar")
        self.clock_endpoint = md.get("clock_endpoint", "/v2/clock")
        self.latest_bars_endpoint = md.get("latest_bars_endpoint", "/v2/stocks/bars/latest")

        self.endpoints = spec.get("endpoints", {}) or {}

        # 組 headers（用 spec.auth.header_template）
        tpl = spec.get("auth", {}).get("header_template", {}) or {}
        self._headers = {}
        for k, v in tpl.items():
            self._headers[k] = v.format(api_key=self.api_key, api_secret=self.api_secret)
        self._headers.setdefault("Accept", "application/json")
        self._headers.setdefault("Content-Type", "application/json")

    # ────────────────────────────────────────────────────────────────────
    # 內部：HTTP 請求 + retry
    # ────────────────────────────────────────────────────────────────────
    def _request(
        self, method: str, url: str, *, params: Optional[dict] = None,
        json_body: Optional[dict] = None, timeout: int = 30,
    ) -> requests.Response:
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.request(
                    method, url, headers=self._headers,
                    params=params, json=json_body, timeout=timeout,
                )
            except requests.RequestException as e:
                last_exc = e
                time.sleep(_BASE_BACKOFF * (2 ** attempt))
                continue

            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                time.sleep(_BASE_BACKOFF * (2 ** attempt))
                continue
            return resp

        # 全部 retry 都失敗
        if last_exc:
            raise BrokerError(f"{method} {url} failed after retries: {last_exc}")
        raise BrokerError(f"{method} {url} failed after retries")

    def _check_resp(self, resp: requests.Response, action: str) -> dict:
        """檢查回應，回 JSON 或 raise（不洩 secret）。"""
        if resp.status_code == 429:
            raise BrokerRateLimitError(f"{action} rate-limited")
        if resp.status_code in (401, 403):
            raise BrokerAuthError(f"{action}: HTTP {resp.status_code} {resp.text[:120]}")
        if not resp.ok:
            raise BrokerError(f"{action}: HTTP {resp.status_code} {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError:
            return {}

    # ────────────────────────────────────────────────────────────────────
    # BrokerClient 介面實作
    # ────────────────────────────────────────────────────────────────────
    def is_trading_day(self, target_date: Optional[_date] = None) -> bool:
        target = target_date or _date.today()
        resp = self._request("GET", f"{self.base_url}{self.calendar_endpoint}",
                             params={"start": target.isoformat(), "end": target.isoformat()})
        data = self._check_resp(resp, "is_trading_day")
        # /v2/calendar 回傳 list（可能空）
        return bool(data) and any(entry.get("date") == target.isoformat() for entry in data)

    def get_account_balance(self) -> AccountBalance:
        url = f"{self.base_url}{self.endpoints.get('account', '/v2/account')}"
        resp = self._request("GET", url)
        data = self._check_resp(resp, "get_account_balance")
        return AccountBalance(
            nav=float(data.get("portfolio_value") or data.get("equity") or 0.0),
            cash=float(data.get("cash") or 0.0),
            buying_power=float(data.get("buying_power") or 0.0),
            currency=data.get("currency", "USD"),
        )

    def get_positions(self) -> List[Position]:
        url = f"{self.base_url}{self.endpoints.get('positions', '/v2/positions')}"
        resp = self._request("GET", url)
        data = self._check_resp(resp, "get_positions")
        out: List[Position] = []
        for p in data or []:
            out.append(Position(
                symbol=p.get("symbol", ""),
                qty=float(p.get("qty") or 0.0),
                avg_entry_price=float(p.get("avg_entry_price") or 0.0),
                current_price=float(p.get("current_price") or 0.0),
                market_value=float(p.get("market_value") or 0.0),
                unrealized_pl=float(p.get("unrealized_pl") or 0.0),
                unrealized_plpc=float(p.get("unrealized_plpc") or 0.0),
            ))
        return out

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        if not symbols:
            return {}
        url = f"{self.data_url}{self.latest_bars_endpoint}"
        resp = self._request("GET", url, params={"symbols": ",".join(symbols), "feed": "iex"})
        data = self._check_resp(resp, "get_latest_prices")
        bars = data.get("bars") or {}
        out: Dict[str, float] = {}
        for sym, bar in bars.items():
            price = bar.get("c") or bar.get("close")
            if price is not None:
                out[sym] = float(price)
        return out

    def place_order(
        self, symbol: str, qty: float, side: str,
        order_type: str = "market", time_in_force: str = "day",
    ) -> OrderResult:
        # capability 檢查
        is_fractional = (qty != int(qty))
        if is_fractional:
            self.check_capability("fractional_shares", True)
        self.check_capability("order_types", order_type)
        self.check_capability("time_in_force", time_in_force)

        url = f"{self.base_url}{self.endpoints.get('orders', '/v2/orders')}"
        body = {
            "symbol":        symbol,
            "qty":           str(qty),
            "side":          side,
            "type":          order_type,
            "time_in_force": time_in_force,
        }
        resp = self._request("POST", url, json_body=body)
        data = self._check_resp(resp, f"place_order {side} {symbol}")
        return OrderResult(
            order_id=data.get("id", ""),
            symbol=symbol,
            side=side,
            qty=qty,
            status=data.get("status", "new"),
            filled_qty=float(data.get("filled_qty") or 0.0),
            filled_avg_price=float(data.get("filled_avg_price") or 0.0),
            raw=data,
        )

    def cancel_all_open_orders(self) -> int:
        url = f"{self.base_url}{self.endpoints.get('cancel_all', '/v2/orders')}"
        resp = self._request("DELETE", url)
        # /v2/orders DELETE 回 207 Multi-Status + list
        if resp.status_code in (200, 207, 204):
            try:
                data = resp.json()
                return len(data) if isinstance(data, list) else 0
            except ValueError:
                return 0
        raise BrokerError(f"cancel_all_open_orders: HTTP {resp.status_code} {resp.text[:200]}")

    def wait_for_fills(self, order_ids: List[str], timeout_seconds: int = 120) -> None:
        if not order_ids:
            return
        endpoint = self.endpoints.get("order_by_id", "/v2/orders/{order_id}")
        deadline = time.time() + timeout_seconds
        pending = set(order_ids)
        while pending and time.time() < deadline:
            for oid in list(pending):
                url = f"{self.base_url}{endpoint.format(order_id=oid)}"
                resp = self._request("GET", url)
                if not resp.ok:
                    continue
                try:
                    data = resp.json()
                except ValueError:
                    continue
                if data.get("status") in ("filled", "cancelled", "rejected", "expired"):
                    pending.discard(oid)
            if pending:
                time.sleep(2.0)

    # ─────────────────────────────────────────────────────────────────────
    #  向下相容層
    #  讓既有 main.py + trader.execute_rebalance 把 self 當舊 AlpacaClient 用
    # ─────────────────────────────────────────────────────────────────────

    def get_account_nav(self) -> tuple:
        """[compat] 回傳 (nav, cash) tuple，給舊 main.py 用。"""
        b = self.get_account_balance()
        return b.nav, b.cash

    def get_current_positions(self) -> list:
        """[compat] 回傳 portfolio.Position list（轉換 brokers.base.Position）。"""
        from portfolio import Position as _PortfolioPosition
        out = []
        for p in self.get_positions():
            out.append(_PortfolioPosition(
                symbol=p.symbol, qty=p.qty,
                avg_entry_price=p.avg_entry_price,
                current_price=p.current_price,
                market_value=p.market_value,
                unrealized_pl=p.unrealized_pl,
                unrealized_plpc=p.unrealized_plpc,
            ))
        return out

    def submit_market_order(self, symbol: str, qty, side: str, time_in_force: str = "day") -> dict:
        """[compat] 給 trader.execute_rebalance 用，回傳 dict 含 'id'。"""
        r = self.place_order(symbol, float(qty), side,
                             order_type="market", time_in_force=time_in_force)
        return r.raw or {"id": r.order_id, "status": r.status}

    def get_open_orders(self) -> list:
        """[compat] 回傳 list of dict (status 含 new/pending_new/accepted/...)。"""
        url = f"{self.base_url}{self.endpoints.get('orders', '/v2/orders')}"
        resp = self._request("GET", url, params={"status": "open", "limit": 500})
        data = self._check_resp(resp, "get_open_orders")
        return data if isinstance(data, list) else []

    def get_cash_flows(self, since: str) -> list:
        """外部現金流（入金/出金）：Alpaca Account Activities（CSD/CSW/JNLC）。

        since: ISO 日期 'YYYY-MM-DD'。回 [{date, type: deposit|withdrawal, amount(正數)}]。
        """
        url = f"{self.base_url}/v2/account/activities"
        resp = self._request("GET", url,
                             params={"activity_types": "CSD,CSW,JNLC", "after": since})
        acts = resp.json() or []
        out = []
        for a in acts:
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
