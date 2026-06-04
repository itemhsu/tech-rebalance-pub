"""BrokerClient ABC + 共用 dataclasses。

所有卷商實作必須繼承 BrokerClient 並實作 7 個 abstract methods。
外部呼叫者（main.py / portfolio.py）只看這個介面。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


# ════════════════════════════════════════════════════════════════════════════
#  共用 dataclasses
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class AccountBalance:
    """帳戶餘額快照。"""
    nav: float                        # Net Asset Value
    cash: float                       # 可用現金
    buying_power: float = 0.0         # 購買力（含融資）
    currency: str = "USD"

    def __repr__(self) -> str:
        # 不洩露任何潛在的 secret 內容
        return (f"AccountBalance(nav={self.nav:.2f}, cash={self.cash:.2f}, "
                f"buying_power={self.buying_power:.2f}, currency={self.currency!r})")


@dataclass
class Position:
    """單一持倉。"""
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float = 0.0         # 若 0 則由 qty × current_price 自動算
    unrealized_pl: float = 0.0
    unrealized_plpc: float = 0.0

    def __post_init__(self):
        # 若呼叫者沒提供 market_value，自動計算
        if self.market_value == 0.0 and self.qty and self.current_price:
            self.market_value = self.qty * self.current_price


@dataclass
class OrderResult:
    """送單後的結果。"""
    order_id: str
    symbol: str
    side: str                         # "buy" | "sell"
    qty: float
    status: str = "new"               # "new" | "filled" | "partial" | "rejected" | "cancelled"
    filled_qty: float = 0.0
    filled_avg_price: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


# ════════════════════════════════════════════════════════════════════════════
#  錯誤類別
# ════════════════════════════════════════════════════════════════════════════

class BrokerError(Exception):
    """所有 broker 相關錯誤的基底。"""
    pass


class BrokerAuthError(BrokerError):
    """認證失敗（API key 錯、token 過期、CA 憑證問題等）。"""
    pass


class BrokerCapabilityError(BrokerError):
    """卷商不支援的功能（如 fractional shares）。"""
    pass


class BrokerRateLimitError(BrokerError):
    """超過 rate limit。"""
    pass


# ════════════════════════════════════════════════════════════════════════════
#  BrokerClient ABC
# ════════════════════════════════════════════════════════════════════════════

class BrokerClient(ABC):
    """所有卷商必須實作的最小介面。

    建構子接收：
      spec : 從 brokers/{id}.json 載入的 dict
      env  : 環境變數 dict（含已 resolve 的 API key/secret/token 等）
      environment : "paper" | "live" | "sandbox" 等，必須是 spec.environments 的 key
    """

    def __init__(self, spec: dict, env: Dict[str, str], environment: str = "paper") -> None:
        self.spec = spec
        self.env = env
        self.environment = environment
        # 校驗 environment 存在於 spec
        envs = spec.get("environments", {})
        if environment not in envs:
            raise ValueError(
                f"environment {environment!r} not in spec.environments; "
                f"available: {sorted(envs.keys())}"
            )
        self.env_config = envs[environment]
        self.capabilities = spec.get("capabilities", {})
        self.broker_id = spec.get("id", "unknown")

    # ── Abstract methods（每家必須實作）─────────────────────────────────

    @abstractmethod
    def is_trading_day(self, target_date: Optional[date] = None) -> bool:
        """今日（或指定日期）是否為交易日。"""

    @abstractmethod
    def get_account_balance(self) -> AccountBalance:
        """帳戶 NAV / 現金。"""

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """所有持倉。"""

    @abstractmethod
    def get_latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        """批次取得最新報價，回傳 {symbol: price}。"""

    @abstractmethod
    def place_order(
        self, symbol: str, qty: float, side: str,
        order_type: str = "market", time_in_force: str = "day",
    ) -> OrderResult:
        """下單。side: 'buy' | 'sell'。"""

    @abstractmethod
    def cancel_all_open_orders(self) -> int:
        """取消所有未成交訂單，回傳取消數。"""

    @abstractmethod
    def wait_for_fills(self, order_ids: List[str], timeout_seconds: int = 120) -> None:
        """阻塞等待指定訂單成交（市場開盤時才用，休市時建議不呼叫）。"""

    # ── 共用 helpers ─────────────────────────────────────────────────────

    def check_capability(self, key: str, value: Any) -> None:
        """檢查指定能力是否被 spec 支援，不支援則 raise BrokerCapabilityError。

        範例：
            self.check_capability("fractional_shares", True)
            self.check_capability("time_in_force", "gtc")
        """
        if key == "fractional_shares":
            if value and not self.capabilities.get("fractional_shares", False):
                raise BrokerCapabilityError(
                    f"{self.broker_id} 不支援零股，請改用整股"
                )
            return
        if key in ("order_types", "time_in_force", "asset_classes"):
            allowed = self.capabilities.get(key, [])
            if value not in allowed:
                raise BrokerCapabilityError(
                    f"{self.broker_id}.{key} 不支援 {value!r}；允許：{allowed}"
                )
            return
        raise ValueError(f"未知 capability key：{key!r}")

    @staticmethod
    def _mask_secret(s: str, keep_prefix: int = 2) -> str:
        """把 secret 字串遮掉中間，只露頭尾。"""
        if not s:
            return ""
        if len(s) <= 6:
            return "***"
        return f"{s[:keep_prefix]}***{s[-2:]}"

    def __repr__(self) -> str:
        """安全的 repr — 不洩露任何 secret。"""
        return f"{self.__class__.__name__}(broker={self.broker_id!r}, env={self.environment!r})"
