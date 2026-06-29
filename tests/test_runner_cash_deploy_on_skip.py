"""非換股日把閒置現金部署進『現有持倉』→ 只買不賣、不換股、不 re-pick。

入金後最常見情境：全體持倉同步變得低於目標權重（偏離 >容忍帶），
calculate_rebalance 以 weight_adjust 買單把現金補進現有持倉；
若全體在容忍帶內，則以 cash_deployment 均分閒置現金。兩者都保留，
但排除任何 SELL（不 churn）與組合異動（exit_top10 / new_entrant）。
"""
import runner
from portfolio import Position


def _pos(sym, qty, px):
    mv = qty * px
    return Position(symbol=sym, qty=qty, avg_entry_price=px, current_price=px,
                    market_value=mv, unrealized_pl=0.0, unrealized_plpc=0.0)


def test_deposit_deploys_into_existing_holdings_no_churn():
    """真實情境：入金後全體低於目標權重（偏離 >2%）→ weight_adjust 把現金部署進持倉。"""
    syms = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","TSM","AMD","ASML"]
    px = {s: 100.0 for s in syms}
    # 模擬入金後：每檔 ~6.75% (低於 10% target，偏離 >2%)，9146 閒置現金
    qty = (28158.0 - 9146.0) / 10 / 100.0
    positions = [_pos(s, qty, 100.0) for s in syms]
    orders = runner.compute_cash_deployment_orders(
        positions=positions, prices=px, nav=28158.0, cash=9146.0)
    assert orders, "入金後必須把閒置現金部署出去"
    assert all(o.action == "BUY" for o in orders), "非換股日只買不賣（不 churn）"
    assert all(o.reason in ("weight_adjust", "cash_deployment") for o in orders)
    assert {o.symbol for o in orders} <= set(syms), "只動現有持倉，不新增標的（不 re-pick）"
    assert sum(o.estimated_value for o in orders) > 5000, "應部署大部分現金"


def test_within_tolerance_idle_cash_uses_cash_deployment():
    """權重已在容忍帶內、僅有閒置現金 → Step F cash_deployment 均分。"""
    syms = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","TSM","AMD","ASML"]
    px = {s: 100.0 for s in syms}
    # 每檔持有 11 股（市值 1100），NAV=11000(持倉)+2000(現金)=13000
    # 每檔權重 1100/13000≈8.46%，target=10%，偏差≈1.54% < 2% 容忍帶 → Step D 不動
    # 現金 2000 >> NAV*1%=130 → Step F 觸發 cash_deployment
    positions = [_pos(s, 11, 100.0) for s in syms]
    orders = runner.compute_cash_deployment_orders(
        positions=positions, prices=px, nav=13000.0, cash=2000.0)
    assert orders, "有閒置現金應產生部署訂單"
    assert all(o.action == "BUY" for o in orders)
    assert all(o.reason in ("weight_adjust", "cash_deployment") for o in orders)


def test_no_idle_cash_no_orders():
    syms = ["AAPL","MSFT"]
    px = {s: 100.0 for s in syms}
    positions = [_pos(s, 50, 100.0) for s in syms]  # 持倉 10000，現金僅 50（<1%）
    orders = runner.compute_cash_deployment_orders(
        positions=positions, prices=px, nav=10050.0, cash=50.0)
    assert orders == [], "現金低於門檻不部署"


def test_empty_positions_no_orders():
    assert runner.compute_cash_deployment_orders(positions=[], prices={}, nav=1000.0, cash=500.0) == []


# ────────────────────────────────────────────────────────────────────────
# Tests for _maybe_deploy_idle_cash
# ────────────────────────────────────────────────────────────────────────

class _FakeClient:
    def __init__(self, nav, cash, syms, px):
        self._nav, self._cash, self._syms, self._px = nav, cash, syms, px
        self.executed = None
    def get_account_nav(self): return (self._nav, self._cash)
    def get_current_positions(self):
        from portfolio import Position
        q = (self._nav - self._cash) / len(self._syms) / 100.0
        return [Position(symbol=s, qty=q, avg_entry_price=100.0, current_price=100.0,
                         market_value=q*100.0, unrealized_pl=0.0, unrealized_plpc=0.0) for s in self._syms]
    def get_latest_prices(self, syms): return {s: self._px for s in syms}


def test_maybe_deploy_idle_cash_deploys(monkeypatch, tmp_path):
    import runner, trader
    syms = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","TSM","AMD","ASML"]
    cli = _FakeClient(nav=28158.0, cash=9146.0, syms=syms, px=100.0)
    captured = {}
    monkeypatch.setattr(trader, "execute_rebalance",
        lambda client, orders, dry_run=False, **k: captured.setdefault("orders", orders) or [])
    import logging; log = logging.getLogger("t")
    deployed = runner._maybe_deploy_idle_cash(
        spec={}, client=cli, data_dir=str(tmp_path), today=__import__("datetime").date(2026,6,26),
        account_id="3", strategy_id="mom_6m_t20", dry_run=True, log=log)
    assert deployed is True
    assert captured["orders"], "應送出部署訂單"
    assert all(o.action == "BUY" for o in captured["orders"])


def test_maybe_deploy_idle_cash_low_cash_returns_false(tmp_path):
    import runner, logging
    syms = ["AAPL","MSFT"]
    cli = _FakeClient(nav=10050.0, cash=50.0, syms=syms, px=100.0)  # cash < 1% NAV
    deployed = runner._maybe_deploy_idle_cash(
        spec={}, client=cli, data_dir=str(tmp_path), today=__import__("datetime").date(2026,6,26),
        account_id="3", strategy_id="mom_6m_t20", dry_run=True, log=logging.getLogger("t"))
    assert deployed is False
