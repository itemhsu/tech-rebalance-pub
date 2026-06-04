"""
dashboard.py — 統一 Dashboard 生成引擎

所有策略共用此模組：
  · DashboardConfig  — 策略外觀、行為設定（預設 TOP10_CONFIG）
  · generate()       — 生成 dashboard.html；extra_sections_html 注入策略特有區塊

策略擴充方式：
  1. 建立自己的 DashboardConfig 實例（或使用 D2P2T6_CONFIG）
  2. 在自己的 dashboard_xxx.py 生成 extra_sections_html（HTML 字串）
  3. 呼叫 generate(state, ..., config=xxx_config, extra_sections_html=...)

區塊順序：
  Header → KPI Cards → NAV 歷史圖 → 回撤對比圖
  → 持倉表 → 市值排名（可選，TOP10 專用）
  → extra_sections_html → 交易日誌
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace as dc_replace
from datetime import date as _date, datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

from portfolio import PortfolioState, HISTORY_PATH

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).parent / "dashboard.html"
BENCH_CACHE = Path(__file__).parent / "data" / "benchmark_365_cache.json"
TW_TZ       = timezone(timedelta(hours=8))


# ══════════════════════════════════════════════════════════════════════════════
#  策略設定
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DashboardConfig:
    """
    策略專屬設定，傳入 generate() 客製化外觀與標籤。

    帳戶切換下拉選單：
      account_id      — 當前帳戶 ID（"1", "2", ...）
      all_account_ids — 所有可切換帳戶 ID 清單；None = 不顯示下拉選單
    下拉選單的 URL 使用相對路徑 ../N/dashboard.html，
    因此每個策略的目錄結構必須是 strategy/N/dashboard.html。
    """
    title: str              = "自動再平衡 Dashboard"
    subtitle: str           = ""                # 副標題（策略說明）
    accent_color: str       = "#38bdf8"         # NAV 折線色
    dd_port_color: str      = "#38bdf8"         # 回撤圖投組色
    dd_port_label: str      = "我的投組"         # 回撤圖投組標籤
    portfolio_label: str    = "前10名持股"       # 交易日誌欄標籤
    show_mcap_ranking: bool = True              # 是否顯示市值排名表格（TOP10 用）
    # ── 帳戶切換 ─────────────────────────────────────────────────────────────
    account_id: str              = "1"          # 當前帳戶
    all_account_ids: Optional[List[str]] = None # None = 不顯示選單


# ── 預設設定（不含帳戶，在呼叫端用 with_account() 覆蓋）──────────────────────

TOP10_CONFIG = DashboardConfig(
    title             = "科技股自動再平衡 Dashboard",
    subtitle          = "前 10 大市值科技股 · 等權重 10%",
    accent_color      = "#38bdf8",
    dd_port_color     = "#38bdf8",
    dd_port_label     = "TOP10 投組",
    portfolio_label   = "前10名持股",
    show_mcap_ranking = True,
)

D2P2T6_CONFIG = DashboardConfig(
    title             = "D2P2T6 Dashboard",
    subtitle          = "軍火×2 + 醫藥×2 + 科技×6 = 10 檔等權重",
    accent_color      = "#6366f1",
    dd_port_color     = "#6366f1",
    dd_port_label     = "D2P2T6",
    portfolio_label   = "D2P2T6 組合",
    show_mcap_ranking = False,
)


def with_account(
    base_config: DashboardConfig,
    account_id: str,
    all_account_ids: Optional[List[str]] = None,
) -> DashboardConfig:
    """
    從 base_config 複製一份，注入帳戶資訊。
    呼叫範例：
        cfg = with_account(TOP10_CONFIG, account_id="1", all_account_ids=["1", "2"])
    """
    return dc_replace(
        base_config,
        account_id      = account_id,
        all_account_ids = all_account_ids if all_account_ids is not None else [account_id],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  工具函式
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"


def _account_dropdown_html(cfg: DashboardConfig) -> str:
    """
    生成帳戶切換 <select>。
    · all_account_ids = None 或空列表 → 不顯示
    · 只有 1 個帳戶 → 顯示靜態徽章（無跳轉）
    · 多個帳戶 → 顯示可跳轉的 <select>
    URL 格式：../N/dashboard.html（相對於 strategy/M/dashboard.html）
    """
    ids = cfg.all_account_ids
    if not ids:
        return ""

    if len(ids) == 1:
        return f"""
      <span class="inline-flex items-center gap-1 bg-slate-800 border border-slate-700
                   text-slate-300 text-xs font-semibold px-2.5 py-1 rounded-md">
        帳戶&nbsp;#{ids[0]}
      </span>"""

    options = "\n".join(
        f'        <option value="../{aid}/dashboard.html"'
        f'{"selected" if aid == cfg.account_id else ""}>'
        f'帳戶 #{aid}</option>'
        for aid in ids
    )
    return f"""
      <div class="flex items-center gap-1.5">
        <span class="text-xs text-slate-500">帳戶</span>
        <select
          onchange="if(this.value) location.href = this.value"
          class="bg-slate-800 border border-slate-600 text-slate-200 text-xs
                 font-semibold rounded-md px-2 py-1 cursor-pointer
                 focus:outline-none focus:border-sky-500">
{options}
        </select>
      </div>"""


def _fmt_pct(v: float, digits: int = 2) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{digits}f}%"


def _color_cls(v: float) -> str:
    return "text-emerald-400" if v >= 0 else "text-red-400"


# ══════════════════════════════════════════════════════════════════════════════
#  基準指數回撤（快取 1 天）
# ══════════════════════════════════════════════════════════════════════════════

def _get_benchmark_drawdown_365() -> dict:
    """取得/快取 NASDAQ 與 S&P500 近365個交易日的回撤序列（含 NaN 防護）。"""
    today_str = _date.today().strftime("%Y-%m-%d")

    if BENCH_CACHE.exists():
        try:
            cached = json.loads(BENCH_CACHE.read_text(encoding="utf-8"))
            if cached.get("fetched_date") == today_str:
                return cached
        except Exception:
            pass

    result: dict = {"fetched_date": today_str, "labels": [], "nasdaq": [], "sp500": []}
    try:
        import yfinance as yf
        import pandas as pd

        cutoff = _date.today() - timedelta(days=365)
        start  = (cutoff - timedelta(days=5)).strftime("%Y-%m-%d")
        raw    = yf.download(
            ["^IXIC", "^GSPC"], start=start, end=today_str,
            auto_adjust=True, progress=False, threads=True,
        )
        closes = raw["Close"].copy()
        try:
            closes.index = closes.index.tz_localize(None)
        except TypeError:
            pass
        closes = closes.dropna(how="all")
        closes = closes[closes.index >= pd.Timestamp(cutoff)]
        result["labels"] = [d.strftime("%Y-%m-%d") for d in closes.index]

        for col, key in [("^IXIC", "nasdaq"), ("^GSPC", "sp500")]:
            if col not in closes.columns:
                result[key] = [None] * len(result["labels"])
                continue
            s = closes[col].ffill().bfill()
            peak = float(s.iloc[0]) if not s.empty else 100.0
            dd: list = []
            for p in s:
                pf = float(p)
                if pf != pf:          # NaN guard
                    dd.append(None)
                    continue
                peak = max(peak, pf)
                dd.append(round((pf - peak) / peak * 100, 2))
            result[key] = dd

        BENCH_CACHE.write_text(json.dumps(result), encoding="utf-8")
        logger.info("基準指數回撤資料已快取（%d 個交易日）", len(result["labels"]))
    except Exception as exc:
        logger.warning("無法取得基準指數資料：%s", exc)

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  歷史資料
# ══════════════════════════════════════════════════════════════════════════════

def _load_history(path: Path = HISTORY_PATH) -> dict:
    if not path.exists():
        return {"initial_nav": 0, "start_date": "", "history": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
#  HTML 區塊生成（內部使用）
# ══════════════════════════════════════════════════════════════════════════════

def _kpi_cards_html(state: PortfolioState, history: dict, cfg: DashboardConfig) -> str:
    hist_arr = history.get("history", [])
    init_nav = history.get("initial_nav", state.nav)

    prev_nav = init_nav
    if len(hist_arr) >= 2:
        prev_nav = hist_arr[-2]["nav"]
    elif len(hist_arr) == 1:
        prev_nav = hist_arr[0]["nav"]

    today_chg    = state.nav - prev_nav
    today_chg_pct= (today_chg / prev_nav * 100) if prev_nav > 0 else 0.0
    total_ret    = (state.nav / init_nav - 1) * 100 if init_nav > 0 else 0.0

    last_rebal = "—"
    for h in reversed(hist_arr):
        if h.get("trades_count", 0) > 0:
            last_rebal = h["date"]
            break

    chg_cls   = _color_cls(today_chg)
    total_cls = _color_cls(total_ret)

    return f"""
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
    <div class="card">
      <div class="text-xs text-slate-400 uppercase tracking-wide mb-1">總 NAV</div>
      <div class="text-2xl font-bold text-white">{_fmt_usd(state.nav)}</div>
      <div class="text-xs text-slate-500 mt-1">期初 {_fmt_usd(init_nav)}</div>
    </div>
    <div class="card">
      <div class="text-xs text-slate-400 uppercase tracking-wide mb-1">今日變動</div>
      <div class="text-2xl font-bold {chg_cls}">{_fmt_usd(today_chg)}</div>
      <div class="text-xs {chg_cls} mt-1">{_fmt_pct(today_chg_pct)}</div>
    </div>
    <div class="card">
      <div class="text-xs text-slate-400 uppercase tracking-wide mb-1">累計報酬</div>
      <div class="text-2xl font-bold {total_cls}">{_fmt_pct(total_ret)}</div>
      <div class="text-xs text-slate-500 mt-1">自 {history.get('start_date', '—')}</div>
    </div>
    <div class="card">
      <div class="text-xs text-slate-400 uppercase tracking-wide mb-1">最後再平衡</div>
      <div class="text-xl font-bold text-white">{last_rebal}</div>
      <div class="text-xs text-slate-500 mt-1">現金 {_fmt_usd(state.cash)}</div>
    </div>
  </div>"""


def _nav_chart_html(hist_arr: list, cfg: DashboardConfig, init_nav: float) -> str:
    chart_labels = json.dumps([h["date"] for h in hist_arr])
    chart_navs   = json.dumps([h["nav"]  for h in hist_arr])
    chart_init   = json.dumps([init_nav] * len(hist_arr))
    color        = cfg.accent_color

    return f"""
  <div class="card mb-6">
    <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-4">
      📈 NAV 歷史走勢
    </h2>
    <div style="height:240px">
      <canvas id="navChart"></canvas>
    </div>
  </div>
  <script>
  (function() {{
    const ctx = document.getElementById('navChart').getContext('2d');
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: {chart_labels},
        datasets: [
          {{
            label: '帳戶 NAV',
            data: {chart_navs},
            borderColor: '{color}',
            backgroundColor: '{color}18',
            borderWidth: 2,
            pointRadius: 2,
            fill: true,
            tension: 0.3,
          }},
          {{
            label: '期初投入',
            data: {chart_init},
            borderColor: '#475569',
            borderDash: [5, 5],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
        }},
        scales: {{
          x: {{ ticks: {{ color: '#64748b', maxTicksLimit: 10 }},
               grid:  {{ color: '#1e293b' }} }},
          y: {{ ticks: {{ color: '#64748b',
                          callback: v => '$' + v.toLocaleString('en-US', {{minimumFractionDigits:0}}) }},
               grid: {{ color: '#1e293b' }} }}
        }}
      }}
    }});
  }})();
  </script>"""


def _drawdown_chart_html(hist_arr: list, bench: dict, cfg: DashboardConfig) -> str:
    """回撤對比圖（投組 vs NASDAQ vs S&P500）。"""
    if not bench.get("labels"):
        return ""

    labels  = bench["labels"]
    nasdaq  = bench["nasdaq"]
    sp500   = bench["sp500"]

    nav_dict = {h["date"]: h["nav"] for h in hist_arr}
    port_dd: list = []
    peak: Optional[float] = None
    for d in labels:
        nav = nav_dict.get(d)
        if nav is None:
            port_dd.append(None)
        else:
            nav = float(nav)
            if peak is None:
                peak = nav
            peak = max(peak, nav)
            port_dd.append(round((nav - peak) / peak * 100, 2))

    all_vals = [v for v in (nasdaq + sp500 + port_dd) if v is not None and v == v]
    y_min    = min(all_vals) if all_vals else -30.0
    if y_min != y_min:
        y_min = -30.0

    labels_js = json.dumps(labels)
    port_js   = json.dumps(port_dd)
    nasdaq_js = json.dumps(nasdaq)
    sp500_js  = json.dumps(sp500)
    port_color = cfg.dd_port_color
    port_label = cfg.dd_port_label

    return f"""
  <div class="card mb-6">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wide">
        📉 近365天回撤對比
      </h2>
      <div class="flex flex-wrap gap-4 text-xs">
        <label class="flex items-center gap-1.5 cursor-pointer select-none">
          <input type="checkbox" id="dd_cb_port" checked class="w-3.5 h-3.5">
          <span style="color:{port_color}" class="font-semibold">{port_label}</span>
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer select-none">
          <input type="checkbox" id="dd_cb_nasdaq" checked class="w-3.5 h-3.5">
          <span class="font-semibold" style="color:#a16207">NASDAQ</span>
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer select-none">
          <input type="checkbox" id="dd_cb_sp500" checked class="w-3.5 h-3.5">
          <span class="text-slate-400 font-semibold">S&amp;P500</span>
        </label>
      </div>
    </div>
    <div style="height:220px">
      <canvas id="ddChart"></canvas>
    </div>
  </div>
  <script>
  (function() {{
    const ddCtx  = document.getElementById('ddChart').getContext('2d');
    const ddChart = new Chart(ddCtx, {{
      type: 'line',
      data: {{
        labels: {labels_js},
        datasets: [
          {{
            label: '{port_label}',
            data:  {port_js},
            borderColor: '{port_color}',
            backgroundColor: '{port_color}14',
            borderWidth: 2.4, pointRadius: 0, fill: false,
            tension: 0.25, spanGaps: false,
          }},
          {{
            label: 'NASDAQ',
            data:  {nasdaq_js},
            borderColor: '#a16207',
            borderWidth: 1.8, pointRadius: 0, fill: false,
            tension: 0.25, spanGaps: false,
          }},
          {{
            label: 'S&P500',
            data:  {sp500_js},
            borderColor: '#64748b',
            borderDash: [5, 3],
            borderWidth: 1.6, pointRadius: 0, fill: false,
            tension: 0.25, spanGaps: false,
          }},
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ display: false }},
          tooltip: {{
            callbacks: {{
              label: function(ctx) {{
                if (ctx.raw == null) return null;
                return ctx.dataset.label + ': ' + ctx.raw.toFixed(1) + '%';
              }}
            }}
          }}
        }},
        scales: {{
          x: {{
            ticks: {{ color: '#64748b', maxTicksLimit: 10, font: {{ size: 10 }} }},
            grid:  {{ color: 'rgba(255,255,255,0.04)' }}
          }},
          y: {{
            min: {y_min * 1.1:.1f},
            ticks: {{ color: '#64748b', font: {{ size: 10 }},
                      callback: v => v.toFixed(0) + '%' }},
            grid: {{ color: 'rgba(255,255,255,0.04)' }}
          }}
        }}
      }}
    }});
    [
      {{ id: 'dd_cb_port',   idx: 0 }},
      {{ id: 'dd_cb_nasdaq', idx: 1 }},
      {{ id: 'dd_cb_sp500',  idx: 2 }},
    ].forEach(function(item) {{
      document.getElementById(item.id).addEventListener('change', function() {{
        ddChart.setDatasetVisibility(item.idx, this.checked);
        ddChart.update();
      }});
    }});
  }})();
  </script>"""


def _holdings_table_html(state: PortfolioState, cfg: DashboardConfig) -> str:
    """持倉明細表格（兩策略通用）。"""
    pos_rows = ""
    for p in sorted(state.positions, key=lambda x: -x.market_value):
        weight  = p.market_value / state.nav * 100 if state.nav > 0 else 0
        in_port = p.symbol in state.top10
        pl_cls  = _color_cls(p.unrealized_pl)
        badge   = (f'<span class="text-xs bg-emerald-700 text-white '
                   f'px-1.5 py-0.5 rounded ml-1">✓</span>') if in_port else ""
        # 整股顯示（qty 固定為整數）
        qty_str = f"{int(p.qty):,}"
        pos_rows += f"""
        <tr class="border-b border-slate-700/60 hover:bg-slate-700/30 transition-colors">
          <td class="py-2 px-3 font-mono font-bold text-sky-300">
            {p.symbol}{badge}
          </td>
          <td class="py-2 px-3 text-right">{qty_str}</td>
          <td class="py-2 px-3 text-right text-slate-400">{_fmt_usd(p.avg_entry_price)}</td>
          <td class="py-2 px-3 text-right">{_fmt_usd(p.current_price)}</td>
          <td class="py-2 px-3 text-right font-semibold">{_fmt_usd(p.market_value)}</td>
          <td class="py-2 px-3 text-right {pl_cls} font-semibold">{_fmt_usd(p.unrealized_pl)}</td>
          <td class="py-2 px-3 text-right {pl_cls}">{_fmt_pct(p.unrealized_plpc * 100)}</td>
          <td class="py-2 px-3 text-right">
            <div class="flex items-center gap-1.5 justify-end">
              <span class="text-slate-300">{weight:.1f}%</span>
              <div class="w-10 h-1.5 bg-slate-600 rounded-full overflow-hidden">
                <div class="h-full rounded-full"
                     style="width:{min(weight * 4, 100):.0f}%;
                            background:{cfg.accent_color}"></div>
              </div>
            </div>
          </td>
        </tr>"""

    return f"""
  <div class="card mb-6">
    <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-4">
      持倉明細（{len(state.positions)} 檔，<span class="text-emerald-400">✓</span> = 組合內）
    </h2>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-slate-500 uppercase border-b border-slate-700">
            <th class="py-2 px-3 text-left">股票</th>
            <th class="py-2 px-3 text-right">股數</th>
            <th class="py-2 px-3 text-right">均價</th>
            <th class="py-2 px-3 text-right">現價</th>
            <th class="py-2 px-3 text-right">市值</th>
            <th class="py-2 px-3 text-right">損益</th>
            <th class="py-2 px-3 text-right">損益%</th>
            <th class="py-2 px-3 text-right">權重</th>
          </tr>
        </thead>
        <tbody>{pos_rows}</tbody>
      </table>
    </div>
  </div>"""


def _mcap_ranking_html(state: PortfolioState) -> str:
    """市值排名表格（TOP10 專用，由 show_mcap_ranking 控制）。"""
    rank_rows = ""
    for i, rd in enumerate(state.ranked_stocks[:15]):
        in_top = rd["symbol"] in state.top10
        row_cls = "bg-emerald-900/25" if in_top else ""
        badge   = ('<span class="text-xs bg-emerald-700 text-white '
                   'px-1.5 py-0.5 rounded ml-1">持有</span>') if in_top else ""
        shares_str = (f"{rd['shares_outstanding']/1e9:.2f}B"
                      if rd.get("shares_outstanding") else "—")
        mcap_str   = f"${rd['market_cap']/1e12:.2f}T"
        rank_rows += f"""
        <tr class="border-b border-slate-700/60 {row_cls}">
          <td class="py-2 px-3 text-slate-400 text-center">{i+1}</td>
          <td class="py-2 px-3 font-mono font-bold text-sky-300">{rd['symbol']}{badge}</td>
          <td class="py-2 px-3 text-right">{_fmt_usd(rd['close_price'])}</td>
          <td class="py-2 px-3 text-right text-slate-400">{shares_str}</td>
          <td class="py-2 px-3 text-right font-semibold">{mcap_str}</td>
        </tr>"""

    return f"""
  <div class="card mb-6">
    <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-4">
      今日市值排名（前15名，<span class="text-emerald-400">綠底</span> = 持有）
    </h2>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-slate-500 uppercase border-b border-slate-700">
            <th class="py-2 px-3 text-center">排名</th>
            <th class="py-2 px-3 text-left">股票</th>
            <th class="py-2 px-3 text-right">收盤價</th>
            <th class="py-2 px-3 text-right">流通股數</th>
            <th class="py-2 px-3 text-right">市值（兆）</th>
          </tr>
        </thead>
        <tbody>{rank_rows}</tbody>
      </table>
    </div>
  </div>"""


def _trade_log_html(hist_arr: list, cfg: DashboardConfig) -> str:
    log_rows = ""
    for h in reversed(hist_arr[-10:]):
        portfolio_str = ", ".join(h.get("top10", []))
        cnt      = h.get("trades_count", 0)
        trade_str= f"{cnt} 筆" if cnt > 0 else "無異動"
        log_rows += f"""
        <tr class="border-b border-slate-700/60">
          <td class="py-2 px-3 font-mono text-slate-300">{h['date']}</td>
          <td class="py-2 px-3 text-right font-semibold">{_fmt_usd(h['nav'])}</td>
          <td class="py-2 px-3 text-center">{trade_str}</td>
          <td class="py-2 px-3 text-slate-400 text-xs">{portfolio_str}</td>
        </tr>"""

    return f"""
  <div class="card">
    <h2 class="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-4">
      最近交易日誌
    </h2>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-slate-500 uppercase border-b border-slate-700">
            <th class="py-2 px-3 text-left">日期</th>
            <th class="py-2 px-3 text-right">NAV</th>
            <th class="py-2 px-3 text-center">交易</th>
            <th class="py-2 px-3 text-left">{cfg.portfolio_label}</th>
          </tr>
        </thead>
        <tbody>{log_rows}</tbody>
      </table>
    </div>
  </div>"""


# ══════════════════════════════════════════════════════════════════════════════
#  主要生成函式
# ══════════════════════════════════════════════════════════════════════════════

def generate(
    state: PortfolioState,
    output_path: Path = OUTPUT_PATH,
    history_path: Path = HISTORY_PATH,
    config: Optional[DashboardConfig] = None,
    extra_sections_html: str = "",
) -> None:
    """
    生成統一格式的 dashboard.html。

    Parameters
    ----------
    state               : 最新持倉快照
    output_path         : HTML 輸出路徑
    history_path        : portfolio_state_history.json 路徑
    config              : 策略設定（預設 TOP10_CONFIG）
    extra_sections_html : 策略特有 HTML 區塊（插入於持倉表與交易日誌之間）
    """
    cfg      = config or TOP10_CONFIG
    history  = _load_history(history_path)
    hist_arr = history.get("history", [])
    init_nav = history.get("initial_nav", state.nav)

    updated_tw = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M 台灣時間")

    # ── 各區塊 HTML ───────────────────────────────────────────────────────────
    bench            = _get_benchmark_drawdown_365()
    kpi_html         = _kpi_cards_html(state, history, cfg)
    nav_chart_html   = _nav_chart_html(hist_arr, cfg, init_nav)
    dd_chart_html    = _drawdown_chart_html(hist_arr, bench, cfg)
    holdings_html    = _holdings_table_html(state, cfg)
    mcap_html        = _mcap_ranking_html(state) if cfg.show_mcap_ranking else ""
    log_html         = _trade_log_html(hist_arr, cfg)
    dropdown_html    = _account_dropdown_html(cfg)
    subtitle_html    = (f'<p class="text-slate-500 text-xs mt-1">{cfg.subtitle}</p>'
                        if cfg.subtitle else "")

    # ── 組合 HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{cfg.title} — 帳戶 #{cfg.account_id}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    body {{ background: #0f172a; }}
    .card {{
      background: #1e293b;
      border-radius: 0.75rem;
      padding: 1.25rem;
    }}
  </style>
</head>
<body class="text-slate-200 min-h-screen p-4 md:p-8">

  <!-- Header -->
  <div class="mb-6">
    <div class="flex items-start justify-between flex-wrap gap-3">
      <!-- 左：標題 + 副標題 -->
      <div>
        <h1 class="text-2xl font-bold text-white">{cfg.title}</h1>
        {subtitle_html}
      </div>
      <!-- 右：帳戶選單 + 更新時間 -->
      <div class="flex items-center gap-3 flex-wrap justify-end">
        {dropdown_html}
        <span class="text-xs text-slate-500 whitespace-nowrap">{updated_tw}</span>
      </div>
    </div>
  </div>

  <!-- KPI Cards -->
  {kpi_html}

  <!-- NAV 歷史圖 -->
  {nav_chart_html}

  <!-- 回撤對比圖 -->
  {dd_chart_html}

  <!-- 持倉表 -->
  {holdings_html}

  <!-- 市值排名（TOP10 專用）-->
  {mcap_html}

  <!-- 策略特有區塊（由各策略的 dashboard_xxx.py 注入）-->
  {extra_sections_html}

  <!-- 交易日誌 -->
  {log_html}

</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Dashboard 已生成：%s", output_path)
