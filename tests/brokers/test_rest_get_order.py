"""RestBrokerClient.get_order — 補上 trader 記錄 outcome 所需的查單方法。

對應 paper 實跑抓到的 bug：'RestBrokerClient' object has no attribute 'get_order'。
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from brokers.rest_broker import RestBrokerClient


class _Resp:
    status_code = 200; ok = True
    def __init__(self, d): self._d = d
    def json(self): return self._d


def _client(captured):
    spec = json.loads((ROOT / "brokers" / "alpaca.json").read_text())
    env = {"base_url": "https://paper-api.alpaca.markets",
           "API_KEY": "k", "API_SECRET": "s"}
    c = RestBrokerClient(spec, env, "paper")
    def fake_request(method, url, **k):
        captured["method"] = method; captured["url"] = url
        return _Resp({"id": "abc", "status": "filled",
                      "filled_qty": "6", "filled_avg_price": "320.5"})
    c._request = fake_request
    return c


def test_has_get_order():
    assert hasattr(RestBrokerClient, "get_order")


def test_get_order_hits_order_by_id_and_returns_raw():
    cap = {}
    order = _client(cap).get_order("abc")
    assert cap["method"] == "GET"
    assert "/v2/orders/abc" in cap["url"]           # 用 order_by_id 端點
    assert order["status"] == "filled"               # 原始欄位給 trader 讀
    assert order["filled_qty"] == "6"
