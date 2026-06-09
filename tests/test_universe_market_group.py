"""market_group 股池：依市場解析 universe/<group>.<market>.json。"""
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.universe_loader import load_universe_groups

_SPEC = {"universe": {"type": "single",
                      "source": {"type": "market_group", "group": "tech"}}}


def test_market_group_us_loads_us_pool():
    syms = load_universe_groups(_SPEC, "us")["__all__"]
    assert "AAPL" in syms and len(syms) >= 20
    assert not any(s.endswith(".TW") for s in syms)


def test_market_group_tw_loads_tw_pool():
    syms = load_universe_groups(_SPEC, "tw")["__all__"]
    assert "2330.TW" in syms and len(syms) >= 20
    assert all(s.endswith(".TW") for s in syms)


def test_market_group_default_market_is_us():
    assert "AAPL" in load_universe_groups(_SPEC)["__all__"]


def test_market_group_missing_file_raises():
    spec = {"universe": {"type": "single",
                         "source": {"type": "market_group", "group": "nosuch"}}}
    with pytest.raises(FileNotFoundError):
        load_universe_groups(spec, "us")


def test_market_group_requires_group():
    spec = {"universe": {"type": "single", "source": {"type": "market_group"}}}
    with pytest.raises(ValueError):
        load_universe_groups(spec, "us")
