"""
email_report.py — 每日交易報告電子郵件
寄信方式：Gmail SMTP（EMAIL_PASSWORD / 舊名 EMAIL_APP_PASSWORD）。SendGrid 已棄用移除。
收件人透過 EMAIL_RECIPIENT 環境變數設定。
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests as _requests

from portfolio import PortfolioState, HISTORY_PATH
from market_state import MarketState, get_market_state
try:
    from harvest import HarvestPlan
except ImportError:
    HarvestPlan = None   # type: ignore

logger = logging.getLogger(__name__)

# 台灣時間 UTC+8
TW_TZ = timezone(timedelta(hours=8))

# 預設收件人（可透過 EMAIL_RECIPIENT 覆蓋）
DEFAULT_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")  # 不硬寫個人信箱

# GitHub Pages Dashboard URL（可透過 DASHBOARD_URL 覆蓋）
DEFAULT_DASHBOARD_URL = "https://itemhsu.github.io/tech-rebalance-dashboard/mvp_dashboard.html?a=1"


# ── 格式化工具 ────────────────────────────────────────────────────────────────

def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_pct(v: float, digits: int = 2) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{digits}f}%"


def _color(v: float) -> str:
    return "#10b981" if v >= 0 else "#ef4444"


def _load_history(path: Path = HISTORY_PATH) -> dict:
    if not path.exists():
        return {"initial_nav": 0, "start_date": "", "history": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 近365天回撤 SVG 圖（email-safe，不需要 JS）─────────────────────────────────

def _build_drawdown_svg_html(hist_arr: list) -> str:
    """
    生成近365天「投組 vs NASDAQ vs S&P500」回撤對比的內嵌 SVG，
    可直接嵌入 HTML 郵件（Gmail 支援 inline SVG）。
    """
    from datetime import date as _date, timedelta

    today_str = _date.today().strftime("%Y-%m-%d")
    bench_cache_path = Path(__file__).parent / "data" / "benchmark_365_cache.json"

    bench: dict = {"labels": [], "nasdaq": [], "sp500": []}
    if bench_cache_path.exists():
        try:
            cached = json.loads(bench_cache_path.read_text(encoding="utf-8"))
            if cached.get("fetched_date") == today_str:
                bench = cached
        except Exception:
            pass

    if not bench.get("labels"):
        try:
            import yfinance as yf
            import pandas as pd
            cutoff = _date.today() - timedelta(days=365)
            start  = (cutoff - timedelta(days=5)).strftime("%Y-%m-%d")
            raw = yf.download(
                ["^IXIC", "^GSPC"], start=start, end=today_str,
                auto_adjust=True, progress=False, threads=True,
            )
            closes = raw["Close"].copy()
            try:
                closes.index = closes.index.tz_localize(None)
            except TypeError:
                pass
            closes = closes.dropna(how="all")
            import pandas as _pd
            closes = closes[closes.index >= _pd.Timestamp(cutoff)]
            bench["labels"] = [d.strftime("%Y-%m-%d") for d in closes.index]
            for col, key in [("^IXIC", "nasdaq"), ("^GSPC", "sp500")]:
                if col not in closes.columns:
                    bench[key] = [None] * len(bench["labels"])
                    continue
                s = closes[col].ffill().bfill()   # bfill 補頭部 NaN
                peak = float(s.iloc[0]) if not s.empty else 100.0
                dd = []
                for p in s:
                    pf = float(p)
                    if pf != pf:   # NaN 檢查（NaN != NaN 為 True）
                        dd.append(None)
                        continue
                    peak = max(peak, pf)
                    dd.append(round((pf - peak) / peak * 100, 2))
                bench[key] = dd
        except Exception as exc:
            logger.warning("回撤 SVG：無法下載基準資料 %s", exc)
            return ""

    labels = bench["labels"]
    if not labels:
        return ""

    # 投組回撤
    nav_dict = {h["date"]: h["nav"] for h in hist_arr}
    port_dd: list = []
    peak_p: float | None = None
    for d in labels:
        nav = nav_dict.get(d)
        if nav is None:
            port_dd.append(None)
        else:
            nav = float(nav)
            if peak_p is None:
                peak_p = nav
            peak_p = max(peak_p, nav)
            port_dd.append(round((nav - peak_p) / peak_p * 100, 2))

    nasdaq_dd = bench.get("nasdaq", [None] * len(labels))
    sp500_dd  = bench.get("sp500",  [None] * len(labels))

    # ── SVG 佈局 ─────────────────────────────────────────────────────────────
    W, H       = 580, 190
    PAD_L      = 44    # 左邊 y 軸標籤
    PAD_R      = 12
    PAD_T      = 10
    PAD_B      = 30    # 下方 x 軸標籤
    CW         = W - PAD_L - PAD_R   # 圖表區寬
    CH         = H - PAD_T - PAD_B   # 圖表區高

    # Y 軸範圍
    # 過濾 None 與 NaN（yfinance SQLite 鎖定失敗時 NaN 會混入）
    all_vals = [
        v for v in (nasdaq_dd + sp500_dd + port_dd)
        if v is not None and v == v   # v == v 為 False 代表 NaN
    ]
    y_min = min(all_vals) if all_vals else -30.0
    if y_min != y_min:                      # 萬一仍是 NaN，給預設值
        y_min = -30.0
    y_min = min(y_min * 1.08, y_min - 2)   # 留一點呼吸空間
    y_min = max(y_min, -70.0)               # 最多顯示到 -70%
    y_min = round(y_min / 10) * 10          # 取整到 10%

    def y_px(val: float | None) -> float | None:
        if val is None:
            return None
        return PAD_T + CH * (1.0 - (val - y_min) / (0.0 - y_min))

    def x_px(i: int) -> float:
        return PAD_L + CW * i / max(len(labels) - 1, 1)

    # 建構 polyline 點串（跳過 None）
    def make_path(dd_list: list) -> str:
        segments = []
        current: list[str] = []
        for i, v in enumerate(dd_list):
            yp = y_px(v)
            if yp is None:
                if current:
                    segments.append("M " + " L ".join(current))
                    current = []
            else:
                current.append(f"{x_px(i):.1f},{yp:.1f}")
        if current:
            segments.append("M " + " L ".join(current))
        return " ".join(segments)

    path_port   = make_path(port_dd)
    path_nasdaq = make_path(nasdaq_dd)
    path_sp500  = make_path(sp500_dd)

    # Y 軸格線 & 標籤
    grid_lines = ""
    y_ticks = range(0, int(y_min) - 1, -10)
    for tick in y_ticks:
        yp = y_px(float(tick))
        if yp is None:
            continue
        is_zero = (tick == 0)
        grid_lines += (
            f'<line x1="{PAD_L}" y1="{yp:.1f}" '
            f'x2="{W - PAD_R}" y2="{yp:.1f}" '
            f'stroke="{"#334155" if is_zero else "#1e293b"}" '
            f'stroke-width="{"1.2" if is_zero else "0.7"}"/>\n'
            f'<text x="{PAD_L - 4}" y="{yp + 4:.1f}" '
            f'text-anchor="end" font-size="9" fill="#64748b">{tick}%</text>\n'
        )

    # X 軸標籤（每隔 ~60 個交易日）
    x_labels = ""
    step = max(1, len(labels) // 6)
    for i in range(0, len(labels), step):
        xp = x_px(i)
        label = labels[i][5:]   # MM-DD
        x_labels += (
            f'<text x="{xp:.1f}" y="{H - 4}" '
            f'text-anchor="middle" font-size="9" fill="#64748b">{label}</text>\n'
        )
    # 最後一個日期
    if labels:
        x_labels += (
            f'<text x="{x_px(len(labels)-1):.1f}" y="{H - 4}" '
            f'text-anchor="end" font-size="9" fill="#64748b">{labels[-1][5:]}</text>\n'
        )

    # 最大回撤標註
    def worst_label(dd_list: list, color: str, offset_y: int = 0) -> str:
        vals = [(i, v) for i, v in enumerate(dd_list) if v is not None]
        if not vals:
            return ""
        idx, worst = min(vals, key=lambda t: t[1])
        xp = x_px(idx)
        yp = y_px(worst)
        if yp is None:
            return ""
        return (
            f'<text x="{xp:.1f}" y="{yp - 4 + offset_y:.1f}" '
            f'text-anchor="middle" font-size="8.5" fill="{color}" '
            f'font-weight="bold">{worst:.1f}%</text>\n'
        )

    worst_annotations = (
        worst_label(nasdaq_dd, "#a16207",  0) +
        worst_label(sp500_dd,  "#64748b",  0) +
        worst_label(port_dd,   "#38bdf8", -8)
    )

    # 是否有投組資料
    has_port = any(v is not None for v in port_dd)
    port_path_el = (
        f'<path d="{path_port}" fill="none" stroke="#38bdf8" '
        f'stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
    ) if has_port and path_port else ""

    svg = f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;max-width:{W}px;background:#1e293b;border-radius:8px;
            display:block;margin:0 auto;">
  <!-- 格線 -->
  {grid_lines}
  <!-- S&P500 -->
  <path d="{path_sp500}" fill="none" stroke="#64748b"
        stroke-width="1.6" stroke-dasharray="5 3"
        stroke-linejoin="round" stroke-linecap="round"/>
  <!-- NASDAQ -->
  <path d="{path_nasdaq}" fill="none" stroke="#a16207"
        stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>
  <!-- 投組 -->
  {port_path_el}
  <!-- 最大回撤標註 -->
  {worst_annotations}
  <!-- X 軸標籤 -->
  {x_labels}
  <!-- 圖例 -->
  <rect x="{PAD_L}" y="2" width="8" height="8" rx="2" fill="#38bdf8"/>
  <text x="{PAD_L + 11}" y="10" font-size="9.5" fill="#38bdf8" font-weight="bold">我的投組</text>
  <rect x="{PAD_L + 68}" y="2" width="8" height="8" rx="2" fill="#a16207"/>
  <text x="{PAD_L + 79}" y="10" font-size="9.5" fill="#a16207" font-weight="bold">NASDAQ</text>
  <rect x="{PAD_L + 138}" y="2" width="8" height="8" rx="2" fill="#64748b"/>
  <text x="{PAD_L + 149}" y="10" font-size="9.5" fill="#64748b" font-weight="bold">S&amp;P500</text>
</svg>"""

    return f"""
    <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;
               letter-spacing:0.08em;margin:28px 0 10px;">
      📉 近365天回撤對比
    </h2>
    <div style="background:#1e293b;border-radius:8px;padding:12px 8px 4px;margin-bottom:4px;">
      {svg}
    </div>
    <div style="font-size:11px;color:#475569;text-align:right;margin-bottom:4px;">
      投組資料自 {hist_arr[0]['date'] if hist_arr else '—'} 起　基準：近365個交易日
    </div>"""


# ── 稅務收割區塊 HTML ─────────────────────────────────────────────────────────

def _build_harvest_html(plan) -> str:
    """生成「稅務增益收割」區塊 HTML，供嵌入每日郵件。"""
    if plan is None:
        return ""

    # 標的 badges
    ticker_badges = " ".join(
        f'<span style="display:inline-block;background:#1e3a5f;color:#7dd3fc;'
        f'font-family:monospace;font-weight:bold;padding:2px 8px;border-radius:4px;'
        f'font-size:12px;">{it.ticker}</span>'
        for it in plan.items
    )

    # 每股明細列
    detail_rows = ""
    for it in plan.items:
        detail_rows += f"""
        <tr style="border-bottom:1px solid #334155;">
          <td style="padding:7px 12px;font-family:monospace;font-weight:bold;color:#0ea5e9;">{it.ticker}</td>
          <td style="padding:7px 12px;text-align:right;color:#e2e8f0;">{it.shares} 股</td>
          <td style="padding:7px 12px;text-align:right;color:#94a3b8;">${it.avg_cost:.2f}</td>
          <td style="padding:7px 12px;text-align:right;color:#e2e8f0;">${it.current_price:.2f}</td>
          <td style="padding:7px 12px;text-align:right;color:#10b981;font-weight:bold;">${it.realized_gain:,.0f}</td>
        </tr>"""

    # 確認按鈕
    confirm_btn = ""
    if plan.confirm_url:
        confirm_btn = f"""
    <div style="text-align:center;margin:16px 0 8px;">
      <a href="{plan.confirm_url}"
         style="display:inline-block;padding:12px 32px;
                background:linear-gradient(135deg,#059669,#10b981);
                color:#fff;text-decoration:none;border-radius:8px;
                font-weight:bold;font-size:15px;letter-spacing:0.02em;">
        ✅ 執行收割
      </a>
      &nbsp;&nbsp;
      <span style="color:#64748b;font-size:12px;vertical-align:middle;">
        點擊後於確認頁選擇是否執行
      </span>
    </div>"""

    return f"""
    <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;
               letter-spacing:0.08em;margin:28px 0 10px;">
      💰 稅務增益收割機會
    </h2>

    <!-- 主說明橫幅 -->
    <div style="background:#052e16;border-left:4px solid #10b981;
                border-radius:8px;padding:14px 16px;margin-bottom:12px;">
      <div style="font-size:15px;font-weight:bold;color:#4ade80;margin-bottom:6px;">
        今年可在 0% 聯邦稅率內實現 ${plan.total_gain:,.0f} 增益
      </div>
      <div style="font-size:13px;color:#e2e8f0;">
        估算可節省未來稅負 <strong style="color:#4ade80;">${plan.tax_saved:,.0f}</strong>（按 15% 聯邦稅率試算）
      </div>
    </div>

    <!-- KPI 列 -->
    <table style="width:100%;border-spacing:8px;border-collapse:separate;margin:-8px -8px 12px;">
      <tr>
        <td style="background:#1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;">聯邦可用空間</div>
          <div style="font-size:18px;font-weight:bold;color:#38bdf8;">${plan.federal_space:,.0f}</div>
        </td>
        <td style="background:#1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;">本年已收割</div>
          <div style="font-size:18px;font-weight:bold;color:#94a3b8;">${plan.ytd_harvested:,.0f}</div>
        </td>
        <td style="background:#1e293b;border-radius:8px;padding:12px;text-align:center;">
          <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;">計劃實現增益</div>
          <div style="font-size:18px;font-weight:bold;color:#10b981;">${plan.total_gain:,.0f}</div>
        </td>
      </tr>
    </table>

    <!-- 收割標的 -->
    <div style="background:#1e293b;border-radius:8px;padding:10px 14px;margin-bottom:8px;">
      <span style="font-size:11px;color:#64748b;text-transform:uppercase;
                   letter-spacing:0.06em;margin-right:10px;">收割標的</span>
      {ticker_badges}
    </div>

    <!-- 明細表 -->
    <div style="overflow-x:auto;margin-bottom:4px;">
    <table style="width:100%;border-collapse:collapse;background:#1e293b;
                  border-radius:8px;overflow:hidden;min-width:380px;">
      <thead>
        <tr style="border-bottom:1px solid #334155;">
          <th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;">股票</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">股數</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">均價</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">現價</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">實現增益</th>
        </tr>
      </thead>
      <tbody>{detail_rows}</tbody>
    </table>
    </div>

    <div style="font-size:11px;color:#475569;text-align:right;margin-bottom:12px;">
      報稅身份：{plan.filing_status.upper()}　普通所得：${plan.ordinary_income:,.0f}
      {'WA 州居民（7% 稅率適用）' if plan.wa_resident else '非 WA 居民'}
    </div>

    {confirm_btn}

    <div style="background:#1c2333;border-radius:8px;padding:12px 14px;
                margin-top:8px;font-size:12px;color:#64748b;line-height:1.7;">
      ℹ️ 點擊確認後系統將以市價<strong style="color:#94a3b8;">賣出後立即回買</strong>相同股數，
      步升成本基礎。執行時市價可能已有變動，實際增益以成交價為準。<br>
      <strong style="color:#94a3b8;">假設所有持倉為長期資本利得（持有 &gt; 1 年）。</strong>
    </div>"""


# ── 建倉時機區塊 HTML ─────────────────────────────────────────────────────────

def _build_market_state_html(ms: Optional[MarketState]) -> str:
    """生成「建倉時機」區塊 HTML，供嵌入每日郵件。"""
    if ms is None:
        return """
        <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;
                   letter-spacing:0.08em;margin:28px 0 10px;">
          建倉時機偵測
        </h2>
        <p style="color:#64748b;background:#1e293b;border-radius:8px;
                  padding:16px;text-align:center;margin:0;">
          ⚠️ 今日 S&P 500 資料下載失敗，無法判斷市場狀態
        </p>"""

    # 訊號設定
    signal_cfg = {
        "strong_bear": {
            "emoji": "🔴",
            "label": "強熊市訊號",
            "color": "#ef4444",
            "bg":    "#450a0a",
            "msg":   (f"{ms.bear_count}/5 個指標認定為熊市，歷史上是大筆資金建倉的高品質窗口。"
                      "（MOM12熊市進場 5年勝率 73.8%）"),
        },
        "bear": {
            "emoji": "🟠",
            "label": "熊市訊號",
            "color": "#f97316",
            "bg":    "#431407",
            "msg":   (f"{ms.bear_count}/5 個指標認定為熊市，可考慮分批部署資金。"
                      "建議等待更多指標確認後再行動。"),
        },
        "neutral": {
            "emoji": "🟡",
            "label": "中性觀望",
            "color": "#eab308",
            "bg":    "#422006",
            "msg":   f"{ms.bear_count}/5 個指標認定為熊市，市場偏中性，繼續觀望。",
        },
        "bull": {
            "emoji": "🟢",
            "label": "牛市 — 等待",
            "color": "#22c55e",
            "bg":    "#052e16",
            "msg":   "0/5 個指標認定為熊市，目前為牛市，等待更好的建倉時機。",
        },
    }
    cfg = signal_cfg[ms.signal]

    # S&P 500 摘要行
    spy_color = "#10b981" if ms.spy_1m_ret >= 0 else "#ef4444"
    spy_summary = (
        f"S&P 500：{ms.spy_price:,.0f}　"
        f"近1月 <span style='color:{spy_color}'>{ms.spy_1m_ret*100:+.1f}%</span>　"
        f"近3月 <span style='color:{'#10b981' if ms.spy_3m_ret>=0 else '#ef4444'}'>"
        f"{ms.spy_3m_ret*100:+.1f}%</span>　"
        f"近12月 <span style='color:{'#10b981' if ms.spy_12m_ret>=0 else '#ef4444'}'>"
        f"{ms.spy_12m_ret*100:+.1f}%</span>　"
        f"距高點 <span style='color:{'#ef4444' if ms.spy_dd_from_high<-10 else '#94a3b8'}'>"
        f"{ms.spy_dd_from_high:.1f}%</span>"
    )

    # 5 個指標列
    ind_rows = ""
    for key, ind in ms.indicators.items():
        is_bull  = ind["bull"]
        dot      = "🟢" if is_bull else "🔴"
        state_lbl = "牛市" if is_bull else "熊市"
        state_color = "#22c55e" if is_bull else "#ef4444"
        desc = ind["bull_desc"] if is_bull else ind["bear_desc"]
        val  = ind.get("value", "")
        diff = ind.get("diff", "")
        ind_rows += f"""
        <tr style="border-bottom:1px solid #334155;">
          <td style="padding:8px 12px;font-weight:bold;color:#e2e8f0;">{dot} {ind['name']}</td>
          <td style="padding:8px 12px;text-align:center;color:{state_color};font-weight:bold;">
            {state_lbl}
          </td>
          <td style="padding:8px 12px;color:#94a3b8;font-family:monospace;font-size:12px;">
            {val} {diff}
          </td>
          <td style="padding:8px 12px;color:#64748b;font-size:12px;">{desc}</td>
        </tr>"""

    return f"""
    <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;
               letter-spacing:0.08em;margin:28px 0 10px;">
      建倉時機偵測（大筆資金進場參考）
    </h2>

    <!-- 主訊號橫幅 -->
    <div style="background:{cfg['bg']};border-left:4px solid {cfg['color']};
                border-radius:8px;padding:14px 16px;margin-bottom:12px;">
      <div style="font-size:16px;font-weight:bold;color:{cfg['color']};margin-bottom:6px;">
        {cfg['emoji']} {cfg['label']}
      </div>
      <div style="font-size:13px;color:#e2e8f0;">{cfg['msg']}</div>
    </div>

    <!-- S&P 500 摘要 -->
    <div style="background:#1e293b;border-radius:8px;padding:12px 16px;
                margin-bottom:10px;font-size:13px;color:#94a3b8;">
      {spy_summary}
    </div>

    <!-- 指標明細表 -->
    <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;background:#1e293b;
                  border-radius:8px;overflow:hidden;min-width:480px;">
      <thead>
        <tr style="border-bottom:1px solid #334155;">
          <th style="padding:8px 12px;text-align:left;font-size:11px;
                     color:#64748b;text-transform:uppercase;">指標</th>
          <th style="padding:8px 12px;text-align:center;font-size:11px;
                     color:#64748b;text-transform:uppercase;">狀態</th>
          <th style="padding:8px 12px;text-align:left;font-size:11px;
                     color:#64748b;text-transform:uppercase;">數值</th>
          <th style="padding:8px 12px;text-align:left;font-size:11px;
                     color:#64748b;text-transform:uppercase;">說明</th>
        </tr>
      </thead>
      <tbody>{ind_rows}</tbody>
    </table>
    </div>

    <div style="margin-top:8px;font-size:11px;color:#475569;text-align:right;">
      資料日期：{ms.as_of}　參考研究：MOM12熊市進場，5年勝率歷史73.8%
    </div>

    <!-- 投資心法 -->
    <div style="margin-top:14px;background:#0f172a;border:1px solid #334155;
                border-radius:8px;padding:14px 18px;">
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;
                  letter-spacing:0.08em;margin-bottom:8px;">💡 投資心法</div>
      <div style="font-size:13px;color:#e2e8f0;line-height:1.8;">
        不要等訊號，<strong style="color:#38bdf8;">直接進場</strong>。<br>
        訊號的功用是：當你<strong>剛好有新資金</strong>要決定時，熊市時更有信心進場，
        不是讓你坐在場外等。<br>
        <span style="color:#94a3b8;">
        科技股長期向上的力量，遠大於選時帶來的優勢。
        最差的決策是「等到完美時機」然後一直沒進場。
        </span>
      </div>
    </div>"""


# ── HTML 郵件生成 ─────────────────────────────────────────────────────────────

def build_html_email(
    state: PortfolioState,
    dashboard_url: str = DEFAULT_DASHBOARD_URL,
    market_state: Optional[MarketState] = None,
    harvest_plan=None,
) -> str:
    """生成完整 HTML 郵件內容。"""
    history  = _load_history()
    hist_arr = history.get("history", [])
    init_nav = history.get("initial_nav", state.nav)

    # 前日 NAV（計算今日變動）
    prev_nav = init_nav
    if len(hist_arr) >= 2:
        prev_nav = hist_arr[-2]["nav"]
    elif len(hist_arr) == 1:
        prev_nav = hist_arr[0]["nav"]

    today_change     = state.nav - prev_nav
    today_change_pct = (today_change / prev_nav * 100) if prev_nav > 0 else 0
    total_return_pct = (state.nav / init_nav - 1) * 100 if init_nav > 0 else 0

    updated_tw = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M 台灣時間")

    change_color = _color(today_change)
    total_color  = _color(total_return_pct)

    # ── 持倉表格 ─────────────────────────────────────────────────────────────
    pos_rows = ""
    for p in sorted(state.positions, key=lambda x: -x.market_value):
        weight   = p.market_value / state.nav * 100 if state.nav > 0 else 0
        pl_color = _color(p.unrealized_pl)
        pos_rows += f"""
        <tr style="border-bottom:1px solid #334155;">
          <td style="padding:8px 12px;font-family:monospace;font-weight:bold;color:#0ea5e9;">{p.symbol}</td>
          <td style="padding:8px 12px;text-align:right;color:#e2e8f0;">{p.qty:.0f}</td>
          <td style="padding:8px 12px;text-align:right;color:#94a3b8;">{_fmt_usd(p.avg_entry_price)}</td>
          <td style="padding:8px 12px;text-align:right;color:#e2e8f0;">{_fmt_usd(p.current_price)}</td>
          <td style="padding:8px 12px;text-align:right;font-weight:bold;color:#e2e8f0;">{_fmt_usd(p.market_value)}</td>
          <td style="padding:8px 12px;text-align:right;color:{pl_color};font-weight:bold;">{_fmt_usd(p.unrealized_pl)}</td>
          <td style="padding:8px 12px;text-align:right;color:{pl_color};">{_fmt_pct(p.unrealized_plpc * 100)}</td>
          <td style="padding:8px 12px;text-align:right;color:#94a3b8;">{weight:.1f}%</td>
        </tr>"""

    # ── 市值排名表格（前15）──────────────────────────────────────────────────
    rank_rows = ""
    for i, rd in enumerate(state.ranked_stocks[:15]):
        in_top10  = rd["symbol"] in state.top10
        row_bg    = "background:#052e16;" if in_top10 else ""
        badge     = ' <span style="font-size:10px;background:#16a34a;color:white;padding:1px 6px;border-radius:3px;margin-left:4px;">持有</span>' if in_top10 else ""
        rank_rows += f"""
        <tr style="border-bottom:1px solid #334155;{row_bg}">
          <td style="padding:8px 12px;text-align:center;color:#64748b;">{i+1}</td>
          <td style="padding:8px 12px;font-family:monospace;font-weight:bold;color:#0ea5e9;">{rd['symbol']}{badge}</td>
          <td style="padding:8px 12px;text-align:right;color:#e2e8f0;">{_fmt_usd(rd['close_price'])}</td>
          <td style="padding:8px 12px;text-align:right;color:#94a3b8;">{rd['shares_outstanding']/1e9:.2f}B</td>
          <td style="padding:8px 12px;text-align:right;font-weight:bold;color:#e2e8f0;">${rd['market_cap']/1e12:.2f}T</td>
        </tr>"""

    # ── 今日交易記錄 ─────────────────────────────────────────────────────────
    if state.orders_executed:
        order_rows = ""
        reason_map = {
            "exit_top10":      "跌出前10",
            "new_entrant":     "新進前10",
            "weight_adjust":   "權重調整",
            "cash_deployment": "現金部署",
        }
        for o in state.orders_executed:
            color = "#10b981" if o.action == "BUY" else "#ef4444"
            reason_label = reason_map.get(o.reason, o.reason)
            order_rows += f"""
            <tr style="border-bottom:1px solid #334155;">
              <td style="padding:7px 12px;color:{color};font-weight:bold;">{o.action}</td>
              <td style="padding:7px 12px;font-family:monospace;color:#0ea5e9;">{o.symbol}</td>
              <td style="padding:7px 12px;text-align:right;color:#e2e8f0;">{o.qty:.0f} 股</td>
              <td style="padding:7px 12px;text-align:right;color:#e2e8f0;">{_fmt_usd(o.estimated_value)}</td>
              <td style="padding:7px 12px;color:#94a3b8;">{reason_label}</td>
            </tr>"""
        orders_section = f"""
        <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:0.08em;margin:28px 0 10px;">
          今日交易（{len(state.orders_executed)} 筆）
        </h2>
        <table style="width:100%;border-collapse:collapse;background:#1e293b;border-radius:8px;overflow:hidden;">
          <thead>
            <tr style="border-bottom:1px solid #334155;">
              <th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;">操作</th>
              <th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;">股票</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">股數</th>
              <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">金額</th>
              <th style="padding:8px 12px;font-size:11px;color:#64748b;text-transform:uppercase;">原因</th>
            </tr>
          </thead>
          <tbody>{order_rows}</tbody>
        </table>"""
    else:
        orders_section = """
        <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:0.08em;margin:28px 0 10px;">今日交易</h2>
        <p style="color:#64748b;background:#1e293b;border-radius:8px;padding:16px;text-align:center;margin:0;">
          今日無交易（持倉均在容忍帶內，無需調整）
        </p>"""

    # ── Top 10 列表 ───────────────────────────────────────────────────────────
    top10_badges = " ".join(
        f'<span style="display:inline-block;background:#0c4a6e;color:#7dd3fc;font-family:monospace;font-weight:bold;padding:3px 10px;border-radius:4px;font-size:13px;">{s}</span>'
        for s in state.top10
    )

    # ── Dashboard 按鈕 ────────────────────────────────────────────────────────
    dashboard_btn = (
        f'<a href="{dashboard_url}" style="display:inline-block;padding:10px 28px;'
        f'background:#0ea5e9;color:white;text-decoration:none;border-radius:6px;'
        f'font-weight:bold;font-size:14px;">🔗 查看完整 Dashboard</a>'
    ) if dashboard_url else ""

    # ── 組合 HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>科技股再平衡報告 {state.date}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="max-width:700px;margin:0 auto;padding:28px 16px;">

  <!-- Header -->
  <div style="margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #1e293b;">
    <h1 style="color:#ffffff;font-size:20px;margin:0 0 6px;">🤖 科技股自動再平衡報告</h1>
    <p style="color:#64748b;font-size:13px;margin:0;">{updated_tw}</p>
  </div>

  <!-- KPI Cards (2×2 grid via table for email compatibility) -->
  <table style="width:100%;border-spacing:10px;border-collapse:separate;margin:-10px -10px 14px;">
    <tr>
      <td style="background:#1e293b;border-radius:10px;padding:16px;width:50%;vertical-align:top;">
        <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">總 NAV</div>
        <div style="font-size:24px;font-weight:bold;color:#ffffff;">{_fmt_usd(state.nav)}</div>
        <div style="font-size:12px;color:#64748b;margin-top:4px;">期初 {_fmt_usd(init_nav)}</div>
      </td>
      <td style="background:#1e293b;border-radius:10px;padding:16px;width:50%;vertical-align:top;">
        <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">今日變動</div>
        <div style="font-size:24px;font-weight:bold;color:{change_color};">{_fmt_usd(today_change)}</div>
        <div style="font-size:12px;color:{change_color};margin-top:4px;">{_fmt_pct(today_change_pct)}</div>
      </td>
    </tr>
    <tr>
      <td style="background:#1e293b;border-radius:10px;padding:16px;vertical-align:top;">
        <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">累計報酬</div>
        <div style="font-size:24px;font-weight:bold;color:{total_color};">{_fmt_pct(total_return_pct)}</div>
        <div style="font-size:12px;color:#64748b;margin-top:4px;">自 {history.get('start_date', '—')}</div>
      </td>
      <td style="background:#1e293b;border-radius:10px;padding:16px;vertical-align:top;">
        <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">現金餘額</div>
        <div style="font-size:24px;font-weight:bold;color:#ffffff;">{_fmt_usd(state.cash)}</div>
        <div style="font-size:12px;color:#64748b;margin-top:4px;">持倉 {len(state.positions)} 檔</div>
      </td>
    </tr>
  </table>

  <!-- Dashboard Button -->
  <div style="text-align:center;margin:20px 0 28px;">
    {dashboard_btn}
  </div>

  <!-- Top 10 -->
  <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:0.08em;margin:0 0 10px;">
    今日前 10 大市值科技股
  </h2>
  <div style="background:#1e293b;border-radius:8px;padding:14px;margin-bottom:4px;line-height:2;">
    {top10_badges}
  </div>

  <!-- Market State / Entry Timing -->
  {_build_market_state_html(market_state)}

  <!-- 365-day Drawdown Comparison Chart -->
  {_build_drawdown_svg_html(hist_arr)}

  <!-- Tax Harvest -->
  {_build_harvest_html(harvest_plan)}

  <!-- Orders -->
  {orders_section}

  <!-- Positions -->
  <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:0.08em;margin:28px 0 10px;">
    當前持倉（{len(state.positions)} 檔）
  </h2>
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;background:#1e293b;border-radius:8px;overflow:hidden;min-width:560px;">
      <thead>
        <tr style="border-bottom:1px solid #334155;">
          <th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;">股票</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">股數</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">均價</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">現價</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">市值</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">損益</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">損益%</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">權重</th>
        </tr>
      </thead>
      <tbody>{pos_rows}</tbody>
    </table>
  </div>

  <!-- Market Cap Ranking -->
  <h2 style="color:#94a3b8;font-size:13px;text-transform:uppercase;letter-spacing:0.08em;margin:28px 0 10px;">
    市值排名（前 15 名，綠底為持有）
  </h2>
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;background:#1e293b;border-radius:8px;overflow:hidden;min-width:380px;">
      <thead>
        <tr style="border-bottom:1px solid #334155;">
          <th style="padding:8px 12px;text-align:center;font-size:11px;color:#64748b;text-transform:uppercase;">排名</th>
          <th style="padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;">股票</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">收盤價</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">流通股數</th>
          <th style="padding:8px 12px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase;">市值（兆）</th>
        </tr>
      </thead>
      <tbody>{rank_rows}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="margin-top:32px;padding-top:20px;border-top:1px solid #1e293b;text-align:center;color:#475569;font-size:12px;line-height:1.8;">
    <p style="margin:0;">🤖 科技股自動再平衡系統 · Alpaca Paper Trading</p>
    <p style="margin:4px 0 0;">
      修改收件人：將 GitHub Secrets 中的
      <code style="background:#1e293b;color:#94a3b8;padding:1px 6px;border-radius:3px;font-size:11px;">EMAIL_RECIPIENT</code>
      改為您的信箱
    </p>
  </div>

</div>
</body>
</html>"""
    return html


# ── 組合郵件主旨 ──────────────────────────────────────────────────────────────

def _build_subject(state: PortfolioState) -> str:
    history  = _load_history()
    hist_arr = history.get("history", [])
    init_nav = history.get("initial_nav", state.nav)
    prev_nav = (
        hist_arr[-2]["nav"] if len(hist_arr) >= 2
        else (hist_arr[0]["nav"] if hist_arr else init_nav)
    )
    change     = state.nav - prev_nav
    change_pct = change / prev_nav * 100 if prev_nav > 0 else 0
    arrow      = "▲" if change >= 0 else "▼"
    trades_str = f"，{len(state.orders_executed)} 筆交易" if state.orders_executed else "，無異動"
    return (
        f"[{state.date}] 再平衡報告 "
        f"NAV ${state.nav:,.0f} {arrow}{abs(change_pct):.2f}%{trades_str}"
    )


# ── Gmail SMTP（唯一寄送通道；SendGrid 已棄用移除）──────────────────────────────

def _send_via_gmail(
    html_body: str,
    subject: str,
    recipient: str,
    sender: str,
    app_password: str,
) -> bool:
    """透過 Gmail SMTP (port 465 SSL) 寄送 HTML 郵件。"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"科技股再平衡 <{sender}>"
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 嘗試 SSL 465 再試 TLS 587
    for port, use_ssl in [(465, True), (587, False)]:
        try:
            if use_ssl:
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL("smtp.gmail.com", port, context=ctx, timeout=30) as s:
                    s.login(sender, app_password)
                    s.sendmail(sender, [recipient], msg.as_string())
            else:
                with smtplib.SMTP("smtp.gmail.com", port, timeout=30) as s:
                    s.ehlo()
                    s.starttls()
                    s.ehlo()
                    s.login(sender, app_password)
                    s.sendmail(sender, [recipient], msg.as_string())
            logger.info("📧 Gmail 報告郵件已寄出 → %s（port %d）", recipient, port)
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "Gmail SMTP port %d 驗證失敗。"
                "請確認 EMAIL_APP_PASSWORD 為 16 字元 App Password（非登入密碼）", port
            )
            break   # 驗證失敗不重試另一埠
        except Exception as e:
            logger.warning("Gmail port %d 失敗：%s，嘗試下一埠…", port, e)
    return False


# ── 主要入口 ──────────────────────────────────────────────────────────────────

def send_harvest_confirm_email(plan, state: PortfolioState) -> bool:
    """收割執行後寄出確認信（獨立主旨，讓使用者知道已完成）。"""
    recipient    = os.environ.get("EMAIL_RECIPIENT", DEFAULT_RECIPIENT)
    sender       = os.environ.get("EMAIL_SENDER",    recipient)
    app_password = os.environ.get("EMAIL_PASSWORD") or os.environ.get("EMAIL_APP_PASSWORD", "")

    if not app_password:
        return False

    items_html = "".join(
        f"<li>{it.ticker} × {it.shares} 股，實現增益 ${it.realized_gain:,.0f}</li>"
        for it in plan.items
    )
    html_body = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="UTF-8"><title>收割確認</title></head>
<body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:28px;">
<div style="max-width:500px;margin:0 auto;background:#1e293b;border-radius:12px;padding:28px;">
  <h1 style="color:#4ade80;margin-bottom:12px;">✅ 稅務增益收割已執行</h1>
  <p style="color:#94a3b8;margin-bottom:20px;">日期：{plan.as_of}</p>
  <ul style="color:#e2e8f0;line-height:2.2;padding-left:20px;">{items_html}</ul>
  <hr style="border-color:#334155;margin:20px 0;">
  <p style="font-size:14px;color:#e2e8f0;">
    <strong>實現總增益：</strong>
    <span style="color:#4ade80;">${plan.total_gain:,.0f}</span>
  </p>
  <p style="font-size:14px;color:#e2e8f0;">
    <strong>估算節稅：</strong>
    <span style="color:#4ade80;">${plan.tax_saved:,.0f}</span>（@15% 聯邦稅率）
  </p>
  <p style="font-size:12px;color:#64748b;margin-top:16px;">
    訂單已送出，請確認 Alpaca 成交紀錄以取得精確金額。
  </p>
</div>
</body></html>"""

    subject = f"[{plan.as_of}] ✅ 稅務收割完成 — 實現增益 ${plan.total_gain:,.0f}"
    return _send_via_gmail(html_body, subject, recipient, sender, app_password)


def send_report(
    state: PortfolioState,
    dashboard_url: Optional[str] = None,
    recipient: Optional[str] = None,
    sender: Optional[str] = None,
    harvest_plan=None,
) -> bool:
    """
    寄送 HTML 每日報告至指定信箱（Gmail SMTP；SendGrid 已棄用移除）。

    環境變數：
      EMAIL_RECIPIENT  收件人
      EMAIL_SENDER     寄件人地址
      EMAIL_PASSWORD   Gmail App Password（亦相容舊名 EMAIL_APP_PASSWORD）
      DASHBOARD_URL    Dashboard 連結（選填）
    """
    recipient     = recipient     or os.environ.get("EMAIL_RECIPIENT", DEFAULT_RECIPIENT)
    dashboard_url = dashboard_url or os.environ.get("DASHBOARD_URL",   DEFAULT_DASHBOARD_URL)
    sender        = sender        or os.environ.get("EMAIL_SENDER",    recipient)

    app_password = os.environ.get("EMAIL_PASSWORD") or os.environ.get("EMAIL_APP_PASSWORD", "")

    if not app_password:
        logger.warning(
            "未設定 EMAIL_PASSWORD（Gmail App Password），跳過寄信。"
        )
        return False

    subject   = _build_subject(state)
    ms        = get_market_state()
    if ms:
        bear_tag = f" ｜ 市場：{'🔴熊市' if ms.signal in ('strong_bear','bear') else '🟡中性' if ms.signal=='neutral' else '🟢牛市'} {ms.bear_count}/5"
        subject += bear_tag
    if harvest_plan:
        subject += f" ｜ 💰收割 ${harvest_plan.total_gain:,.0f}"
    html_body = build_html_email(state, dashboard_url, market_state=ms, harvest_plan=harvest_plan)

    # Gmail SMTP（唯一通道）
    return _send_via_gmail(html_body, subject, recipient, sender, app_password)


# ── 給 harvest.py 使用的輕量型收割確認信 ──────────────────────────────────────
# （已在 send_harvest_confirm_email() 定義，此處無需重複）
