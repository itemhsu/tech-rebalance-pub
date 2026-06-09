"""engine/yf_factors.py — 以 yfinance 取得 factor 原料（給非 Alpaca 市場，如台股）。

提供與 market_cap.py 相容的三個函式（介面對齊，忽略 api_key/secret）：
  fetch_latest_prices(symbols, **_)        → {symbol: 最新收盤}
  fetch_bars_history_batch(symbols, days, **_) → {symbol: DataFrame(含 'close')}
  load_shares(symbols)                     → {symbol: 流通股數}

台股代號用 yfinance 格式（如 '2330.TW'）；market_cap = price × shares 由 runner 計算。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List

log = logging.getLogger("yf_factors")


def _download(symbols: List[str], start: str):
    import yfinance as yf
    return yf.download(symbols, start=start, progress=False,
                       auto_adjust=False, group_by="ticker", threads=True)


def fetch_bars_history_batch(symbols: List[str], days: int = 400, **_) -> Dict:
    """回 {symbol: DataFrame(index=date, 含小寫 'close' 欄)}。"""
    import pandas as pd
    if not symbols:
        return {}
    start = (date.today() - timedelta(days=days + 10)).isoformat()
    raw = _download(symbols, start)
    out: Dict[str, "pd.DataFrame"] = {}
    for s in symbols:
        try:
            if len(symbols) == 1:
                df = raw
            else:
                df = raw[s] if s in raw.columns.get_level_values(0) else None
            if df is None or df.empty or "Close" not in df.columns:
                continue
            sub = df[["Close"]].rename(columns={"Close": "close"}).dropna()
            if not sub.empty:
                out[s] = sub
        except Exception as e:   # noqa: BLE001  單檔失敗不影響其他
            log.warning("yf bars 失敗 %s：%s", s, e)
    return out


def fetch_latest_prices(symbols: List[str], **_) -> Dict[str, float]:
    """最新收盤（取近 7 日最後一筆有效 Close）。"""
    hist = fetch_bars_history_batch(symbols, days=7)
    out: Dict[str, float] = {}
    for s, df in hist.items():
        if df is not None and len(df) > 0:
            out[s] = float(df["close"].iloc[-1])
    return out


def load_shares(symbols: List[str]) -> Dict[str, int]:
    """流通股數：yfinance get_shares_full 最新值；取不到回 0（該檔被排除）。"""
    import yfinance as yf
    out: Dict[str, int] = {}
    for s in symbols:
        try:
            ser = yf.Ticker(s).get_shares_full(start="2020-01-01")
            if ser is not None and len(ser) > 0:
                out[s] = int(ser.iloc[-1])
        except Exception as e:   # noqa: BLE001
            log.warning("yf shares 失敗 %s：%s", s, e)
    return out
