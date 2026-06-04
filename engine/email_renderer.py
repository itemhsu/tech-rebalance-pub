"""
engine/email_renderer.py — 從 data.json 生成電子郵件 HTML

用法：
    from engine.email_renderer import render
    subject, html = render(data_path, strategy_path)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 共用樣式常數 ──────────────────────────────────────────────────────────────
_BG       = "#ffffff"
_BG_CARD  = "#f8fafc"
_TEXT     = "#1e293b"
_MUTED    = "#64748b"
_BORDER   = "#e2e8f0"
_GREEN    = "#16a34a"
_RED      = "#dc2626"
_FONT     = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif"


def _color(v: float) -> str:
    return _GREEN if v >= 0 else _RED


def _pct(v: float) -> str:
    return f"{'+'if v>=0 else ''}{v:.2f}%"


def _money(v: float) -> str:
    sign = "−" if v < 0 else ""
    return f"${sign}{abs(v):,.2f}"


# ══════════════════════════════════════════════════════════════════════════════
#  公開入口
# ══════════════════════════════════════════════════════════════════════════════

def render(data_path: Path, strategy_path: Path) -> tuple[str, str]:
    """
    從 data.json + strategy.json 生成電子郵件。
    回傳 (subject, html_body)。
    """
    data     = json.loads(data_path.read_text(encoding="utf-8"))
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    sections = strategy["email"]["sections"]
    subject  = data["email"]["subject"]
    html     = _build_html(data, sections)
    return subject, html


def render_from_dict(data: dict, strategy: dict) -> tuple[str, str]:
    """dict 版本（測試用，不需讀檔）。"""
    sections = strategy["email"]["sections"]
    subject  = data["email"]["subject"]
    html     = _build_html(data, sections)
    return subject, html


# ══════════════════════════════════════════════════════════════════════════════
#  核心渲染
# ══════════════════════════════════════════════════════════════════════════════

def _build_html(d: dict, sections: list[str]) -> str:
    accent = d["meta"].get("accent_color", "#38bdf8")

    renderers = {
        "header":           lambda: _section_header(d, accent),
        "kpi":              lambda: _section_kpi(d, accent),
        "strategy_card":    lambda: _section_strategy_card(d, accent),
        "portfolio_badges": lambda: _section_badges(d, accent),
        "positions_table":  lambda: _section_positions(d),
        "rankings":         lambda: _section_rankings(d),
        "today_events":     lambda: _section_events(d),
        "harvest_plan":     lambda: _section_harvest(d),
        "trades":           lambda: _section_trades(d),
        "cta":              lambda: _section_cta(d, accent),
        "strategy_history": lambda: _section_strategy_history(d),
        "footer":           lambda: _section_footer(d),
    }

    body = _section_stale_warning(d)  # 今日未更新紅色橫幅（永遠最頂，若有）
    body += _section_order_alerts(d)   # 訂單異常紅色橫幅（若有）
    body += _section_upstream_notice(d)   # 落後上游柔性提示（若有）
    for sec in sections:
        fn = renderers.get(sec)
        if fn is None:
            logger.debug("未知 section 跳過：%s", sec)
            continue
        html = fn()
        if html:
            body += html

    return _wrap(body, accent)


def _section_order_alerts(d: dict) -> str:
    alerts = d.get("order_alerts") or []
    if not alerts:
        return ""
    items = ""
    for a in alerts:
        icon = "❌ 被拒" if a.get("kind") == "rejected" else "⏳ 未結"
        items += (f'<div style="font-size:12px;margin:2px 0">{icon} '
                  f'<b>{a.get("symbol","")}</b> {a.get("action","")} —— '
                  f'{a.get("detail","")}</div>')
    return (f'<tr><td style="padding:14px 32px;background:#7f1d1d;color:#fecaca">'
            f'<div style="font-size:13px;font-weight:700;margin-bottom:4px">'
            f'⚠️ 訂單異常（{len(alerts)} 筆，請查 Dashboard 日誌）</div>{items}</td></tr>')


def _section_stale_warning(d: dict) -> str:
    w = d.get("stale_warning")
    if not w:
        return ""
    return (f'<tr><td style="padding:14px 32px;background:#7f1d1d;color:#fecaca;'
            f'font-size:13px;font-weight:700">{w}</td></tr>')


def _section_upstream_notice(d: dict) -> str:
    notice = d.get("upstream_notice")
    if not notice:
        return ""
    return (f'<tr><td style="padding:10px 32px;background:#1e3a5f;color:#cfe3fb;'
            f'font-size:12px">{notice}</td></tr>')


# ══════════════════════════════════════════════════════════════════════════════
#  外層容器
# ══════════════════════════════════════════════════════════════════════════════

def _wrap(body: str, accent: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>每日報告</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;{_FONT}">
<table width="100%" cellpadding="0" cellspacing="0">
  <tr><td align="center" style="padding:24px 16px">
    <table width="600" cellpadding="0" cellspacing="0"
           style="max-width:600px;width:100%;background:{_BG};
                  border-radius:12px;overflow:hidden;
                  box-shadow:0 1px 3px rgba(0,0,0,.1)">
      {body}
      <tr><td style="height:4px;background:{accent}"></td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  Header
# ══════════════════════════════════════════════════════════════════════════════

def _section_header(d: dict, accent: str) -> str:
    meta   = d["meta"]
    status = meta.get("strategy_status", "active")
    dry    = meta.get("dry_run", False)

    if dry:
        badge_label, badge_bg, badge_fg = "DRY RUN", "#fef3c7", "#d97706"
    else:
        badge_map = {
            "active":   ("LIVE",    "#dcfce7", "#16a34a"),
            "paused":   ("PAUSED",  "#fef9c3", "#ca8a04"),
            "switched": ("SWITCHED","#e0e7ff", "#4f46e5"),
        }
        badge_label, badge_bg, badge_fg = badge_map.get(status, ("LIVE", "#dcfce7", "#16a34a"))

    strategy_name = d.get("strategy_name") or meta.get("strategy", "").upper()
    return f"""
    <tr><td style="height:4px;background:{accent}"></td></tr>
    <tr><td style="padding:24px 32px 20px;border-bottom:1px solid {_BORDER}">
      <table width="100%" cellpadding="0" cellspacing="0"><tr>
        <td>
          <div style="font-size:18px;font-weight:700;color:{_TEXT}">{strategy_name}</div>
          <div style="font-size:13px;color:{_MUTED};margin-top:2px">
            帳戶 #{meta['account_id']} · {meta['trading_date']}
          </div>
        </td>
        <td align="right">
          <span style="background:{badge_bg};color:{badge_fg};
                       font-size:11px;font-weight:700;
                       padding:3px 10px;border-radius:20px;
                       letter-spacing:.5px">{badge_label}</span>
        </td>
      </tr></table>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  KPI 卡片
# ══════════════════════════════════════════════════════════════════════════════

def _section_kpi(d: dict, accent: str) -> str:
    s = d["summary"]
    tc  = s["today_change"]
    tcp = s["today_change_pct"]
    twr = s["total_return_pct_twr"]
    ytd = s.get("ytd_return_pct")

    def card(title: str, value: str, sub: str = "", sub_color: str = _MUTED) -> str:
        sub_html = (f"<div style='font-size:12px;color:{sub_color};margin-top:2px'>{sub}</div>"
                    if sub else "")
        return f"""
        <td width="50%" style="padding:12px">
          <div style="background:{_BG_CARD};border-radius:8px;padding:14px 16px">
            <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                        letter-spacing:.5px;margin-bottom:6px">{title}</div>
            <div style="font-size:20px;font-weight:700;color:{_TEXT}">{value}</div>
            {sub_html}
          </div>
        </td>"""

    return f"""
    <tr><td style="padding:20px 20px 8px">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          {card("NAV 淨值", f"${s['nav']:,.0f}", f"現金 ${s['cash']:,.0f}")}
          {card("今日損益", _pct(tcp), _money(tc), sub_color=_color(tc))}
        </tr>
        <tr>
          {card("總報酬 TWR", _pct(twr),
                f"自 {s['inception_date']} 起",
                sub_color=_color(twr))}
          {card("年初至今 YTD",
                _pct(ytd) if ytd is not None else "—",
                sub_color=_color(ytd) if ytd is not None else _MUTED)}
        </tr>
      </table>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  策略描述卡片
# ══════════════════════════════════════════════════════════════════════════════

def _section_strategy_card(d: dict, accent: str) -> str:
    sc = d.get("strategy_card")
    if not sc:
        return ""

    # 標籤
    tags_html = "".join(
        f'<span style="display:inline-block;background:{accent}22;color:{accent};'
        f'border:1px solid {accent}44;border-radius:12px;font-size:11px;'
        f'font-weight:600;padding:2px 10px;margin:2px 4px 2px 0">{t}</span>'
        for t in sc.get("tags", [])
    )

    # 基本資訊行
    info_rows = [
        ("宇宙",   sc.get("universe_summary",    "")),
        ("選股",   sc.get("selection_summary",   "")),
        ("再平衡", sc.get("rebalancing_summary", "")),
        ("基準",   sc.get("benchmark",           "")),
    ]
    info_html = "".join(
        f'<tr>'
        f'<td style="padding:5px 12px 5px 0;font-size:12px;color:{_MUTED};white-space:nowrap;'
        f'vertical-align:top;font-weight:600">{label}</td>'
        f'<td style="padding:5px 0;font-size:13px;color:{_TEXT}">{val}</td>'
        f'</tr>'
        for label, val in info_rows if val
    )

    # 風控亮點
    risk_items = sc.get("risk_highlights", [])
    risk_html = ""
    if risk_items:
        bullets = "".join(
            f'<span style="display:inline-block;background:#fef3c7;color:#92400e;'
            f'border-radius:8px;font-size:11px;padding:2px 8px;margin:2px 4px 2px 0">'
            f'⚠ {item}</span>'
            for item in risk_items
        )
        risk_html = f'<div style="margin-top:8px">{bullets}</div>'

    # 排名因子（v3 only）
    factors = sc.get("ranking_factors", [])
    factors_html = ""
    if factors:
        factor_items = "".join(
            f'<tr>'
            f'<td style="padding:4px 8px 4px 0;font-size:12px;color:{_TEXT}">'
            f'{f["direction"]} {f["name"]}</td>'
            f'<td style="padding:4px 0;font-size:12px;color:{accent};font-weight:700;'
            f'text-align:right">{f["weight"]}</td>'
            f'</tr>'
            for f in factors[:6]
        )
        factors_html = f'''
        <div style="margin-top:14px">
          <div style="font-size:12px;font-weight:700;color:{_MUTED};margin-bottom:6px;
                      text-transform:uppercase;letter-spacing:.06em">排名因子</div>
          <table style="width:100%;border-collapse:collapse">{factor_items}</table>
        </div>'''

    # 過濾條件（v3 only）
    fs = sc.get("filter_summary", {})
    filters_html = ""
    if fs:
        def _filter_block(title: str, items: list[str]) -> str:
            chips = "".join(
                f'<span style="display:inline-block;background:#f1f5f9;color:{_TEXT};'
                f'border:1px solid {_BORDER};border-radius:6px;font-size:11px;'
                f'padding:2px 8px;margin:2px 4px 2px 0">{c}</span>'
                for c in items
            )
            return (
                f'<div style="margin-top:10px">'
                f'<span style="font-size:11px;font-weight:700;color:{_MUTED};'
                f'text-transform:uppercase;letter-spacing:.05em">{title}</span>'
                f'<div style="margin-top:4px">{chips}</div>'
                f'</div>'
            )
        if fs.get("fundamental"):
            filters_html += _filter_block("基本面篩選", fs["fundamental"])
        if fs.get("technical"):
            filters_html += _filter_block("技術面篩選", fs["technical"])

    return f'''
<div style="background:{_BG_CARD};border:1px solid {_BORDER};border-radius:12px;
            padding:20px 24px;margin:16px 0;{_FONT}">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;
              flex-wrap:wrap;gap:8px;margin-bottom:12px">
    <div>
      <div style="font-size:16px;font-weight:700;color:{_TEXT}">{sc.get("name","")}</div>
      <div style="font-size:13px;color:{_MUTED};margin-top:4px;line-height:1.5">
        {sc.get("description","")}
      </div>
    </div>
  </div>
  {f'<div style="margin-bottom:10px">{tags_html}</div>' if tags_html else ""}
  <table style="border-collapse:collapse;width:100%">{info_html}</table>
  {risk_html}
  {factors_html}
  {filters_html}
</div>
'''


# ══════════════════════════════════════════════════════════════════════════════
#  組合 Badges
# ══════════════════════════════════════════════════════════════════════════════

def _section_badges(d: dict, accent: str) -> str:
    p = d["portfolio"]
    badges = "".join(
        f'<span style="display:inline-block;background:{accent}22;color:{accent};'
        f'border:1px solid {accent}55;font-size:12px;font-weight:600;'
        f'padding:3px 10px;border-radius:20px;margin:3px">{s}</span>'
        for s in p["symbols"]
    )
    return f"""
    <tr><td style="padding:8px 32px 16px">
      <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">
        {p['label']}（{len(p['symbols'])} 檔）
      </div>
      <div>{badges}</div>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  持倉表
# ══════════════════════════════════════════════════════════════════════════════

def _section_positions(d: dict) -> str:
    rows = ""
    for i, p in enumerate(d["positions"]):
        bg   = "#f0fdf4" if p["in_portfolio"] else _BG
        mark = "●" if p["in_portfolio"] else ""
        plc  = _color(p["unrealized_pl"])
        rows += f"""
        <tr style="background:{bg};border-bottom:1px solid {_BORDER}">
          <td style="padding:8px 12px;font-size:13px;color:{_MUTED}">{i+1}</td>
          <td style="padding:8px 12px;font-weight:700;font-size:13px;
                     color:#0369a1;font-family:monospace">
            {p['symbol']}
            <span style="color:{_GREEN};font-size:10px">{mark}</span>
          </td>
          <td style="padding:8px 12px;text-align:right;font-size:13px;color:{_MUTED}">
            {int(p['qty'])} 股</td>
          <td style="padding:8px 12px;text-align:right;font-size:13px">
            ${p['current_price']:,.2f}</td>
          <td style="padding:8px 12px;text-align:right;font-size:13px">
            {p['weight']:.1f}%</td>
          <td style="padding:8px 12px;text-align:right;font-size:13px;
                     color:{plc};font-weight:600">
            {_pct(p['unrealized_plpc'])}</td>
          <td style="padding:8px 12px;text-align:right;font-size:12px;color:{plc}">
            {_money(p['unrealized_pl'])}</td>
        </tr>"""

    if not rows:
        return ""

    return f"""
    <tr><td style="padding:16px 32px 0">
      <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">
        持倉明細（綠底 = 組合內）
      </div>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid {_BORDER};border-radius:8px;overflow:hidden">
        <thead>
          <tr style="background:{_BG_CARD}">
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:{_MUTED}">#</th>
            <th style="padding:8px 12px;text-align:left;font-size:11px;color:{_MUTED}">股票</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED}">股數</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED}">股價</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED}">權重</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED}">損益%</th>
            <th style="padding:8px 12px;text-align:right;font-size:11px;color:{_MUTED}">損益$</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  Rankings（多型）
# ══════════════════════════════════════════════════════════════════════════════

def _section_rankings(d: dict) -> str:
    r = d["rankings"]
    if r["type"] == "market_cap_list":
        return _rankings_market_cap(r)
    elif r["type"] == "universe_groups":
        return _rankings_universe_groups(r)
    return ""


def _rankings_market_cap(r: dict) -> str:
    rows = ""
    for item in r["items"]:
        mark = "✓" if item["in_portfolio"] else ""
        mark_style = f"color:{_GREEN};font-weight:700" if item["in_portfolio"] else ""
        rows += f"""
        <tr style="border-bottom:1px solid {_BORDER}">
          <td style="padding:6px 12px;font-size:12px;color:{_MUTED}">{item['rank']}</td>
          <td style="padding:6px 12px;font-weight:700;font-family:monospace;
                     font-size:13px;color:#0369a1">
            {item['symbol']}
            <span style="{mark_style};font-size:10px"> {mark}</span>
          </td>
          <td style="padding:6px 12px;text-align:right;font-size:13px">
            ${item['price']:,.2f}</td>
          <td style="padding:6px 12px;text-align:right;font-size:12px;
                     color:{_color(item['change_pct'])}">
            {_pct(item['change_pct'])}</td>
          <td style="padding:6px 12px;text-align:right;font-size:12px;color:{_MUTED}">
            {item['market_cap_b']:.0f}B</td>
        </tr>"""
    return f"""
    <tr><td style="padding:16px 32px 0">
      <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">{r['label']}</div>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid {_BORDER};border-radius:8px;overflow:hidden">
        <tbody>{rows}</tbody>
      </table>
    </td></tr>"""


def _rankings_universe_groups(r: dict) -> str:
    cols = ""
    for group in r["groups"]:
        rows = ""
        for item in group["items"]:
            mark  = "✓" if item["in_portfolio"] else ""
            mc    = f"color:{_GREEN}" if item["in_portfolio"] else ""
            rows += f"""
            <tr style="border-bottom:1px solid {_BORDER}">
              <td style="padding:4px 8px;font-size:11px;color:{_MUTED}">{item['rank']}</td>
              <td style="padding:4px 8px;font-size:12px;font-weight:700;
                         font-family:monospace;color:#0369a1">
                {item['symbol']}
                <span style="{mc}">{mark}</span>
              </td>
              <td style="padding:4px 8px;text-align:right;font-size:11px">
                ${item['price']:,.0f}</td>
              <td style="padding:4px 8px;text-align:right;font-size:11px;
                         color:{_color(item['change_pct'])}">
                {_pct(item['change_pct'])}</td>
            </tr>"""
        cols += f"""
        <td width="33%" valign="top" style="padding:0 6px">
          <div style="font-size:11px;font-weight:600;color:{_MUTED};
                      text-transform:uppercase;letter-spacing:.4px;
                      margin-bottom:6px">{group['label']}</div>
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid {_BORDER};border-radius:6px;overflow:hidden">
            <tbody>{rows}</tbody>
          </table>
        </td>"""

    return f"""
    <tr><td style="padding:16px 32px 0">
      <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">{r['label']}</div>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>{cols}</tr>
      </table>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  今日事件
# ══════════════════════════════════════════════════════════════════════════════

def _section_events(d: dict) -> str:
    today  = d["meta"]["trading_date"]
    events = [e for e in d.get("events", []) if e["date"] == today]
    if not events:
        return ""

    icon_map = {
        "deposit":         ("💰", _GREEN,   "入金"),
        "withdrawal":      ("💸", _RED,     "出金"),
        "strategy_switch": ("🔄", "#7c3aed","策略切換"),
        "strategy_pause":  ("⏸️", "#d97706","策略暫停"),
        "strategy_resume": ("▶️", _GREEN,   "策略恢復"),
    }
    rows = ""
    for e in events:
        icon, color, label = icon_map.get(e["type"], ("📌", _MUTED, e["type"]))
        detail = ""
        if e["type"] in ("deposit", "withdrawal"):
            amt    = e.get("amount", 0)
            sign   = "+" if amt >= 0 else ""
            detail = f" {sign}${abs(amt):,.0f}"
        elif e["type"] == "strategy_switch":
            detail = f" {e.get('from_strategy','?')}→{e.get('to_strategy','?')}"
        note_html = ""
        if e.get("note"):
            note_html = (f"<br><span style='color:{_MUTED};font-size:11px'>"
                         f"{e['note']}</span>")
        rows += f"""
        <tr><td style="padding:8px 12px">
          <span style="font-size:14px">{icon}</span>
          <span style="font-size:13px;font-weight:600;color:{color};margin-left:6px">
            {label}{detail}
          </span>{note_html}
        </td></tr>"""

    return f"""
    <tr><td style="padding:16px 32px 0">
      <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">今日帳戶事件</div>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid {_BORDER};border-radius:8px;overflow:hidden;
                    background:{_BG_CARD}">
        <tbody>{rows}</tbody>
      </table>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  稅務收割
# ══════════════════════════════════════════════════════════════════════════════

def _section_harvest(d: dict) -> str:
    # harvest_plan 目前在 data.json 之外（由 main.py 另外計算）
    # 若 data.json 未來加入 harvest_plan 欄位，在此渲染
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  今日交易
# ══════════════════════════════════════════════════════════════════════════════

def _section_trades(d: dict) -> str:
    log = d.get("trade_log", [])
    if not log:
        return ""
    today_log = log[0]   # 最新一筆（降序）
    orders    = today_log.get("orders", [])
    count     = today_log.get("trades_count", 0)

    if count == 0:
        return f"""
    <tr><td style="padding:12px 32px 0">
      <div style="font-size:12px;color:{_MUTED}">今日無交易。</div>
    </td></tr>"""

    rows = ""
    for o in orders:
        side_color = _GREEN if o["side"] == "buy" else _RED
        side_label = "買入" if o["side"] == "buy" else "賣出"
        rows += f"""
        <tr style="border-bottom:1px solid {_BORDER}">
          <td style="padding:6px 12px;font-weight:700;font-family:monospace;
                     font-size:13px;color:#0369a1">{o['symbol']}</td>
          <td style="padding:6px 12px;font-size:13px;
                     color:{side_color};font-weight:600">{side_label}</td>
          <td style="padding:6px 12px;text-align:right;font-size:13px">
            {o['qty']:.0f} 股</td>
          <td style="padding:6px 12px;text-align:right;font-size:13px">
            @${o['price']:,.2f}</td>
        </tr>"""

    return f"""
    <tr><td style="padding:16px 32px 0">
      <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">
        今日交易（{count} 筆）
      </div>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid {_BORDER};border-radius:8px;overflow:hidden">
        <tbody>{rows}</tbody>
      </table>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  CTA 按鈕
# ══════════════════════════════════════════════════════════════════════════════

def _section_cta(d: dict, accent: str) -> str:
    url = d["email"]["dashboard_url"]
    account_id = d.get("meta", {}).get("account_id", "1")
    strategy = (d.get("meta", {}).get("strategy") or "top10").lower()

    # 兩個額外連結用同一個 dashboard host
    # 從 dashboard_url 推導 host（容錯：若沒設就用預設）
    import re
    m = re.match(r"(https?://[^/]+)(/[^?#]*)?", url or "")
    host = m.group(1) if m else "https://itemhsu.github.io"
    base_path = "/tech-rebalance-dashboard"

    log_url      = f"{host}{base_path}/log/?account={account_id}"
    backtest_url = f"{host}{base_path}/momentum/?focus={strategy}"

    btn = lambda href, label, color: (
        f'<a href="{href}" style="display:inline-block;background:{color};color:#ffffff;'
        f'font-weight:700;font-size:13px;text-decoration:none;padding:10px 20px;'
        f'border-radius:7px;letter-spacing:.3px;margin:4px;">{label}</a>'
    )
    return f"""
    <tr><td align="center" style="padding:24px 32px 8px 32px">
      {btn(url, "📊 Dashboard", accent)}
      {btn(log_url, "📋 交易日誌", "#06b6d4")}
      {btn(backtest_url, "📈 回測對照", "#a855f7")}
    </td></tr>
    <tr><td align="center" style="padding:0 32px 24px 32px;font-size:10.5px;color:#64748b">
      ｜ Dashboard：最新持股 ｜ 日誌：誰觸發、為何下單 ｜ 回測：歷史績效 ｜
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  策略歷史（帳戶歷經多個策略時的時間軸）
# ══════════════════════════════════════════════════════════════════════════════

def _section_strategy_history(d: dict) -> str:
    hist = d.get("strategy_history") or []
    if len(hist) < 2:
        return ""
    rows = ""
    for seg in hist:
        period = f"{seg.get('from') or '?'} ～ {seg.get('to') or '至今'}"
        rows += f"""
        <tr style="border-bottom:1px solid {_BORDER}">
          <td style="padding:6px 12px;font-size:12px;color:{_MUTED};white-space:nowrap">{period}</td>
          <td style="padding:6px 12px;font-size:13px;font-weight:600;color:{_TEXT}">
            {seg.get('label') or seg.get('strategy','')}</td>
        </tr>"""
    return f"""
    <tr><td style="padding:16px 32px 0">
      <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px">策略歷史（本帳戶歷經的策略）</div>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid {_BORDER};border-radius:8px;overflow:hidden">
        <thead><tr style="background:{_BG_CARD}">
          <th style="padding:8px 12px;text-align:left;font-size:11px;color:{_MUTED}">期間</th>
          <th style="padding:8px 12px;text-align:left;font-size:11px;color:{_MUTED}">策略</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </td></tr>"""


# ══════════════════════════════════════════════════════════════════════════════
#  Footer
# ══════════════════════════════════════════════════════════════════════════════

def _section_footer(d: dict) -> str:
    meta = d["meta"]
    return f"""
    <tr><td style="padding:16px 32px;border-top:1px solid {_BORDER};
                   background:{_BG_CARD}">
      <div style="font-size:11px;color:{_MUTED};text-align:center;line-height:1.8">
        {meta.get('strategy','').upper()} · 帳戶 #{meta['account_id']}<br>
        生成時間：{meta['generated_at']}<br>
        <span style="color:#94a3b8">此為自動生成郵件，請勿回覆</span>
      </div>
    </td></tr>"""
