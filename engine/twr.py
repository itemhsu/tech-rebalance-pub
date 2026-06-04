"""
engine/twr.py — 時間加權報酬率（TWR）計算

TWR 將現金流量（入金/出金）從投資績效中剝離，
正確衡量策略本身的報酬，而不受資金進出影響。

計算邏輯：
  子期間 i 的報酬 = (nav_end_i / nav_start_i) - 1
  TWR = ∏(1 + sub_return_i) - 1
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def compute_twr(nav_history: List[dict], events: List[dict]) -> float:
    """
    計算 TWR（時間加權報酬率）。

    Parameters
    ----------
    nav_history : [{"date": "YYYY-MM-DD", "nav": float}, ...]
                  按日期升序排列
    events      : [{"date": ..., "type": ..., "nav_before": ..., "nav_after": ...}, ...]
                  只有 deposit / withdrawal 會切割子期間

    Returns
    -------
    TWR 百分比（e.g. 28.45 表示 +28.45%）
    """
    if not nav_history:
        return 0.0

    # 找出現金流量事件（按日期排序）
    cash_events = sorted(
        [e for e in events if e["type"] in ("deposit", "withdrawal")],
        key=lambda e: e["date"],
    )

    if not cash_events:
        # 無現金流：TWR = 簡單報酬
        initial = nav_history[0]["nav"]
        final   = nav_history[-1]["nav"]
        if initial <= 0:
            return 0.0
        return (final / initial - 1) * 100

    # 有現金流：分子期間計算
    nav_lookup = {p["date"]: p["nav"] for p in nav_history}

    # 子期間邊界：inception + 每個現金流事件前後 + 最終
    sub_period_returns = []
    nav_start = nav_history[0]["nav"]

    for evt in cash_events:
        nav_before = evt["nav_before"]
        nav_after  = evt["nav_after"]

        # 本子期間：從 nav_start 到 nav_before（現金流前）
        if nav_start > 0 and nav_before > 0:
            sub_r = nav_before / nav_start - 1
            sub_period_returns.append(sub_r)

        # 下個子期間從 nav_after 開始
        nav_start = nav_after

    # 最後一個子期間：最後一個現金流後 → 最終
    final_nav = nav_history[-1]["nav"]
    if nav_start > 0 and final_nav > 0:
        sub_r = final_nav / nav_start - 1
        sub_period_returns.append(sub_r)

    # TWR = ∏(1 + sub_r) - 1
    twr = 1.0
    for r in sub_period_returns:
        twr *= (1 + r)
    return (twr - 1) * 100


def compute_net_contribution(events: List[dict]) -> float:
    """
    計算淨貢獻（總入金 - 總出金）。
    入金 amount > 0，出金 amount < 0。
    """
    total = 0.0
    for e in events:
        if e["type"] in ("deposit", "withdrawal"):
            total += e.get("amount", 0.0)
    return total


def compute_totals(events: List[dict]) -> tuple[float, float]:
    """
    回傳 (total_deposited, total_withdrawn)。
    total_deposited: 所有入金之和（正數）
    total_withdrawn: 所有出金之絕對值之和（正數）
    """
    deposited = 0.0
    withdrawn = 0.0
    for e in events:
        if e["type"] == "deposit":
            deposited += e.get("amount", 0.0)
        elif e["type"] == "withdrawal":
            withdrawn += abs(e.get("amount", 0.0))
    return deposited, withdrawn


def compute_investment_gain(nav: float, initial_nav: float, net_contribution: float) -> float:
    """純策略損益（排除資金進出）。"""
    return nav - initial_nav - net_contribution
