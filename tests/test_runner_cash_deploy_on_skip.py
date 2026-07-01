"""非換股日把閒置現金部署進『當前選股』→ 只買不賣、不碰舊持倉。

v2（2026-07-01）：_maybe_deploy_idle_cash 改用 _select_current_picks + compute_deploy_into_picks，
舊的 compute_cash_deployment_orders（投進舊持倉）已移除。
"""
import runner
from portfolio import Position


def _pos(sym, qty, px):
    mv = qty * px
    return Position(symbol=sym, qty=qty, avg_entry_price=px, current_price=px,
                    market_value=mv, unrealized_pl=0.0, unrealized_plpc=0.0)


# ────────────────────────────────────────────────────────────────────────
# Tests for _maybe_deploy_idle_cash (picks-based)
# ────────────────────────────────────────────────────────────────────────

def test_maybe_deploy_targets_current_picks_not_holdings(monkeypatch, tmp_path):
    """#3 情境：持有 INTC/ORCL（不在 picks），picks 為當前動能選股 → 只買 picks，不碰 INTC/ORCL。"""
    import runner, trader, logging, datetime
    from portfolio import Position
    picks  = ["NVDA","AAPL","MSFT","AMZN","GOOGL","META","AVGO","TSM","AMD","ASML"]
    prices = {s: 100.0 for s in picks}
    monkeypatch.setattr(runner, "_select_current_picks", lambda spec, client, log: (picks, prices))
    class C:  # 持有 INTC/ORCL（不在 picks）+ 大量閒置現金
        def get_account_nav(self): return (28158.0, 9146.0)
        def get_current_positions(self):
            return [Position(symbol=s, qty=40, avg_entry_price=100, current_price=100,
                             market_value=4000, unrealized_pl=0, unrealized_plpc=0)
                    for s in ("INTC","ORCL")]
    cap = {}
    monkeypatch.setattr(trader, "execute_rebalance",
        lambda client, orders, dry_run=False, **k: cap.update(orders=orders) or [])
    d = runner._maybe_deploy_idle_cash(spec={}, client=C(), data_dir=str(tmp_path),
        today=datetime.date(2026,7,2), account_id="3", strategy_id="mom_6m_t20",
        dry_run=True, log=logging.getLogger("t"))
    assert d is True
    o = cap["orders"]
    assert o and all(x.action == "BUY" for x in o), "只買不賣"
    assert {x.symbol for x in o} <= set(picks), "只買當前選股"
    assert not ({x.symbol for x in o} & {"INTC","ORCL"}), "不碰舊持倉"


def test_maybe_deploy_low_cash_returns_false(monkeypatch, tmp_path):
    """現金 < NAV×1% → 不部署，回 False。"""
    import runner, logging, datetime
    from portfolio import Position
    monkeypatch.setattr(runner, "_select_current_picks", lambda s,c,l: (["NVDA"], {"NVDA":100.0}))
    class C:
        def get_account_nav(self): return (10000.0, 50.0)   # 現金 < 1% NAV
        def get_current_positions(self): return []
    d = runner._maybe_deploy_idle_cash(spec={}, client=C(), data_dir=str(tmp_path),
        today=datetime.date(2026,7,2), account_id="3", strategy_id="mom_6m_t20",
        dry_run=True, log=logging.getLogger("t"))
    assert d is False


def test_maybe_deploy_empty_picks_returns_false(monkeypatch, tmp_path):
    """_select_current_picks 回空 → 不部署，回 False。"""
    import runner, logging, datetime
    monkeypatch.setattr(runner, "_select_current_picks", lambda s,c,l: ([], {}))
    class C:
        def get_account_nav(self): return (28158.0, 9146.0)
        def get_current_positions(self): return []
    d = runner._maybe_deploy_idle_cash(spec={}, client=C(), data_dir=str(tmp_path),
        today=datetime.date(2026,7,2), account_id="3", strategy_id="mom_6m_t20",
        dry_run=True, log=logging.getLogger("t"))
    assert d is False


def test_maybe_deploy_no_orders_when_fully_allocated(monkeypatch, tmp_path):
    """持倉已滿（現金恰好 < 門檻）→ compute_deploy_into_picks 回空 → False。"""
    import runner, logging, datetime
    from portfolio import Position
    picks = ["NVDA","AAPL"]
    prices = {s: 100.0 for s in picks}
    monkeypatch.setattr(runner, "_select_current_picks", lambda s,c,l: (picks, prices))
    class C:
        def get_account_nav(self): return (10050.0, 50.0)  # cash < 1% NAV
        def get_current_positions(self):
            return [_pos(s, 50, 100.0) for s in picks]  # 10000 持倉
    d = runner._maybe_deploy_idle_cash(spec={}, client=C(), data_dir=str(tmp_path),
        today=datetime.date(2026,7,2), account_id="3", strategy_id="mom_6m_t20",
        dry_run=True, log=logging.getLogger("t"))
    assert d is False
