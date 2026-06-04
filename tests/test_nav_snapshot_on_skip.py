"""非換股日仍更新 NAV 快照（每日報告新鮮）。對應使用者回報：月度帳戶每日報告變舊。"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import runner


# ── 決策：何時要在守門擋下時仍存快照 ─────────────────────────────────────────
def test_frequency_skip_snapshots():
    assert runner.should_snapshot_on_skip("not_first_trading_day_of_month", dry_run=False) is True
    assert runner.should_snapshot_on_skip("not_weekly_day_FRI", dry_run=False) is True


def test_non_trading_day_no_snapshot():
    assert runner.should_snapshot_on_skip("non_trading_day", dry_run=False) is False


def test_dry_run_no_snapshot():
    assert runner.should_snapshot_on_skip("not_first_trading_day_of_month", dry_run=True) is False


# ── 快照內容：更新日期/NAV、保留上次選股、不交易 ───────────────────────────
class _Client:
    def get_account_nav(self): return (12345.67, 100.0)
    def get_current_positions(self): return [{"symbol": "AAPL", "qty": 3}]


def test_snapshot_updates_date_keeps_picks(tmp_path):
    # 上次 state：6/2、有 top10/排名
    prev = {"date": "2026-06-02", "nav": 11111.0, "cash": 50.0,
            "top10": ["NVDA", "AAPL"], "positions": [], "orders_executed": [],
            "ranked_stocks": [{"symbol": "NVDA", "rank": 1}]}
    (tmp_path / "portfolio_state.json").write_text(json.dumps(prev))
    import logging
    runner._save_nav_snapshot(_Client(), tmp_path, __import__("datetime").date(2026, 6, 3),
                              logging.getLogger("t"))
    new = json.loads((tmp_path / "portfolio_state.json").read_text())
    assert new["date"] == "2026-06-03"          # 日期更新到今天
    assert new["nav"] == 12345.67               # NAV 更新
    assert new["top10"] == ["NVDA", "AAPL"]     # 選股保留（非換股日不變）
    assert new["orders_executed"] == []         # 沒有交易
    assert new["ranked_stocks"]                 # 排名保留
    # history 也追加了今天
    hist = json.loads((tmp_path / "portfolio_state_history.json").read_text())
    h = hist.get("history") or hist
    assert h[-1]["date"] == "2026-06-03"
