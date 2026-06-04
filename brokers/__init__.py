"""brokers/ — 多卷商抽象層。

設計：每家卷商有一個 JSON 描述 API（brokers/{id}.json），
        對應一個 Python client 類別實作 BrokerClient ABC。
        策略邏輯（main.py / portfolio.py）只看 BrokerClient 介面，
        完全不知道背後是哪家卷商。

入口：
    from brokers.registry import build_client
    client = build_client(broker_id="alpaca", environment="paper",
                          secret_prefix="ACC1")
    nav = client.get_account_balance()

每家 broker 必須實作 6 個方法（見 base.BrokerClient）。
"""
