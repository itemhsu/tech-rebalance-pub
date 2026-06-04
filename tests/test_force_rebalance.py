"""FORCE_REBALANCE 覆蓋頻率守門（手動再平衡 / 驗證下單路徑）。"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import runner


def test_no_force_passes_through(monkeypatch):
    monkeypatch.delenv("FORCE_REBALANCE", raising=False)
    assert runner.apply_force_override(False, "not_first_trading_day_of_month") == \
        (False, False, "not_first_trading_day_of_month")


def test_force_overrides_blocked_gate(monkeypatch):
    monkeypatch.setenv("FORCE_REBALANCE", "true")
    forced, run, trig = runner.apply_force_override(False, "not_first_trading_day_of_month")
    assert forced is True and run is True
    assert "forced" in trig and "not_first" in trig


def test_force_does_not_affect_already_passing(monkeypatch):
    monkeypatch.setenv("FORCE_REBALANCE", "true")
    # 守門本來就通過 → 不標記為 forced（避免誤導）
    assert runner.apply_force_override(True, "monthly_first_day") == \
        (False, True, "monthly_first_day")
