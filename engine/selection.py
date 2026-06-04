"""engine/selection.py — universal portfolio selector

純函式模組，**不碰網路、不碰檔案、不碰時間**。

輸入：
    spec           : v3 strategy dict（用 selection / ranking 區塊）
    groups         : {group_id: [symbol, ...]}
                      single universe 傳 {"__all__": [...]}
                      grouped universe 傳 {"defense": [...], "pharma": [...], ...}
    factor_values  : {factor_name: {symbol: value, ...}, ...}
                      由呼叫者預先從 broker 資料 / yfinance 等算好
                      標準因子名：market_cap / price_momentum_3m / 6m / 12m
    valid_symbols  : 可選；只考慮這個集合內的 symbol（用於排除沒上市/沒報價）

輸出：
    list[str] — 該日應持有的 symbol 清單，可直接傳給 portfolio.calculate_rebalance

對應 backtest_anchor/tool_v2/engine/spec_engine.py 的 selection 區塊，
但抽出網路 I/O，可在 live 與 backtest 共用同一份邏輯（理想狀態）。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Iterable


# ════════════════════════════════════════════════════════════════════════
#  共用 helpers
# ════════════════════════════════════════════════════════════════════════

def _percentile_score(
    values: Dict[str, float],
    symbols: List[str],
    desc: bool,
) -> Dict[str, float]:
    """把 raw values 轉成 [0, 1] 百分位分數。

    desc=True  → 大值得高分（適合動能、市值）
    desc=False → 小值得高分（適合 volatility、PE）

    沒值的 symbol 得 0；單一 symbol 得 0.5。
    """
    items = [(s, values[s]) for s in symbols if s in values]
    if not items:
        return {s: 0.5 for s in symbols}
    items.sort(key=lambda x: x[1])
    out: Dict[str, float] = {s: 0.0 for s in symbols}
    n = len(items)
    for rank, (s, _) in enumerate(items):
        norm = rank / (n - 1) if n > 1 else 0.5
        out[s] = norm if desc else (1.0 - norm)
    return out


def _filter_universe(
    sel: dict,
    symbols: Iterable[str],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set] = None,
) -> List[str]:
    """套用 exclude_symbols / min_price / valid_symbols 過濾。"""
    excl = {str(s).upper() for s in (sel.get("exclude_symbols") or [])}
    out = [s for s in symbols if s not in excl]

    if valid_symbols is not None:
        out = [s for s in out if s in valid_symbols]

    mp = float(sel.get("min_price", 0) or 0)
    if mp > 0:
        # 假設 factor_values["price"] 存在（呼叫者要帶）
        prices = factor_values.get("price") or {}
        out = [s for s in out if prices.get(s, 0.0) >= mp]
    return out


def _all_symbols(groups: Dict[str, List[str]]) -> List[str]:
    """flatten groups → list（去重保序）。"""
    seen = set()
    out: List[str] = []
    for syms in groups.values():
        for s in syms:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _get_factor(
    factor_values: Dict[str, Dict[str, float]],
    name: str,
) -> Dict[str, float]:
    """取因子值 dict；不存在則回空 dict。"""
    return factor_values.get(name, {})


# ════════════════════════════════════════════════════════════════════════
#  五種 selection methods
# ════════════════════════════════════════════════════════════════════════

def _sel_top_n_by_metric(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set],
) -> List[str]:
    sel = spec["selection"]
    metric = sel.get("metric", "market_cap")
    n = int(sel.get("n", 10))
    all_syms = _all_symbols(groups)
    all_syms = _filter_universe(sel, all_syms, factor_values, valid_symbols)
    vals = _get_factor(factor_values, metric)
    ranked = sorted(all_syms, key=lambda s: vals.get(s, 0.0), reverse=True)
    return ranked[:n]


def _sel_top_n_per_group(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set],
) -> List[str]:
    sel = spec["selection"]
    metric = sel.get("metric", "market_cap")
    quotas = sel.get("group_quotas", {})
    vals = _get_factor(factor_values, metric)

    picks: List[str] = []
    for gid, syms in groups.items():
        q = int(quotas.get(gid, 0))
        if q <= 0:
            continue
        # 過濾 + 排序
        valid = [s for s in syms
                 if valid_symbols is None or s in valid_symbols]
        valid = _filter_universe(sel, valid, factor_values, valid_symbols)
        ranked = sorted(valid, key=lambda s: vals.get(s, 0.0), reverse=True)
        picks.extend(ranked[:q])
    return picks


def _sel_factor_score(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set],
) -> List[str]:
    sel = spec["selection"]
    factors = sel.get("factors", [])
    n = int(sel.get("n", 10))
    all_syms = _filter_universe(sel, _all_symbols(groups), factor_values, valid_symbols)

    scores = {s: 0.0 for s in all_syms}
    for f in factors:
        metric = f.get("metric") or f.get("field")
        weight = float(f.get("weight", 1.0))
        desc = (f.get("direction", "desc") == "desc")
        vals = _get_factor(factor_values, metric)
        ps = _percentile_score(vals, all_syms, desc)
        for s in all_syms:
            scores[s] += weight * ps.get(s, 0.0)

    ranked = sorted(all_syms, key=lambda s: scores[s], reverse=True)
    return ranked[:n]


def _sel_weighted_percentile(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set],
) -> List[str]:
    sel = spec["selection"]
    ranking = spec.get("ranking", {})
    factors = ranking.get("factors", [])
    n = int(sel.get("n", 10))
    wt_metric = sel.get("watchlist_metric", "market_cap")
    wt_n = int(sel.get("watchlist_top_n", n * 2))

    all_syms = _filter_universe(sel, _all_symbols(groups), factor_values, valid_symbols)
    wt_vals = _get_factor(factor_values, wt_metric)
    watchlist = sorted(all_syms, key=lambda s: wt_vals.get(s, 0.0), reverse=True)[:wt_n]

    scores = {s: 0.0 for s in watchlist}
    for f in factors:
        field = f.get("field") or f.get("metric")
        weight = float(f.get("weight", 1.0))
        desc = (f.get("direction", "desc") == "desc")
        vals = _get_factor(factor_values, field)
        ps = _percentile_score(vals, watchlist, desc)
        for s in watchlist:
            scores[s] += weight * ps.get(s, 0.0)
    ranked = sorted(watchlist, key=lambda s: scores[s], reverse=True)
    return ranked[:n]


def _sel_weighted_percentile_per_group(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set],
) -> List[str]:
    """兩段：每組 market_cap 取 group_watchlist 進候選池 → ranking factors 排序 → group_quotas。"""
    sel = spec["selection"]
    ranking = spec.get("ranking", {})
    factors = ranking.get("factors", [])
    wt_metric = sel.get("watchlist_metric", "market_cap")
    group_watchlist = sel.get("group_watchlist", {})
    group_quotas = sel.get("group_quotas", {})
    wt_vals = _get_factor(factor_values, wt_metric)

    picks: List[str] = []
    for gid, syms in groups.items():
        wl_n = int(group_watchlist.get(gid, len(syms)))
        quota = int(group_quotas.get(gid, 0))
        if quota <= 0:
            continue
        valid = _filter_universe(sel, syms, factor_values, valid_symbols)
        watchlist = sorted(valid, key=lambda s: wt_vals.get(s, 0.0), reverse=True)[:wl_n]
        if not watchlist:
            continue
        scores = {s: 0.0 for s in watchlist}
        for f in factors:
            field = f.get("field") or f.get("metric")
            weight = float(f.get("weight", 1.0))
            desc = (f.get("direction", "desc") == "desc")
            vals = _get_factor(factor_values, field)
            ps = _percentile_score(vals, watchlist, desc)
            for s in watchlist:
                scores[s] += weight * ps.get(s, 0.0)
        ranked = sorted(watchlist, key=lambda s: scores[s], reverse=True)
        picks.extend(ranked[:quota])
    return picks


def _sel_buy_and_hold(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set],
) -> List[str]:
    """買入持有：取全部 universe 符號（valid 過濾）。"""
    syms = _all_symbols(groups)
    if valid_symbols is not None:
        syms = [s for s in syms if s in valid_symbols]
    n = int(spec.get("selection", {}).get("n") or len(syms))
    return syms[:n]


# ════════════════════════════════════════════════════════════════════════
#  Dispatcher
# ════════════════════════════════════════════════════════════════════════

_METHODS = {
    "top_n_by_metric":              _sel_top_n_by_metric,
    "top_n_per_group":              _sel_top_n_per_group,
    "factor_score":                 _sel_factor_score,
    "weighted_percentile":          _sel_weighted_percentile,
    "weighted_percentile_per_group": _sel_weighted_percentile_per_group,
    "buy_and_hold":                 _sel_buy_and_hold,
}


def select_portfolio(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set] = None,
) -> List[str]:
    """主入口：解析 spec.selection.method 並 dispatch。

    Raises:
        ValueError: method 不被支援
    """
    method = (spec.get("selection") or {}).get("method")
    if method not in _METHODS:
        raise ValueError(
            f"未知 selection.method={method!r}；支援：{sorted(_METHODS)}"
        )
    return _METHODS[method](spec, groups, factor_values, valid_symbols)


def universe_ranking(
    spec: dict,
    groups: Dict[str, List[str]],
    factor_values: Dict[str, Dict[str, float]],
    valid_symbols: Optional[set] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """回傳「候選池」的完整排名（symbol 由佳到差），與選股同一套指標。

    給 runner 存進 portfolio_state.ranked_stocks，讓 dashboard 候選池顯示真實排名/股價，
    而非只有持有的名單。不只回前 N，回整個 watchlist 的排序。
    """
    sel = spec.get("selection") or {}
    all_syms = _filter_universe(sel, _all_symbols(groups), factor_values, valid_symbols)

    # 候選池（watchlist）：有定義 watchlist_metric 就先取前 watchlist_top_n
    wt_metric = sel.get("watchlist_metric")
    if wt_metric:
        wt_vals = _get_factor(factor_values, wt_metric)
        cand = sorted(all_syms, key=lambda s: wt_vals.get(s, 0.0), reverse=True)
        wt_n = sel.get("watchlist_top_n")
        if wt_n:
            cand = cand[:int(wt_n)]
    else:
        cand = list(all_syms)

    # 排序分數：ranking.factors（加權百分位）或 selection.factors，否則 selection.metric
    factors = (spec.get("ranking", {}) or {}).get("factors") or sel.get("factors")
    if factors:
        scores = {s: 0.0 for s in cand}
        for f in factors:
            field = f.get("field") or f.get("metric")
            weight = float(f.get("weight", 1.0))
            desc = (f.get("direction", "desc") == "desc")
            ps = _percentile_score(_get_factor(factor_values, field), cand, desc)
            for s in cand:
                scores[s] += weight * ps.get(s, 0.0)
        ranked = sorted(cand, key=lambda s: scores[s], reverse=True)
    else:
        metric = sel.get("metric", "market_cap")
        vals = _get_factor(factor_values, metric)
        ranked = sorted(cand, key=lambda s: vals.get(s, 0.0), reverse=True)

    return ranked[:int(limit)] if limit else ranked


def required_factors(spec: dict) -> List[str]:
    """根據 spec 計算需要哪些因子值（給 runner 預先 fetch 用）。"""
    sel = spec.get("selection") or {}
    method = sel.get("method")
    needed: set = set()

    if method == "top_n_by_metric":
        needed.add(sel.get("metric", "market_cap"))
    elif method == "top_n_per_group":
        needed.add(sel.get("metric", "market_cap"))
    elif method == "factor_score":
        for f in sel.get("factors", []):
            needed.add(f.get("metric") or f.get("field"))
    elif method in ("weighted_percentile", "weighted_percentile_per_group"):
        needed.add(sel.get("watchlist_metric", "market_cap"))
        for f in (spec.get("ranking", {}) or {}).get("factors", []):
            needed.add(f.get("field") or f.get("metric"))
    # buy_and_hold 不需要因子

    if sel.get("min_price", 0):
        needed.add("price")

    return sorted(x for x in needed if x)
