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


# ── v1.0.29：第二輪貪婪補殘留（整股取整後的剩餘現金）──────────────────────────

def _total(orders):
    return sum(o.estimated_value for o in orders)


def test_second_pass_deploys_rounding_residual():
    # 3 檔、高價股；第一輪按比例縮後 floor 會留下大量殘留
    picks = ["A", "B", "C"]
    prices = {"A": 300.0, "B": 300.0, "C": 300.0}
    # nav=3000 → 目標各 1000；cash=2000 → budget≈1990；scale≈0.663 → 每檔 663/300 → 2 股
    # 第一輪 6 股 = 1800，殘留 ≈190 < 300 → 不能再補；改 cash 讓殘留 ≥ 1 股
    orders = runner.compute_deploy_into_picks([], picks, prices, nav=3000.0, cash=2400.0)
    # budget=2376；scale=0.792 → 792/300 → 2 股 each = 1800；殘留 576 → 補 1 股（再剩 276 < 300 停）
    assert _total(orders) == 2100.0
    assert _total(orders) <= 2400.0 * (1 - 0.01) + 1e-9


def test_second_pass_never_overbuys_beyond_target():
    # 單檔：缺口 < 1 股價時不補（不超買目標）
    picks = ["A"]
    prices = {"A": 400.0}
    positions = [_pos("A", 700.0)]       # 目標 1000，缺口 300 < 400
    orders = runner.compute_deploy_into_picks(positions, picks, prices, nav=1000.0, cash=900.0)
    assert orders == []


def test_second_pass_prefers_largest_remaining_gap():
    picks = ["A", "B"]
    prices = {"A": 100.0, "B": 100.0}
    positions = [_pos("A", 500.0)]       # nav 2000 → 目標各 1000；缺口 A=500、B=1000
    # cash=250 → budget=247.5；scale=0.165 → A 0 股、B 1 股；殘留 147.5 → 補 1 股給剩餘缺口最大者（B=900 > A=500）
    orders = runner.compute_deploy_into_picks(positions, picks, prices, nav=2000.0, cash=250.0)
    by = {o.symbol: o.qty for o in orders}
    assert by.get("B") == 2 and "A" not in by


def test_second_pass_respects_cash_cap():
    picks = ["A", "B", "C", "D"]
    prices = {s: 97.0 for s in picks}
    orders = runner.compute_deploy_into_picks([], picks, prices, nav=40000.0, cash=1000.0)
    assert _total(orders) <= 1000.0 * (1 - 0.01) + 1e-9
    # 殘留必須 < 一股價（否則還能再補）
    assert 1000.0 * (1 - 0.01) - _total(orders) < 97.0
