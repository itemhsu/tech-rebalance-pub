"""永豐金證券 (SinoPac) client — 實作 BrokerClient ABC，走 Shioaji SDK。

對應 brokers/sinopac.json spec。**Phase 2：只做模擬（simulation=True）**，
不呼叫 activate_ca、不下實單、不需 CA 憑證。

設計重點
--------
- **延遲連線**：建構時不登入；第一次用到才 `_ensure_api()`（lazy import shioaji +
  `Shioaji(simulation=...)` + `login`）。測試可注入假的 `api`（與 `sj`）完全免網路。
- **零股下單**：spec.capabilities.order_mode == "odd_lot" → 以「股」為單位、order_lot=IntradayOdd。
- **代號正規化**：內部統一用 yfinance 格式 "2330.TW"；Shioaji 用純代號 "2330"。

⚠️ 真實 API 對拍待辦：本檔的 Shioaji 物件/欄位映射在「有模擬帳號憑證」後須對拍驗證
   （Shioaji 版本間 constant/欄位略有差異）。單元測試以注入假 api 驗證映射邏輯。
"""
from __future__ import annotations

import time
from datetime import date as _date
from typing import Any, Dict, List, Optional

from .base import (
    AccountBalance, BrokerAuthError, BrokerClient, BrokerError,
    OrderResult, Position,
)


def _to_code(symbol: str) -> str:
    """內部符號 → Shioaji 代號：'2330.TW' → '2330'、'^TWII' 原樣。"""
    s = (symbol or "").upper()
    if s.endswith(".TW") or s.endswith(".TWO"):
        return s.split(".")[0]
    return s


def _to_symbol(code: str) -> str:
    """Shioaji 代號 → 內部符號：'2330' → '2330.TW'（已含後綴則原樣）。"""
    c = (code or "").upper()
    if "." in c or c.startswith("^"):
        return c
    return f"{c}.TW"


class SinoPacClient(BrokerClient):
    """永豐 Shioaji client（模擬）。"""

    def __init__(self, spec: dict, env: Dict[str, str], environment: str = "paper",
                 api: Any = None, sj: Any = None) -> None:
        super().__init__(spec, env, environment)
        self.api_key = env.get("API_KEY", "")
        self.api_secret = env.get("API_SECRET", "")
        self._simulation = bool(self.env_config.get("simulation", True))
        # 測試可直接注入 api / sj（免網路、免 shioaji 套件）
        self._api = api
        self._sj = sj
        self._lot_size = int(self.capabilities.get("lot_size", 1000))
        self._odd_lot = (self.capabilities.get("order_mode") == "odd_lot")

    # ── 延遲連線 ──────────────────────────────────────────────────────────
    def _ensure_api(self):
        if self._api is not None:
            return self._api
        if not self.api_key or not self.api_secret:
            raise BrokerAuthError("SinoPacClient 需要 API_KEY 與 API_SECRET")
        try:
            import shioaji as sj  # noqa: 延遲載入，未用到永豐時不需安裝
        except ImportError as e:   # pragma: no cover - 需實機才會走到
            raise BrokerError(
                "未安裝 shioaji 套件（pip install shioaji）") from e
        self._sj = sj
        api = sj.Shioaji(simulation=self._simulation)
        api.login(api_key=self.api_key, secret_key=self.api_secret)
        self._api = api
        return api

    def _const(self, *path, fallback):
        """取 shioaji constant（self._sj.constant.X.Y）；無 sj 時回 fallback（測試用）。"""
        obj = self._sj
        if obj is None:
            return fallback
        for p in path:
            obj = getattr(obj, p, None)
            if obj is None:
                return fallback
        return obj

    def _contract(self, symbol: str):
        api = self._ensure_api()
        return api.Contracts.Stocks[_to_code(symbol)]

    # ── ABC 實作 ─────────────────────────────────────────────────────────
    def is_trading_day(self, target_date: Optional[_date] = None) -> bool:
        """週一~五視為交易日。

        ⚠️ 尚未接 TWSE 假日曆（颱風假/補班/國定假）；模擬不下實單，影響有限。
        真實交易前須補上可靠交易日來源（Phase 4）。
        """
        d = target_date or _date.today()
        return d.weekday() < 5

    def get_positions(self) -> List[Position]:
        api = self._ensure_api()
        raw = api.list_positions(api.stock_account)
        out: List[Position] = []
        for p in (raw or []):
            code = getattr(p, "code", None) or (p.get("code") if isinstance(p, dict) else "")
            qty = float(getattr(p, "quantity", None) if not isinstance(p, dict) else p.get("quantity", 0) or 0)
            avg = float(getattr(p, "price", None) if not isinstance(p, dict) else p.get("price", 0) or 0)
            last = float(getattr(p, "last_price", None) if not isinstance(p, dict) else p.get("last_price", 0) or 0)
            pnl = float(getattr(p, "pnl", None) if not isinstance(p, dict) else p.get("pnl", 0) or 0)
            out.append(Position(
                symbol=_to_symbol(code), qty=qty, avg_entry_price=avg,
                current_price=last or avg, unrealized_pl=pnl,
            ))
        return out

    def get_account_balance(self) -> AccountBalance:
        api = self._ensure_api()
        bal = api.account_balance()
        # 首次對拍 debug：印原始回應（workflow log 可見），確認欄位名 + 是否真為 0。
        try:
            import sys as _sys
            print(f"[sinopac] account_balance raw: {bal!r}", file=_sys.stderr)
        except Exception:   # noqa: BLE001
            pass

        def _num(obj, *names) -> float:
            for n in names:
                v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
            return 0.0

        # acc_balance 為 Shioaji 主要欄位；其餘為不同版本/型態的後援
        cash = _num(bal, "acc_balance", "available_balance", "cash", "settled_cash")
        pos_value = sum(p.market_value for p in self.get_positions())
        nav = cash + pos_value
        return AccountBalance(nav=nav, cash=cash, buying_power=cash, currency="TWD")

    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        api = self._ensure_api()
        contracts = [self._contract(s) for s in symbols]
        snaps = api.snapshots(contracts) if contracts else []
        out: Dict[str, float] = {}
        for snap in (snaps or []):
            code = getattr(snap, "code", None) or (snap.get("code") if isinstance(snap, dict) else "")
            close = getattr(snap, "close", None) if not isinstance(snap, dict) else snap.get("close")
            if code and close is not None:
                out[_to_symbol(code)] = float(close)
        return out

    def place_order(self, symbol: str, qty: float, side: str,
                    order_type: str = "market", time_in_force: str = "day") -> OrderResult:
        api = self._ensure_api()
        shares = int(qty)   # 零股以「股」計，最小 1 股
        if shares <= 0:
            raise BrokerError(f"下單股數需 > 0（symbol={symbol}, qty={qty}）")
        contract = self._contract(symbol)

        action = self._const("constant", "Action", "Buy" if side == "buy" else "Sell",
                             fallback=("Buy" if side == "buy" else "Sell"))
        price_type = self._const("constant", "StockPriceType",
                                 "MKT" if order_type == "market" else "LMT",
                                 fallback=("MKT" if order_type == "market" else "LMT"))
        order_lot = self._const("constant", "StockOrderLot",
                                "IntradayOdd" if self._odd_lot else "Common",
                                fallback=("IntradayOdd" if self._odd_lot else "Common"))
        rod = self._const("constant", "OrderType", "ROD", fallback="ROD")

        order = api.Order(
            price=0, quantity=shares, action=action,
            price_type=price_type, order_type=rod, order_lot=order_lot,
        )
        trade = api.place_order(contract, order)
        oid = ""
        status = "new"
        msg = ""
        o = getattr(trade, "order", None)
        if o is not None:
            oid = str(getattr(o, "id", "") or "")
        st = getattr(trade, "status", None)
        if st is not None:
            status = str(getattr(st, "status", status) or status)
            msg = str(getattr(st, "msg", "") or "")
        # 模擬委託成功＝狀態 PendingSubmit/Submitted（官方測試準則，與有無資金無關）
        ok = status in ("PendingSubmit", "PreSubmitted", "Submitted", "Filled",
                        "Filling", "PartFilled")
        try:
            import sys as _sys
            print(f"[sinopac] place_order {symbol} x{shares} {side} → "
                  f"status={status} msg={msg!r} ok={ok}", file=_sys.stderr)
        except Exception:   # noqa: BLE001
            pass
        return OrderResult(order_id=oid, symbol=symbol, side=side, qty=shares,
                           status=status, raw={"status": status, "msg": msg, "ok": ok})

    def cancel_all_open_orders(self) -> int:
        api = self._ensure_api()
        api.update_status(api.stock_account)
        n = 0
        for trade in (api.list_trades() or []):
            st = getattr(trade, "status", None)
            s = str(getattr(st, "status", "") or "").lower() if st is not None else ""
            if s in ("", "submitted", "pendingsubmit", "presubmitted", "partfilled"):
                try:
                    api.cancel_order(trade)
                    n += 1
                except Exception:   # noqa: BLE001  取消失敗不擋其他
                    pass
        return n

    def wait_for_fills(self, order_ids: List[str], timeout_seconds: int = 120) -> None:
        api = self._ensure_api()
        want = {str(x) for x in (order_ids or [])}
        if not want:
            return
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            api.update_status(api.stock_account)
            filled = set()
            for trade in (api.list_trades() or []):
                o = getattr(trade, "order", None)
                st = getattr(trade, "status", None)
                oid = str(getattr(o, "id", "") or "") if o is not None else ""
                s = str(getattr(st, "status", "") or "").lower() if st is not None else ""
                if oid in want and s in ("filled", "filling"):
                    filled.add(oid)
            if want.issubset(filled):
                return
            time.sleep(2)
