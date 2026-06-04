"""
market_state.py — 每日市場狀態偵測（建倉時機通知用）

偵測 5 個 S&P 500 指標，判斷現在是牛市還是熊市。
熊市 = 潛在的大筆資金建倉窗口。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MarketState:
    spy_price:    float          # S&P 500 最新收盤
    spy_1m_ret:   float          # 近1個月報酬
    spy_3m_ret:   float          # 近3個月報酬（63日）
    spy_12m_ret:  float          # 近12個月報酬（252日）
    spy_dd_from_high: float      # 距52週高點回撤%
    indicators:   dict           # {name: {"bull": bool, "value": str, "desc": str}}
    bear_count:   int            # 幾個指標認定為熊市
    signal:       str            # "strong_bear" / "bear" / "neutral" / "bull"
    as_of:        str            # 日期字串


INDICATOR_META = {
    "MA200": {
        "name": "200日均線",
        "bull_desc": "S&P 500 站上 200MA → 長期趨勢向上",
        "bear_desc": "S&P 500 跌破 200MA → 長期趨勢向下",
    },
    "GX": {
        "name": "黃金/死亡交叉",
        "bull_desc": "50MA > 200MA → 黃金交叉（多頭排列）",
        "bear_desc": "50MA < 200MA → 死亡交叉（空頭排列）",
    },
    "MOM12": {
        "name": "12個月動能",
        "bull_desc": "S&P 500 年報酬為正 → 長線動能向上",
        "bear_desc": "S&P 500 年報酬為負 → 長線動能向下 ★最強信號",
    },
    "MOM3": {
        "name": "3個月動能",
        "bull_desc": "S&P 500 近3月報酬為正 → 短線動能向上",
        "bear_desc": "S&P 500 近3月報酬為負 → 短線動能向下",
    },
    "DD10": {
        "name": "距高點回撤",
        "bull_desc": "距52週高點回撤 < 10% → 接近高點",
        "bear_desc": "距52週高點回撤 ≥ 10% → 明顯修正 ★較強信號",
    },
}


def fetch_spy_data(period: str = "2y") -> Optional[pd.Series]:
    """下載 S&P 500（^GSPC）歷史收盤價，失敗回傳 None。"""
    try:
        raw = yf.download("^GSPC", period=period,
                          auto_adjust=False, progress=False)
        s = raw["Close"].squeeze()
        if hasattr(s, "columns"):          # multi-level columns 防護
            s = s.iloc[:, 0]
        s = s.dropna()
        logger.info("S&P 500 資料：%d 天，最新 %.2f", len(s), s.iloc[-1])
        return s
    except Exception as e:
        logger.error("S&P 500 資料下載失敗：%s", e)
        return None


def compute_market_state(spy: pd.Series) -> MarketState:
    """根據 S&P 500 收盤序列計算所有指標，回傳 MarketState。"""
    if len(spy) < 252:
        logger.warning("S&P 500 資料不足 252 天，部分指標可能 N/A")

    latest = float(spy.iloc[-1])
    as_of  = str(spy.index[-1].date())

    def safe_ret(n: int) -> float:
        if len(spy) <= n:
            return float("nan")
        return float(spy.iloc[-1] / spy.iloc[-n] - 1)

    spy_1m_ret  = safe_ret(21)
    spy_3m_ret  = safe_ret(63)
    spy_12m_ret = safe_ret(252)
    high_52w    = float(spy.iloc[-min(252, len(spy)):].max())
    dd_pct      = (latest / high_52w - 1) * 100 if high_52w > 0 else 0.0

    # 計算均線
    ma50  = float(spy.iloc[-50:].mean())  if len(spy) >= 50  else float("nan")
    ma200 = float(spy.iloc[-200:].mean()) if len(spy) >= 200 else float("nan")

    indicators: dict = {}

    # MA200
    bull_ma200 = (latest > ma200) if not np.isnan(ma200) else True
    indicators["MA200"] = {
        "bull":  bull_ma200,
        "value": f"S&P {latest:.0f} vs MA200 {ma200:.0f}",
        "diff":  f"{(latest/ma200-1)*100:+.1f}%" if not np.isnan(ma200) else "N/A",
        **INDICATOR_META["MA200"],
    }

    # GX（黃金/死亡交叉）
    bull_gx = (ma50 > ma200) if (not np.isnan(ma50) and not np.isnan(ma200)) else True
    indicators["GX"] = {
        "bull":  bull_gx,
        "value": f"MA50 {ma50:.0f} vs MA200 {ma200:.0f}",
        "diff":  f"{(ma50/ma200-1)*100:+.1f}%" if (not np.isnan(ma50) and not np.isnan(ma200)) else "N/A",
        **INDICATOR_META["GX"],
    }

    # MOM12
    bull_mom12 = (spy_12m_ret > 0) if not np.isnan(spy_12m_ret) else True
    indicators["MOM12"] = {
        "bull":  bull_mom12,
        "value": f"年報酬 {spy_12m_ret*100:+.1f}%" if not np.isnan(spy_12m_ret) else "N/A",
        "diff":  "",
        **INDICATOR_META["MOM12"],
    }

    # MOM3
    bull_mom3 = (spy_3m_ret > 0) if not np.isnan(spy_3m_ret) else True
    indicators["MOM3"] = {
        "bull":  bull_mom3,
        "value": f"3月報酬 {spy_3m_ret*100:+.1f}%" if not np.isnan(spy_3m_ret) else "N/A",
        "diff":  "",
        **INDICATOR_META["MOM3"],
    }

    # DD10
    bull_dd10 = (dd_pct > -10.0)
    indicators["DD10"] = {
        "bull":  bull_dd10,
        "value": f"距高點 {dd_pct:.1f}%",
        "diff":  f"（52週高點 {high_52w:.0f}）",
        **INDICATOR_META["DD10"],
    }

    bear_count = sum(1 for v in indicators.values() if not v["bull"])

    if bear_count >= 4:
        signal = "strong_bear"
    elif bear_count >= 2:
        signal = "bear"
    elif bear_count == 1:
        signal = "neutral"
    else:
        signal = "bull"

    return MarketState(
        spy_price=latest,
        spy_1m_ret=spy_1m_ret,
        spy_3m_ret=spy_3m_ret,
        spy_12m_ret=spy_12m_ret,
        spy_dd_from_high=dd_pct,
        indicators=indicators,
        bear_count=bear_count,
        signal=signal,
        as_of=as_of,
    )


def get_market_state() -> Optional[MarketState]:
    """對外主入口：下載資料 + 計算狀態，失敗回傳 None。"""
    spy = fetch_spy_data()
    if spy is None or len(spy) < 5:
        return None
    return compute_market_state(spy)
