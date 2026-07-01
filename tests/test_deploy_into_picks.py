"""現金部署投進『當前選股』：只買不賣、目標=picks、不碰非選股持倉。"""
import runner
from portfolio import Position


def _pos(sym, val):
    return Position(symbol=sym, qty=val / 100.0, avg_entry_price=100.0,
                    current_price=100.0, market_value=val,
                    unrealized_pl=0.0, unrealized_plpc=0.0)


def test_targets_current_picks_not_holdings():
    positions = [_pos("INTC", 4000), _pos("ORCL", 2000)]   # 走弱、不在當前選股
    picks = ["NVDA","AAPL","MSFT","AMZN","GOOGL","META","AVGO","TSM","AMD","ASML"]
    prices = {**{s: 100.0 for s in picks}, "INTC": 100.0, "ORCL": 100.0}
    orders = runner.compute_deploy_into_picks(positions, picks, prices, nav=20000.0, cash=6000.0)
    assert orders, "有現金應部署"
    syms = {o.symbol for o in orders}
    assert syms <= set(picks), "只買當前選股"
    assert "INTC" not in syms and "ORCL" not in syms, "不加碼舊持倉"
    assert all(o.action == "BUY" for o in orders), "只買不賣"


def test_buy_only_never_touches_dropped_holdings():
    positions = [_pos("INTC", 9000)]        # 大量舊持倉、不在 picks
    picks = ["NVDA","AAPL"]
    prices = {"NVDA":100.0,"AAPL":100.0,"INTC":100.0}
    orders = runner.compute_deploy_into_picks(positions, picks, prices, nav=10000.0, cash=1000.0)
    assert all(o.action == "BUY" for o in orders)
    assert all(o.symbol != "INTC" for o in orders), "絕不賣/動 INTC"


def test_capped_by_cash():
    picks = ["A","B","C","D","E","F","G","H","I","J"]
    prices = {s: 100.0 for s in picks}
    orders = runner.compute_deploy_into_picks([], picks, prices, nav=100000.0, cash=500.0)
    assert sum(o.estimated_value for o in orders) <= 500.0, "部署總額不得超過現金"


def test_no_idle_cash_returns_empty():
    assert runner.compute_deploy_into_picks([], ["A"], {"A":100.0}, nav=10000.0, cash=50.0) == []


def test_new_entrant_reason():
    o = runner.compute_deploy_into_picks([], ["NVDA"], {"NVDA":100.0}, nav=1000.0, cash=900.0)
    assert o and o[0].reason == "new_entrant"


def test_continuing_underweight_reason_weight_adjust():
    positions = [_pos("NVDA", 50.0)]   # 已持有一點點 NVDA（遠低於目標）
    o = runner.compute_deploy_into_picks(positions, ["NVDA"], {"NVDA":100.0}, nav=1000.0, cash=900.0)
    assert o and o[0].reason == "weight_adjust"
