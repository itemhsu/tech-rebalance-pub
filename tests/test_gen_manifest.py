"""引擎 manifest 產生器（兩 repo GUI G1）。manifest 是 GUI 策略/券商清單的來源。"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.gen_manifest import build_manifest


def test_manifest_core_fields():
    m = build_manifest()
    assert m["manifest_version"] == "1"
    assert m["engine_version"]   # 非空
    assert m["data_schema"]
    assert isinstance(m["strategies"], list) and m["strategies"]
    assert isinstance(m["brokers"], dict) and m["brokers"]


def test_engine_version_matches_pyproject():
    import re
    txt = (ROOT / "pyproject.toml").read_text()
    ver = re.search(r'^version\s*=\s*"([^"]+)"', txt, re.M).group(1)
    assert build_manifest()["engine_version"] == ver


def test_data_schema_matches_engine():
    from engine.data_writer import SCHEMA_VERSION
    assert build_manifest()["data_schema"] == SCHEMA_VERSION


def test_strategies_exclude_schema_files():
    s = build_manifest()["strategies"]
    assert "top10" in s and "mom_6m_t20" in s
    assert not any("schema" in x for x in s)   # 不含 strategy-schema-*


def test_broker_required_env_from_source_map():
    import run_account as ra
    b = build_manifest()["brokers"]
    # 與引擎實際讀取的 secret 名稱一致（單一事實來源）
    assert b["alpaca"]["required_env"] == list(ra._source_map("{PREFIX}", "alpaca").values())
    assert "{PREFIX}_ALPACA_KEY" in b["alpaca"]["required_env"]
    assert "paper" in b["alpaca"]["environments"] and "live" in b["alpaca"]["environments"]


def test_brokers_exclude_schema():
    assert "broker-schema-v1" not in build_manifest()["brokers"]


def test_broker_environments_is_dict_with_base_url():
    """回歸：environments 必須是 dict（含 base_url），probe_broker 才能連線測試。
    曾被壓成 list 導致 GUI 'list' object has no attribute 'get'。"""
    a = build_manifest()["brokers"]["alpaca"]
    assert isinstance(a["environments"], dict)
    assert a["environments"]["paper"].get("base_url")
    assert a["environments"]["live"].get("base_url")


def test_broker_full_spec_embedded():
    """GUI 需要 auth.method + 輸入欄位名 + endpoints。"""
    a = build_manifest()["brokers"]["alpaca"]
    assert a["auth"]["method"]                       # credential 標籤
    assert a["auth"]["required_env"]                 # 輸入欄位名（API_KEY/API_SECRET）
    assert a.get("endpoints")                        # probe 取餘額端點
