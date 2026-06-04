"""
market_cap.py — 市值計算與排名
透過 Alpaca API 取得最新收盤價，計算市值並排名前 N 大。
fetch_bars_history() 另提供歷史 K 線抓取（供 v3 指標計算）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Alpaca Data API endpoint（免費 IEX feed）
_DATA_URL = "https://data.alpaca.markets"
_BARS_LATEST = "/v2/stocks/bars/latest"

# IEX feed 免費；sip 需 Alpaca Unlimited Data 訂閱
_FEED = "iex"


@dataclass
class StockData:
    symbol: str
    close_price: float
    shares_outstanding: int
    market_cap: float      # = close_price × shares_outstanding
    rank: int


def fetch_latest_prices(
    symbols: list[str],
    api_key: str,
    secret_key: str,
    data_url: str = _DATA_URL,
    feed: str = _FEED,
) -> dict[str, float]:
    """
    使用 Alpaca Data API /v2/stocks/bars/latest 批次取得最新收盤價。
    若某股票無法取得，記錄警告並排除。
    回傳 {symbol: close_price}。
    """
    headers = {
        "APCA-API-KEY-ID":     api_key,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept":              "application/json",
    }

    prices: dict[str, float] = {}
    # 分批：每次最多 100 個 symbol
    batch_size = 100
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        params = {
            "symbols": ",".join(batch),
            "feed":    feed,
        }
        for attempt in range(3):
            try:
                resp = requests.get(
                    data_url + _BARS_LATEST,
                    headers=headers,
                    params=params,
                    timeout=15,
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limit (429)，等待 %ds 後重試…", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                bars = resp.json().get("bars", {})
                for sym, bar_list in bars.items():
                    # bar_list 可能是 list 或 dict
                    bar = bar_list[0] if isinstance(bar_list, list) else bar_list
                    prices[sym.upper()] = float(bar["c"])
                break
            except requests.RequestException as e:
                logger.warning("取得收盤價失敗（attempt %d/3）：%s", attempt + 1, e)
                if attempt == 2:
                    logger.error("批次 %s 無法取得收盤價，跳過", batch)
                time.sleep(2 ** attempt)

    missing = [s for s in symbols if s not in prices]
    if missing:
        logger.warning("無法取得收盤價的股票（排除在外）：%s", missing)
    logger.info("取得收盤價：%d / %d 檔", len(prices), len(symbols))
    return prices


def calculate_market_caps(
    prices: dict[str, float],
    shares: dict[str, int],
) -> dict[str, float]:
    """計算每檔股票的市值 = 收盤價 × 流通股數。"""
    return {
        sym: prices[sym] * shares[sym]
        for sym in prices
        if sym in shares and shares[sym] > 0
    }


def rank_by_market_cap(market_caps: dict[str, float]) -> list[StockData]:
    """
    依市值由大至小排序。
    同市值時以 symbol 字母順序為次要排序（確保結果確定性）。
    """
    sorted_items = sorted(
        market_caps.items(),
        key=lambda x: (-x[1], x[0])
    )
    return [
        StockData(
            symbol=sym,
            close_price=0.0,          # 由呼叫者視需要填入
            shares_outstanding=0,
            market_cap=mcap,
            rank=idx + 1,
        )
        for idx, (sym, mcap) in enumerate(sorted_items)
    ]


def get_top_n(ranked: list[StockData], n: int = 10) -> list[str]:
    """回傳市值前 n 名的 symbol 清單。"""
    return [s.symbol for s in ranked[:n]]


def build_ranked_stocks(
    symbols: list[str],
    prices: dict[str, float],
    shares: dict[str, int],
    n: int = 10,
) -> tuple[list[StockData], list[str]]:
    """
    一站式：計算市值 → 排名 → 取前 N 名。
    回傳 (全排名清單, 前N名 symbol 清單)。
    """
    mcaps = calculate_market_caps(prices, shares)
    ranked = rank_by_market_cap(mcaps)

    # 補回 close_price 和 shares_outstanding
    for sd in ranked:
        sd.close_price = prices.get(sd.symbol, 0.0)
        sd.shares_outstanding = shares.get(sd.symbol, 0)

    top10 = get_top_n(ranked, n)
    logger.info(
        "前 %d 名：%s",
        n,
        "  ".join(f"{i+1}.{s}" for i, s in enumerate(top10)),
    )
    return ranked, top10


# ── 歷史 K 線（供 v3 指標計算）────────────────────────────────────────────────

_BARS_URL = "/v2/stocks/bars"


def fetch_bars_history(
    symbol:     str,
    api_key:    str,
    secret_key: str,
    days:       int = 300,
    timeframe:  str = "1Day",
    data_url:   str = _DATA_URL,
    feed:       str = _FEED,
) -> pd.DataFrame:
    """
    抓取單一股票 `days` 天的日線 OHLCV，回傳 DataFrame。
    index = pd.DatetimeIndex（日期），columns = [open, high, low, close, volume]
    失敗時回傳空 DataFrame。
    """
    end   = date.today()
    start = end - timedelta(days=days + 10)   # 多抓幾天避免週末/假日缺口

    headers = {
        "APCA-API-KEY-ID":     api_key,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept":              "application/json",
    }
    params = {
        "symbols":   symbol,
        "timeframe": timeframe,
        "start":     start.isoformat(),
        "end":       end.isoformat(),
        "feed":      feed,
        "limit":     1000,
    }

    rows: list[dict] = []
    url  = data_url + _BARS_URL
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=20)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            bars = data.get("bars", {}).get(symbol, [])

            # 處理分頁
            next_page = data.get("next_page_token")
            while next_page:
                params2 = dict(params)
                params2["page_token"] = next_page
                r2 = requests.get(url, headers=headers, params=params2, timeout=20)
                r2.raise_for_status()
                d2 = r2.json()
                bars.extend(d2.get("bars", {}).get(symbol, []))
                next_page = d2.get("next_page_token")

            for bar in bars:
                rows.append({
                    "date":   bar["t"][:10],
                    "open":   float(bar["o"]),
                    "high":   float(bar["h"]),
                    "low":    float(bar["l"]),
                    "close":  float(bar["c"]),
                    "volume": float(bar["v"]),
                })
            break

        except requests.RequestException as exc:
            logger.warning("fetch_bars_history %s attempt %d 失敗：%s", symbol, attempt + 1, exc)
            time.sleep(2 ** attempt)

    if not rows:
        logger.warning("fetch_bars_history：%s 無資料", symbol)
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.tail(days)   # 確保不超過需要的天數
    return df


def fetch_bars_history_batch(
    symbols:    list[str],
    api_key:    str,
    secret_key: str,
    days:       int = 300,
    timeframe:  str = "1Day",
    data_url:   str = _DATA_URL,
    feed:       str = _FEED,
    batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    """
    批次抓取多支股票歷史 K 線（分批請求，每批最多 50 個 symbol）。
    回傳 {symbol: DataFrame}
    """
    end   = date.today()
    start = end - timedelta(days=days + 10)

    headers = {
        "APCA-API-KEY-ID":     api_key,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept":              "application/json",
    }

    all_bars: dict[str, list[dict]] = {s: [] for s in symbols}
    url = data_url + _BARS_URL

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i: i + batch_size]
        params = {
            "symbols":   ",".join(batch),
            "timeframe": timeframe,
            "start":     start.isoformat(),
            "end":       end.isoformat(),
            "feed":      feed,
            "limit":     10000,
        }
        for attempt in range(3):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
                if resp.status_code == 429:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                bars_dict = data.get("bars", {})
                for sym, bars in bars_dict.items():
                    all_bars[sym.upper()].extend(bars)

                next_page = data.get("next_page_token")
                while next_page:
                    p2 = dict(params)
                    p2["page_token"] = next_page
                    r2 = requests.get(url, headers=headers, params=p2, timeout=30)
                    r2.raise_for_status()
                    d2 = r2.json()
                    for sym, bars in d2.get("bars", {}).items():
                        all_bars[sym.upper()].extend(bars)
                    next_page = d2.get("next_page_token")
                break
            except requests.RequestException as exc:
                logger.warning("批次歷史 K 線 attempt %d 失敗：%s", attempt + 1, exc)
                time.sleep(2 ** attempt)

        time.sleep(0.2)   # 避免 rate limit

    # 轉換為 DataFrame
    result: dict[str, pd.DataFrame] = {}
    for sym, rows in all_bars.items():
        if not rows:
            continue
        df_rows = [
            {
                "date":   bar["t"][:10],
                "open":   float(bar["o"]),
                "high":   float(bar["h"]),
                "low":    float(bar["l"]),
                "close":  float(bar["c"]),
                "volume": float(bar["v"]),
            }
            for bar in rows
        ]
        df = pd.DataFrame(df_rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index().tail(days)
        result[sym] = df

    logger.info("批次 K 線抓取完成：%d / %d 檔有資料", len(result), len(symbols))
    return result
