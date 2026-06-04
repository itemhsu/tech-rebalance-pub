"""brokers/rest_broker.py — 通用 REST 券商引擎（JSON-driven）。

RestBrokerClient 讀 broker-schema v2 spec（含 request/response/value_maps
對應表），用「查表 + 組請求 + 解析回應」實作 BrokerClient ABC 的 7 個方法。

新增一家純 REST + 永久憑證的券商 = 寫一份 spec JSON，0 行 Python。
不純 REST（OAuth refresh / 本地 gateway）的券商仍用 integration.client_class
指向自訂子類，本引擎不處理。

對應計劃書：docs/json-broker-plan.html（Phase A）。
"""
from __future__ import annotations

import time
from datetime import date as _date
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from .base import (
    AccountBalance, BrokerAuthError, BrokerClient,
    BrokerError, BrokerRateLimitError, OrderResult, Position,
)

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0
_TERMINAL_STATUSES = {"filled", "cancelled", "canceled", "rejected", "expired"}


# ════════════════════════════════════════════════════════════════════════
#  純函式 helpers（無狀態，方便單元測試）
# ════════════════════════════════════════════════════════════════════════

def dig(data: Any, path: str) -> Any:
    """依點號路徑逐層取值；任一層不存在回 None（不丟例外）。

    範例：dig({"order": {"id": 7}}, "order.id") == 7
         dig({"a": 1}, "a.b.c") is None
    空 path 回 data 本身。
    """
    if not path:
        return data
    cur = data
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def normalize_list(value: Any) -> List[Any]:
    """把「單筆 dict / 多筆 list / None」正規化成 list。

    許多券商（如 Tradier）單筆回 dict、多筆回 list、無資料回 None 或 "null"。
    """
    if value is None or value == "null":
        return []
    if isinstance(value, list):
        return value
    return [value]


# ════════════════════════════════════════════════════════════════════════
#  通用引擎
# ════════════════════════════════════════════════════════════════════════

class RestBrokerClient(BrokerClient):
    """spec-driven 的通用 REST 券商 client。"""

    def __init__(self, spec: dict, env: Dict[str, str], environment: str = "paper") -> None:
        super().__init__(spec, env, environment)

        self.api_key = env.get("API_KEY", "")
        self.api_secret = env.get("API_SECRET", "")
        self.account_id = env.get("ACCOUNT_ID", "")
        if not self.api_key:
            raise BrokerAuthError(f"{self.broker_id} 需要 API_KEY")

        self.base_url = self.env_config["base_url"].rstrip("/")
        md = spec.get("market_data", {}) or {}
        self.data_url = (md.get("data_url") or self.base_url).rstrip("/")
        self.md = md

        self.endpoints = spec.get("endpoints", {}) or {}
        self.req_spec = spec.get("request", {}) or {}
        self.resp_spec = spec.get("response", {}) or {}
        self.value_maps = spec.get("value_maps", {}) or {}

        # headers（用 spec.auth.header_template，支援 {api_key}/{api_secret}）
        tpl = (spec.get("auth", {}) or {}).get("header_template", {}) or {}
        self._headers: Dict[str, str] = {}
        for k, v in tpl.items():
            self._headers[k] = v.format(api_key=self.api_key, api_secret=self.api_secret)
        self._headers.setdefault("Accept", "application/json")

    # ── endpoint 模板套用 ────────────────────────────────────────────────
    def _ep(self, name: str, default: str = "", **kw: str) -> str:
        tpl = self.endpoints.get(name, default)
        kw.setdefault("account_id", self.account_id)
        return tpl.format(**kw)

    def _map_value(self, category: str, value: str) -> str:
        """value_maps 翻譯（無對應則原樣回）。"""
        return self.value_maps.get(category, {}).get(value, value)

    # ── HTTP ─────────────────────────────────────────────────────────────
    def _request(
        self, method: str, url: str, *, params: Optional[dict] = None,
        json_body: Optional[dict] = None, data_body: Optional[dict] = None,
        timeout: int = 30,
    ) -> requests.Response:
        last_exc = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.request(
                    method, url, headers=self._headers,
                    params=params, json=json_body, data=data_body, timeout=timeout,
                )
            except requests.RequestException as e:
                last_exc = e
                time.sleep(_BASE_BACKOFF * (2 ** attempt))
                continue
            if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                time.sleep(_BASE_BACKOFF * (2 ** attempt))
                continue
            return resp
        if last_exc:
            raise BrokerError(f"{method} {url} failed after retries: {last_exc}")
        raise BrokerError(f"{method} {url} failed after retries")

    def _check_resp(self, resp: requests.Response, action: str) -> dict:
        if resp.status_code == 429:
            raise BrokerRateLimitError(f"{action} rate-limited")
        if resp.status_code in (401, 403):
            # 不洩 token：只截前 120 字回應
            raise BrokerAuthError(f"{action}: HTTP {resp.status_code} {resp.text[:120]}")
        if not resp.ok:
            raise BrokerError(f"{action}: HTTP {resp.status_code} {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError:
            return {}

    # ════════════════════════════════════════════════════════════════════
    #  BrokerClient 介面
    # ════════════════════════════════════════════════════════════════════
    def is_trading_day(self, target_date: Optional[_date] = None) -> bool:
        target = target_date or _date.today()
        cal_ep = self.md.get("calendar_endpoint")
        if cal_ep:
            resp = self._request("GET", f"{self.base_url}{cal_ep}",
                                 params={"start": target.isoformat(), "end": target.isoformat()})
            data = self._check_resp(resp, "is_trading_day")
            # Alpaca: list；其他券商可能巢狀，先支援 list 形式
            if isinstance(data, list):
                return any(e.get("date") == target.isoformat() for e in data)
            # 巢狀 calendar.days.day[]（如 Tradier）
            days = normalize_list(dig(data, "calendar.days.day"))
            for d in days:
                if d.get("date") == target.isoformat():
                    return d.get("status") == "open"
            return False
        # 退而用 clock
        clk_ep = self.md.get("clock_endpoint")
        if clk_ep:
            resp = self._request("GET", f"{self.base_url}{clk_ep}")
            data = self._check_resp(resp, "is_trading_day")
            state = data.get("state") or dig(data, "clock.state")
            return state in ("open", "premarket", "postmarket")
        raise BrokerError(f"{self.broker_id} spec 未定義 calendar/clock endpoint")

    def get_account_balance(self) -> AccountBalance:
        url = f"{self.base_url}{self._ep('balances', self.endpoints.get('account', ''))}"
        resp = self._request("GET", url)
        data = self._check_resp(resp, "get_account_balance")
        bmap = self.resp_spec.get("balance", {}) or {}
        nav = dig(data, bmap.get("nav", "")) if bmap.get("nav") else (
            data.get("portfolio_value") or data.get("equity"))
        cash = dig(data, bmap.get("cash", "")) if bmap.get("cash") else data.get("cash")
        bp = dig(data, bmap.get("buying_power", "")) if bmap.get("buying_power") else data.get("buying_power")
        return AccountBalance(
            nav=float(nav or 0.0),
            cash=float(cash or 0.0),
            buying_power=float(bp or 0.0),
        )

    def get_positions(self) -> List[Position]:
        url = f"{self.base_url}{self._ep('positions')}"
        resp = self._request("GET", url)
        data = self._check_resp(resp, "get_positions")
        path = self.resp_spec.get("positions_path", "")
        raw = normalize_list(dig(data, path) if path else data)
        fmap = self.resp_spec.get("position_fields", {}) or {}

        def g(p: dict, generic: str, default_key: str) -> Any:
            return p.get(fmap.get(generic, default_key))

        out: List[Position] = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            qty = float(g(p, "qty", "qty") or 0.0)
            cost = float(g(p, "avg_entry_price", "avg_entry_price") or 0.0)
            cur = float(g(p, "current_price", "current_price") or 0.0)
            mv = g(p, "market_value", "market_value")
            out.append(Position(
                symbol=g(p, "symbol", "symbol") or "",
                qty=qty, avg_entry_price=cost, current_price=cur,
                market_value=float(mv) if mv is not None else 0.0,
                unrealized_pl=float(g(p, "unrealized_pl", "unrealized_pl") or 0.0),
                unrealized_plpc=float(g(p, "unrealized_plpc", "unrealized_plpc") or 0.0),
            ))
        return out

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        if not symbols:
            return {}
        quotes_ep = self.md.get("quotes_endpoint")
        if quotes_ep:
            url = f"{self.data_url}{quotes_ep}"
            resp = self._request("GET", url, params={"symbols": ",".join(symbols)})
            data = self._check_resp(resp, "get_latest_prices")
            sym_f = self.resp_spec.get("quote_symbol_field", "symbol")
            px_f = self.resp_spec.get("quote_price_field", "last")
            quotes = normalize_list(dig(data, self.resp_spec.get("quote_list_path", "")))
            out: Dict[str, float] = {}
            for q in quotes:
                sym = q.get(sym_f)
                px = q.get(px_f)
                if sym and px is not None:
                    out[sym] = float(px)
            return out
        # Alpaca bars 形式
        bars_ep = self.md.get("latest_bars_endpoint")
        if bars_ep:
            url = f"{self.data_url}{bars_ep}"
            resp = self._request("GET", url, params={"symbols": ",".join(symbols), "feed": "iex"})
            data = self._check_resp(resp, "get_latest_prices")
            out = {}
            for sym, bar in (data.get("bars") or {}).items():
                price = bar.get("c") or bar.get("close")
                if price is not None:
                    out[sym] = float(price)
            return out
        raise BrokerError(f"{self.broker_id} spec 未定義 quotes/bars endpoint")

    def place_order(
        self, symbol: str, qty: float, side: str,
        order_type: str = "market", time_in_force: str = "day",
    ) -> OrderResult:
        if qty != int(qty):
            self.check_capability("fractional_shares", True)
        self.check_capability("order_types", order_type)
        self.check_capability("time_in_force", time_in_force)

        # 通用值 → 券商值
        generic = {
            "symbol": symbol,
            "qty": str(int(qty)) if qty == int(qty) else str(qty),
            "side": self._map_value("side", side),
            "order_type": self._map_value("order_type", order_type),
            "time_in_force": self._map_value("time_in_force", time_in_force),
        }
        fmap = self.req_spec.get("field_map") or {
            "symbol": "symbol", "qty": "qty", "side": "side",
            "order_type": "type", "time_in_force": "time_in_force",
        }
        body: Dict[str, Any] = {}
        for gkey, gval in generic.items():
            body[fmap.get(gkey, gkey)] = gval
        # 固定常數
        for k, v in (self.req_spec.get("constants") or {}).items():
            body[k] = v

        url = f"{self.base_url}{self._ep('orders')}"
        encoding = self.req_spec.get("encoding", "json")
        if encoding == "form":
            resp = self._request("POST", url, data_body=body)
        else:
            resp = self._request("POST", url, json_body=body)
        data = self._check_resp(resp, f"place_order {side} {symbol}")

        oid_path = self.resp_spec.get("order_id_path", "id")
        st_path = self.resp_spec.get("order_status_path", "status")
        return OrderResult(
            order_id=str(dig(data, oid_path) or ""),
            symbol=symbol, side=side, qty=qty,
            status=str(dig(data, st_path) or "new"),
            raw=data,
        )

    def cancel_all_open_orders(self) -> int:
        # 列 open orders → 逐筆 DELETE（通用做法，相容帳號路徑券商）
        list_url = f"{self.base_url}{self._ep('orders')}"
        resp = self._request("GET", list_url, params={"status": "open"})
        if not resp.ok:
            return 0
        try:
            data = resp.json()
        except ValueError:
            return 0
        orders = data if isinstance(data, list) else normalize_list(
            dig(data, self.resp_spec.get("order_list_path", "orders.order")))
        oid_field = self.resp_spec.get("order_id_field", "id")
        cancelled = 0
        for o in orders:
            if not isinstance(o, dict):
                continue
            oid = o.get(oid_field) or o.get("id")
            if not oid:
                continue
            del_url = f"{self.base_url}{self._ep('order_by_id', order_id=str(oid))}"
            r = self._request("DELETE", del_url)
            if r.ok:
                cancelled += 1
        return cancelled

    def wait_for_fills(self, order_ids: List[str], timeout_seconds: int = 120) -> None:
        if not order_ids:
            return
        st_path = self.resp_spec.get("order_status_path", "status")
        deadline = time.time() + timeout_seconds
        pending = set(order_ids)
        while pending and time.time() < deadline:
            for oid in list(pending):
                url = f"{self.base_url}{self._ep('order_by_id', order_id=str(oid))}"
                resp = self._request("GET", url)
                if not resp.ok:
                    continue
                try:
                    data = resp.json()
                except ValueError:
                    continue
                status = dig(data, st_path)
                if status in _TERMINAL_STATUSES:
                    pending.discard(oid)
            if pending:
                time.sleep(2.0)

    # ── 向下相容層（與 AlpacaClient 同介面，給 trader/runner 用）──────────
    def get_order(self, order_id: str) -> dict:
        """查單一訂單原始 dict（給 trader 記錄成交/拒單/未結 outcome 用）。

        回傳券商原始 JSON（含 status / filled_qty / filled_avg_price 等欄位）。
        """
        url = f"{self.base_url}{self._ep('order_by_id', order_id=str(order_id))}"
        return self._check_resp(self._request("GET", url), "get_order")

    def get_account_nav(self) -> tuple:
        b = self.get_account_balance()
        return b.nav, b.cash

    def get_current_positions(self) -> list:
        from portfolio import Position as _PP
        return [_PP(symbol=p.symbol, qty=p.qty, avg_entry_price=p.avg_entry_price,
                    current_price=p.current_price, market_value=p.market_value,
                    unrealized_pl=p.unrealized_pl, unrealized_plpc=p.unrealized_plpc)
                for p in self.get_positions()]

    def submit_market_order(self, symbol: str, qty, side: str, time_in_force: str = "day") -> dict:
        r = self.place_order(symbol, float(qty), side,
                             order_type="market", time_in_force=time_in_force)
        return r.raw or {"id": r.order_id, "status": r.status}

    def get_open_orders(self) -> list:
        url = f"{self.base_url}{self._ep('orders')}"
        resp = self._request("GET", url, params={"status": "open"})
        data = self._check_resp(resp, "get_open_orders")
        if isinstance(data, list):
            return data
        return normalize_list(dig(data, self.resp_spec.get("order_list_path", "orders.order")))
