"""
engine/strategy_card.py — 策略描述卡片產生器

把任意 strategy JSON（v1 或 v3）轉成一個結構化的 strategy_card dict，
供 email_renderer 和 mvp_dashboard.html 使用。

輸出格式（strategy_card）：
{
  "name":               str,
  "description":        str,
  "tags":               [str, ...],
  "benchmark":          str,
  "universe_summary":   str,
  "selection_summary":  str,
  "rebalancing_summary": str,
  "risk_highlights":    [str, ...],   # 最多 5 條
  "ranking_factors":    [{"name":str,"weight":str}, ...],  # v3 only
  "filter_summary":     {"fundamental":[str,...], "technical":[str,...]},  # v3 only
}
"""
from __future__ import annotations

from typing import Any

# ── 欄位顯示名稱對照 ──────────────────────────────────────────────────────────
_FACTOR_LABELS: dict[str, str] = {
    "momentum_90d":       "90日動能",
    "momentum_60d":       "60日動能",
    "momentum_20d":       "20日動能",
    "ma_gap_50":          "MA50偏離度",
    "ma_slope_20_5d":     "MA20斜率",
    "ma_slope_50_10d":    "MA50斜率",
    "macd_histogram":     "MACD柱",
    "adx_14":             "ADX趨勢強度",
    "volume_ratio_20d":   "量比",
    "roe":                "ROE",
    "revenue_growth_yoy": "營收成長",
    "pe_ratio":           "本益比",
    "market_cap":         "市值",
}

_FIELD_LABELS: dict[str, str] = {
    "revenue_growth_yoy": "營收年成長",
    "eps_ttm":            "EPS (TTM)",
    "roe":                "ROE",
    "debt_to_equity":     "負債比",
    "pe_ratio":           "本益比",
    "adjusted_close":     "股價",
    "sma_50":             "SMA50",
    "sma_200":            "SMA200",
    "rsi_14":             "RSI",
    "adx_14":             "ADX",
    "volume_ratio_20d":   "量比",
    "atr_pct":            "ATR%",
}

_OP_LABELS: dict[str, str] = {
    ">":       ">",
    ">=":      "≥",
    "<":       "<",
    "<=":      "≤",
    "=":       "=",
    "==":      "=",
    "!=":      "≠",
    "between": "介於",
}

_FREQ_LABELS: dict[str, str] = {
    "daily":   "每日",
    "weekly":  "每週",
    "monthly": "每月",
}

_DOW_LABELS: dict[str, str] = {
    "MON": "週一", "TUE": "週二", "WED": "週三",
    "THU": "週四", "FRI": "週五",
}


# ── 公開 API ──────────────────────────────────────────────────────────────────

def build_strategy_card(strategy_cfg: dict) -> dict:
    """
    把策略 dict 轉成 strategy_card dict。
    v1 / v3 均可處理；v3 額外輸出 ranking_factors 與 filter_summary。
    """
    meta     = strategy_cfg.get("meta",        {})
    uni      = strategy_cfg.get("universe",    {})
    sel      = strategy_cfg.get("selection",   {})
    port     = strategy_cfg.get("portfolio",   {})
    reb      = strategy_cfg.get("rebalancing", {})
    risk     = strategy_cfg.get("risk",        {})
    rank_cfg = strategy_cfg.get("ranking",     {})
    filters  = strategy_cfg.get("filters",     {})

    return {
        "name":                meta.get("name", strategy_cfg.get("id", "")),
        "description":         meta.get("description", ""),
        "tags":                meta.get("tags", []),
        "benchmark":           meta.get("benchmark", ""),
        "universe_summary":    _universe_summary(uni),
        "selection_summary":   _selection_summary(sel, port),
        "rebalancing_summary": _rebalancing_summary(reb),
        "risk_highlights":     _risk_highlights(risk),
        "ranking_factors":     _ranking_factors(rank_cfg),
        "filter_summary":      _filter_summary(filters),
    }


# ── 各區塊轉換 ────────────────────────────────────────────────────────────────

def _universe_summary(uni: dict) -> str:
    uni_type = uni.get("type", "")
    if uni_type == "exchange_filter":
        exchanges     = " + ".join(uni.get("exchanges", ["NASDAQ", "NYSE"]))
        min_mcap_b    = uni.get("min_market_cap", 0) / 1e9
        exclude_sec   = uni.get("exclude_sectors", [])
        parts = [exchanges, f"市值 ≥ ${min_mcap_b:.0f}B"]
        if exclude_sec:
            parts.append(f"排除 {'/'.join(exclude_sec)}")
        return "，".join(parts)
    elif uni_type == "single":
        src = uni.get("source", {})
        return src.get("path", "custom universe")
    elif uni_type == "grouped":
        groups = uni.get("groups", [])
        return " + ".join(g.get("label", g.get("id", "")) for g in groups)
    return uni_type


def _selection_summary(sel: dict, port: dict) -> str:
    method  = sel.get("method", "")
    target_n = sel.get("n") or port.get("target_n", "?")
    weight   = port.get("weighting", "equal")
    weight_label = {"equal": "等權重", "market_cap": "市值加權", "custom": "自訂權重"}.get(weight, weight)

    if method == "weighted_percentile":
        watchlist = sel.get("watchlist_top_n", 20)
        min_score = sel.get("min_score", 70)
        return f"多因子加權百分位數，持股 {target_n} 檔（{weight_label}，觀察名單 {watchlist}，最低分 {min_score}）"
    elif method == "top_n_by_metric":
        metric = sel.get("metric", "market_cap")
        metric_label = {"market_cap": "市值"}.get(metric, metric)
        return f"依{metric_label}排名前 {target_n} 檔，{weight_label}"
    elif method == "top_n_per_group":
        quotas = sel.get("group_quotas", {})
        parts  = [f"{g} ×{n}" for g, n in quotas.items()]
        return "，".join(parts) + f"，合計 {sum(quotas.values())} 檔，{weight_label}"
    return f"{method}，{target_n} 檔"


def _rebalancing_summary(reb: dict) -> str:
    freq  = reb.get("frequency", "daily")
    label = _FREQ_LABELS.get(freq, freq)
    parts = [label]
    if freq == "weekly":
        dow = reb.get("day_of_week", "MON")
        parts.append(_DOW_LABELS.get(dow, dow))
    t = reb.get("time", "")
    tz = reb.get("timezone", "")
    if t:
        parts.append(t[:5])
    if tz:
        parts.append(tz.replace("America/", "").replace("New_York", "美東"))
    return " ".join(parts)


def _risk_highlights(risk: dict) -> list[str]:
    items: list[str] = []
    if risk.get("trailing_stop_pct"):
        items.append(f"追蹤停損 {risk['trailing_stop_pct']*100:.0f}%")
    if risk.get("stop_loss_atr_multiple"):
        items.append(f"ATR 停損 {risk['stop_loss_atr_multiple']}×ATR")
    if risk.get("take_profit_pct"):
        items.append(f"止盈 {risk['take_profit_pct']*100:.0f}%")
    if risk.get("halt_new_entries_when_drawdown_pct_exceeds"):
        val = risk["halt_new_entries_when_drawdown_pct_exceeds"]
        # ⚠️  顯示用：此欄位目前尚未在執行層（trader.py / portfolio.py）中落地，
        # 若要真正封鎖新倉，需在 execute_rebalance 或 calculate_rebalance 中實作。
        items.append(f"回撤 > {val*100:.0f}% 停止新倉（顯示用，待實作）")
    if risk.get("max_daily_loss_pct"):
        items.append(f"單日虧損上限 {risk['max_daily_loss_pct']*100:.0f}%")
    if risk.get("max_single_position_pct"):
        items.append(f"單倉上限 {risk['max_single_position_pct']:.0f}%")
    return items[:6]


def _ranking_factors(rank_cfg: dict) -> list[dict]:
    factors = rank_cfg.get("factors", [])
    result  = []
    for f in factors:
        field  = f.get("field", "")
        weight = f.get("weight", 0)
        direc  = f.get("direction", "desc")
        label  = _FACTOR_LABELS.get(field, field)
        result.append({
            "name":      label,
            "weight":    f"{weight*100:.0f}%",
            "direction": "↑" if direc == "desc" else "↓",
        })
    return result


def _filter_summary(filters: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key in ("fundamental", "technical"):
        block = filters.get(key)
        if not block:
            continue
        conditions = block.get("conditions", [])
        lines: list[str] = []
        for cond in conditions:
            line = _format_condition(cond)
            if line:
                lines.append(line)
        if lines:
            result[key] = lines
    return result


def _format_condition(cond: dict) -> str:
    field = cond.get("field", "")
    op    = cond.get("op", "")
    value = cond.get("value")
    label = _FIELD_LABELS.get(field, field)
    op_label = _OP_LABELS.get(op, op)

    if op == "between" and isinstance(value, list) and len(value) == 2:
        return f"{label} {value[0]}–{value[1]}"

    # value 可能是欄位名（字串）或數字
    if isinstance(value, str):
        val_label = _FIELD_LABELS.get(value, value)
        return f"{label} {op_label} {val_label}"

    # 百分比格式
    if isinstance(value, float) and abs(value) < 10:
        return f"{label} {op_label} {value*100:.0f}%"

    return f"{label} {op_label} {value}"
