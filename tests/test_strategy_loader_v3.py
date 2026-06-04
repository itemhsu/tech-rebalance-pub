"""engine/strategy_loader v3 — schema 偵測與載入驗證。

（原 tests/test_toprank_v3.py 拆出。toprank/v3_runner live-trading 路徑已退役，
 對應的 IndicatorEngine/FilterEngine/RankingEngine/SignalEvaluator/v3_runner
 測試隨程式碼一併移除；此處只保留仍 live 的 strategy_loader 測試。）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestStrategyLoaderV3:

    def test_is_v3_strategy(self):
        from engine.strategy_loader import is_v3_strategy
        assert is_v3_strategy({"schema_version": "3.0.0"}) is True
        assert is_v3_strategy({"schema_version": "1.0"})   is False
        assert is_v3_strategy({})                           is False

    def test_is_v3_algorithmic(self):
        from engine.strategy_loader import is_v3_algorithmic
        assert is_v3_algorithmic({
            "schema_version": "3.0.0",
            "indicators": [{"name": "sma_20", "type": "SMA", "period": 20}],
        }) is True
        assert is_v3_algorithmic({
            "schema_version": "3.0.0",
        }) is False

    def test_load_toprank_v3(self):
        from engine.strategy_loader import load_strategy
        data = load_strategy("toprank_v3")
        assert data["id"] == "toprank_ma_momentum"
        assert data["schema_version"] == "3.0.0"

    def test_validate_toprank_v3(self):
        from engine.strategy_loader import load_and_validate_v3
        data = load_and_validate_v3("toprank_v3")
        assert "indicators" in data
        assert "ranking"    in data

    def test_validate_top10_v3_with_v3_schema(self):
        from engine.strategy_loader import load_and_validate
        data = load_and_validate("top10_v3")
        assert data["id"] == "top10"

    def test_validate_d2p2t6_v3_with_v3_schema(self):
        from engine.strategy_loader import load_and_validate
        data = load_and_validate("d2p2t6_v3")
        assert data["id"] == "d2p2t6"
