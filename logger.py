"""
logger.py — README.md 交易日誌更新
每日執行結束後追加一行至 README.md 的 Markdown 表格。
防重複：相同日期再次執行時更新而非重複追加。
"""
import logging
import re
from pathlib import Path

from portfolio import PortfolioState, RebalanceOrder

logger = logging.getLogger(__name__)

README_PATH     = Path(__file__).parent / "README.md"
LOG_START_TAG   = "<!-- TRADING_LOG_START -->"
LOG_END_TAG     = "<!-- TRADING_LOG_END -->"
TABLE_HEADER    = (
    "| 日期 | NAV (USD) | 執行交易 | 前10名持股 | 備註 |\n"
    "|------|-----------|---------|-----------|------|\n"
)


# ── 格式化函式 ────────────────────────────────────────────────────────────────

def _format_trades(orders: list[RebalanceOrder]) -> str:
    """將訂單清單壓縮成單行文字摘要。"""
    if not orders:
        return "無交易（持倉無異動）"
    parts = []
    for o in orders:
        qty_str = f"{o.qty:.4f}".rstrip("0").rstrip(".")
        parts.append(f"{'賣出' if o.action == 'SELL' else '買入'} {o.symbol}×{qty_str}")
    # 最多顯示 6 筆，超過折疊
    if len(parts) <= 6:
        return "; ".join(parts)
    return "; ".join(parts[:6]) + f"… 共{len(parts)}筆"


def _format_nav(nav: float) -> str:
    return f"${nav:,.2f}"


def format_log_row(state: PortfolioState, note: str = "") -> str:
    """將 PortfolioState 格式化為單行 Markdown 表格列（不含換行）。"""
    top10_str  = ",".join(state.top10)
    trades_str = _format_trades(state.orders_executed)
    nav_str    = _format_nav(state.nav)
    note_str   = note or ("首次建倉" if not state.orders_executed else "—")
    # 自動偵測首次建倉（全部為 cash_deployment）
    if state.orders_executed and all(
        o.reason == "cash_deployment" for o in state.orders_executed
    ):
        note_str = "首次建倉"

    return (
        f"| {state.date} | {nav_str} | {trades_str} | {top10_str} | {note_str} |"
    )


# ── README.md 更新 ────────────────────────────────────────────────────────────

def _ensure_log_section(content: str) -> str:
    """若 README.md 尚無日誌區塊，在末尾新增。"""
    if LOG_START_TAG not in content:
        logger.info("README.md 無日誌區塊，自動建立")
        section = (
            "\n\n## 交易日誌\n\n"
            f"{LOG_START_TAG}\n"
            f"{TABLE_HEADER}"
            f"{LOG_END_TAG}\n"
        )
        content = content.rstrip() + section
    return content


def read_existing_log(readme_path: Path = README_PATH) -> list[str]:
    """讀取現有日誌列（不含表頭）。"""
    if not readme_path.exists():
        return []
    text = readme_path.read_text(encoding="utf-8")
    start = text.find(LOG_START_TAG)
    end   = text.find(LOG_END_TAG)
    if start == -1 or end == -1:
        return []
    block = text[start + len(LOG_START_TAG): end]
    rows  = [line for line in block.splitlines()
             if line.startswith("|") and not line.startswith("| 日期") and "---" not in line]
    return rows


def append_log_entry(
    state: PortfolioState,
    note: str = "",
    readme_path: Path = README_PATH,
) -> None:
    """
    在 README.md 的日誌表格中追加（或更新）今日記錄。
    若相同日期已存在，以新資料覆蓋（冪等）。
    """
    # 讀取原始內容（若不存在則建立骨架）
    if readme_path.exists():
        content = readme_path.read_text(encoding="utf-8")
    else:
        content = _build_initial_readme()

    content = _ensure_log_section(content)

    new_row = format_log_row(state, note)

    # 取出標記之間的內容
    start_idx = content.find(LOG_START_TAG) + len(LOG_START_TAG)
    end_idx   = content.find(LOG_END_TAG)

    inner = content[start_idx:end_idx]

    # 找出現有的各行
    lines = inner.splitlines(keepends=True)

    # 保留表頭；移除相同日期的舊記錄
    new_lines = []
    replaced  = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"| {state.date}"):
            new_lines.append(new_row + "\n")
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        # 追加至表格末尾（在 end tag 前）
        new_lines.append(new_row + "\n")

    new_inner = "".join(new_lines)
    new_content = (
        content[:start_idx]
        + new_inner
        + content[end_idx:]
    )

    readme_path.write_text(new_content, encoding="utf-8")
    action = "更新" if replaced else "追加"
    logger.info("README.md 日誌已%s：%s  NAV=%s", action, state.date, _format_nav(state.nav))


def _build_initial_readme() -> str:
    """建立初始 README.md 骨架。"""
    return """# 🤖 科技股自動再平衡系統

每個美股交易日收盤後，自動依市值選出前 10 大科技股並以等權重再平衡持倉。

- **策略**：等權重（10% × 10 檔），±2% 容忍帶
- **資料**：Alpaca API（收盤價）× SEC EDGAR（流通股數）
- **執行**：GitHub Actions，每日 UTC 15:15（台灣時間 23:15）
- **Dashboard**：[查看即時持倉](dashboard.html)

## 最新持倉

> 詳見 [dashboard.html](dashboard.html)（由 GitHub Pages 提供）

## 交易日誌

"""
