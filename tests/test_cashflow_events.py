"""入金/出金事件：券商現金流 → cash_flows.json → TWR 事件（入金不算報酬）。

使用者回報（2026-10-07）：mvp_dashboard #3 總報酬 TWR +64.81% 錯誤——6/22 入金 $9,476
被當成報酬。根因：report_generator 把 events 寫死成 []、整個引擎沒人呼叫 get_cash_flows。
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import cashflow                       # noqa: E402
from engine.twr import compute_twr                # noqa: E402
from engine.data_writer import build_summary      # noqa: E402

# 帳戶 #3 真實片段（data/3/portfolio_state_history.json）
_HIST = [
    {"date": "2026-05-18", "nav": 19820.37},
    {"date": "2026-06-18", "nav": 20180.38},
    {"date": "2026-06-22", "nav": 19883.01},   # 入金前最後快照
    {"date": "2026-06-23", "nav": 28787.60},   # 含入金 $9,476.5
    {"date": "2026-10-07", "nav": 32665.40},
]
_DEPOSIT = 9476.53


# ── flows_to_events ──────────────────────────────────────────────────────────
def test_deposit_event_uses_last_nav_before_flow_date():
    flows = [{"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}]
    ev = cashflow.flows_to_events(flows, _HIST)
    assert len(ev) == 1
    e = ev[0]
    assert e["type"] == "deposit" and e["date"] == "2026-06-23"
    assert e["nav_before"] == pytest.approx(19883.01, abs=0.01)
    assert e["nav_after"] == pytest.approx(19883.01 + _DEPOSIT, abs=0.01)
    assert e["amount"] == pytest.approx(_DEPOSIT, abs=0.01)


def test_same_day_snapshot_taken_before_deposit_is_nav_before():
    """券商記 6/22 入金，但 6/22 的 NAV 快照明顯還沒含入金 → 以該快照為 nav_before，
    不要退到 6/18（否則 6/22 當天跌幅會被算進入金子期間）。"""
    flows = [{"date": "2026-06-22", "type": "deposit", "amount": _DEPOSIT}]
    e = cashflow.flows_to_events(flows, _HIST)[0]
    assert e["nav_before"] == pytest.approx(19883.01, abs=0.01)


def test_withdrawal_event_has_negative_amount_and_lower_nav_after():
    flows = [{"date": "2026-06-23", "type": "withdrawal", "amount": 1000.0}]
    e = cashflow.flows_to_events(flows, _HIST)[0]
    assert e["type"] == "withdrawal"
    assert e["amount"] == pytest.approx(-1000.0)
    assert e["nav_after"] == pytest.approx(e["nav_before"] - 1000.0, abs=0.01)


def test_no_flows_or_no_history_gives_no_events():
    assert cashflow.flows_to_events([], _HIST) == []
    assert cashflow.flows_to_events(
        [{"date": "2026-06-23", "type": "deposit", "amount": 1.0}], []) == []


def test_twr_with_synced_deposit_excludes_contribution():
    """#3 的真實數字：單純報酬 +64.8%，正確 TWR ≈ +11.6%。"""
    flows = [{"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}]
    ev = cashflow.flows_to_events(flows, _HIST)
    twr = compute_twr(_HIST, ev)
    expected = ((19883.01 / 19820.37) * (32665.40 / (19883.01 + _DEPOSIT)) - 1) * 100
    assert twr == pytest.approx(expected, abs=0.05)
    assert twr < 20.0, "入金不得被算成報酬"


# ── sync_cash_flows / load_cash_flows ────────────────────────────────────────
class _AlpacaLike:
    def __init__(self, flows):
        self._flows = flows
        self.since_calls: list[str] = []

    def get_cash_flows(self, since):
        self.since_calls.append(since)
        return [f for f in self._flows if f["date"] > since]


def _write_history(d: Path):
    (d / "portfolio_state_history.json").write_text(
        json.dumps({"history": [dict(h, cash=0.0) for h in _HIST]}), encoding="utf-8")


def test_sync_writes_cash_flows_json_from_inception(tmp_path):
    _write_history(tmp_path)
    c = _AlpacaLike([{"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}])
    flows = cashflow.sync_cash_flows(c, tmp_path, logging.getLogger("t"))
    assert flows == [{"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}]
    assert c.since_calls == ["2026-05-17"], "自成立日前一天起抓，才補得到歷史入金"
    saved = json.loads((tmp_path / "cash_flows.json").read_text(encoding="utf-8"))
    assert saved["flows"] == flows
    assert cashflow.load_cash_flows(tmp_path) == flows


def test_sync_is_idempotent_and_dedupes(tmp_path):
    _write_history(tmp_path)
    dup = {"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}
    c = _AlpacaLike([dup, dict(dup)])
    cashflow.sync_cash_flows(c, tmp_path, logging.getLogger("t"))
    cashflow.sync_cash_flows(c, tmp_path, logging.getLogger("t"))
    assert len(cashflow.load_cash_flows(tmp_path)) == 1


def test_sync_without_history_uses_wide_window(tmp_path):
    c = _AlpacaLike([{"date": "2026-06-23", "type": "deposit", "amount": 5.0}])
    cashflow.sync_cash_flows(c, tmp_path, logging.getLogger("t"))
    assert c.since_calls and c.since_calls[0] <= "2020-01-01"


def test_sync_client_without_cash_flow_support_keeps_existing_file(tmp_path):
    """永豐等 SDK 券商沒有 get_cash_flows → 不抓、不覆寫既有檔、不丟例外。"""
    (tmp_path / "cash_flows.json").write_text(
        json.dumps({"flows": [{"date": "2026-01-02", "type": "deposit", "amount": 1.0}]}))

    class _NoSupport:  # 連方法都沒有
        pass

    assert cashflow.sync_cash_flows(_NoSupport(), tmp_path, logging.getLogger("t")) == []
    assert len(cashflow.load_cash_flows(tmp_path)) == 1


def test_sync_broker_error_does_not_raise(tmp_path):
    class _Boom:
        def get_cash_flows(self, since):
            raise RuntimeError("alpaca 500")

    assert cashflow.sync_cash_flows(_Boom(), tmp_path, logging.getLogger("t")) == []
    assert not (tmp_path / "cash_flows.json").exists()


def test_load_missing_file_returns_empty(tmp_path):
    assert cashflow.load_cash_flows(tmp_path) == []


# ── build_summary：入金當天的今日損益要扣掉入金 ──────────────────────────────
def test_today_change_excludes_same_day_deposit():
    flows = [{"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}]
    ev = cashflow.flows_to_events(flows, _HIST[:4])
    s = build_summary(nav=28787.60, cash=9142.27, initial_nav=19820.37,
                      inception_date="2026-05-18", prev_nav=19883.01,
                      nav_history=_HIST[:4], events=ev, trading_date="2026-06-23")
    assert s["today_change"] == pytest.approx(28787.60 - 19883.01 - _DEPOSIT, abs=0.01)
    assert s["today_change_pct"] == pytest.approx(-2.88, abs=0.05)
    assert s["net_contribution"] == pytest.approx(_DEPOSIT, abs=0.01)


# ── report_generator：讀 cash_flows.json 產 events（不再寫死 []）─────────────
def test_report_generator_events_come_from_cash_flows_file(tmp_path, monkeypatch):
    from engine import report_generator as rg
    (tmp_path / "data" / "3").mkdir(parents=True)
    (tmp_path / "data" / "3" / "cash_flows.json").write_text(json.dumps(
        {"flows": [{"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}]}))
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    ev = rg.account_events("data/3", _HIST)
    assert len(ev) == 1 and ev[0]["type"] == "deposit"
    assert rg.account_events("data/9", _HIST) == []


# ── runner：建立 client 後、守門前就同步，非換股日也會補到 ──────────────────
def test_runner_syncs_cash_flows_before_gate(tmp_path, monkeypatch):
    import runner
    import brokers.from_env as fe

    class _C:
        broker_id, environment = "alpaca", "live"
        def is_trading_day(self, d): return False          # 守門擋下 → 提早 return
        def get_cash_flows(self, since):
            return [{"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}]

    _write_history(tmp_path)
    monkeypatch.setattr(fe, "build_client_for_account", lambda aid: _C())
    import trade_log
    monkeypatch.setattr(trade_log, "record_skip", lambda **k: None)   # 不污染 repo data/
    rc = runner.run(strategy_id="tech_top10", account_id="3", data_dir=tmp_path,
                    dry_run=False, date_override="2026-10-11")  # 週六
    assert rc == 0
    assert cashflow.load_cash_flows(tmp_path)[0]["amount"] == pytest.approx(_DEPOSIT)


# ── 雜訊：$1 以下的 JNLC（如 Juneteenth 保證金補貼 $0.06）不當入金事件 ────────
def test_normalize_drops_sub_dollar_noise():
    flows = [{"date": "2026-08-17", "type": "deposit", "amount": 0.06},
             {"date": "2026-06-23", "type": "deposit", "amount": _DEPOSIT}]
    ev = cashflow.flows_to_events(flows, _HIST)
    assert [e["date"] for e in ev] == ["2026-06-23"]
