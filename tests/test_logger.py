"""tests/test_logger.py — README.md 日誌更新測試"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from portfolio import PortfolioState, RebalanceOrder, Position
from logger import (
    append_log_entry,
    format_log_row,
    read_existing_log,
    LOG_START_TAG,
    LOG_END_TAG,
)


# ── 工具 ──────────────────────────────────────────────────────────────────────
def make_state(dt="2026-05-05", nav=100000.0, cash=500.0,
               orders=None, top10=None) -> PortfolioState:
    return PortfolioState(
        date=dt, nav=nav, cash=cash,
        positions=[],
        top10=top10 or ["AAPL","MSFT","NVDA","GOOGL","AMZN",
                        "META","TSM","AVGO","ORCL","V"],
        orders_executed=orders or [],
    )


def make_readme_with_table(rows: list[str] = None) -> str:
    rows_str = "\n".join(rows or [])
    return (
        "# Test\n\n## 交易日誌\n\n"
        f"{LOG_START_TAG}\n"
        "| 日期 | NAV (USD) | 執行交易 | 前10名持股 | 備註 |\n"
        "|------|-----------|---------|-----------|------|\n"
        f"{rows_str}\n"
        f"{LOG_END_TAG}\n"
    )


# ── 格式化測試 ────────────────────────────────────────────────────────────────
class TestFormatLogRow:
    def test_contains_date(self):
        state = make_state(dt="2026-05-05")
        row   = format_log_row(state)
        assert "2026-05-05" in row

    def test_contains_nav(self):
        state = make_state(nav=102345.67)
        row   = format_log_row(state)
        assert "102,345.67" in row

    def test_no_orders_shows_no_trade(self):
        state = make_state(orders=[])
        row   = format_log_row(state)
        assert "無交易" in row

    def test_with_sell_order(self):
        orders = [RebalanceOrder("INTC", "SELL", 100.0, "exit_top10", 2500.0)]
        state  = make_state(orders=orders)
        row    = format_log_row(state)
        assert "賣出" in row
        assert "INTC" in row

    def test_with_buy_order(self):
        orders = [RebalanceOrder("NOW", "BUY", 8.5, "new_entrant", 1700.0)]
        state  = make_state(orders=orders)
        row    = format_log_row(state)
        assert "買入" in row
        assert "NOW" in row

    def test_cash_deployment_flagged_as_first_build(self):
        """全部為 cash_deployment → 備註應顯示 '首次建倉'"""
        orders = [
            RebalanceOrder(s, "BUY", 10.0, "cash_deployment", 1000.0)
            for s in ["AAPL","MSFT","NVDA","GOOGL","AMZN",
                      "META","TSM","AVGO","ORCL","V"]
        ]
        state = make_state(orders=orders)
        row   = format_log_row(state)
        assert "首次建倉" in row

    def test_pipe_delimited_format(self):
        state = make_state()
        row   = format_log_row(state)
        assert row.startswith("|")
        assert row.count("|") >= 5  # 至少 5 個欄位分隔符


# ── README.md 追加測試 ────────────────────────────────────────────────────────
class TestAppendLogEntry:
    def test_creates_table_if_not_exists(self):
        """README.md 無日誌區塊時，應自動建立"""
        state = make_state()
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write("# My Repo\n\n## Introduction\n\nSome text.\n")
            tmp = Path(f.name)
        append_log_entry(state, readme_path=tmp)
        content = tmp.read_text(encoding="utf-8")
        tmp.unlink()
        assert LOG_START_TAG in content
        assert LOG_END_TAG   in content
        assert "2026-05-05"  in content

    def test_appends_new_row(self):
        """新日期應追加為新行"""
        state = make_state(dt="2026-05-06")
        existing_row = "| 2026-05-05 | $100,000.00 | 無交易（持倉無異動） | AAPL,MSFT | — |"
        content = make_readme_with_table([existing_row])
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp = Path(f.name)
        append_log_entry(state, readme_path=tmp)
        rows = read_existing_log(tmp)
        tmp.unlink()
        dates = [r.split("|")[1].strip() for r in rows]
        assert "2026-05-05" in dates
        assert "2026-05-06" in dates

    def test_updates_existing_row_not_duplicate(self):
        """相同日期再次執行 → 更新而非重複追加（冪等）"""
        state = make_state(dt="2026-05-05", nav=101000.0)
        existing_row = "| 2026-05-05 | $100,000.00 | 無交易（持倉無異動） | AAPL,MSFT | — |"
        content = make_readme_with_table([existing_row])
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp = Path(f.name)
        append_log_entry(state, readme_path=tmp)
        rows = read_existing_log(tmp)
        tmp.unlink()
        dates = [r.split("|")[1].strip() for r in rows]
        # 同日期只應出現一次
        assert dates.count("2026-05-05") == 1
        # NAV 應更新為新值
        updated_row = next(r for r in rows if "2026-05-05" in r)
        assert "101,000.00" in updated_row

    def test_creates_readme_if_not_exists(self):
        """README.md 不存在時，應自動建立"""
        state = make_state()
        tmp   = Path(tempfile.mktemp(suffix=".md"))
        assert not tmp.exists()
        append_log_entry(state, readme_path=tmp)
        assert tmp.exists()
        content = tmp.read_text(encoding="utf-8")
        tmp.unlink()
        assert "2026-05-05" in content

    def test_read_existing_log_empty(self):
        """無日誌時回傳空清單"""
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                         delete=False, encoding="utf-8") as f:
            f.write("# Test\n\nNo log here.\n")
            tmp = Path(f.name)
        rows = read_existing_log(tmp)
        tmp.unlink()
        assert rows == []
