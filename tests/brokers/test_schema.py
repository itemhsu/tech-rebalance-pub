"""Phase 1 Schema 測試 — 對應計劃書 S-01 ~ S-08。

驗證 brokers/*.json 符合 broker-schema-v2.json（v2 向下相容 v1；
Phase B 後 alpaca.json 含 request/response 區塊，需用 v2 驗證）。
"""
import json
from pathlib import Path

import pytest

BROKERS_DIR = Path(__file__).resolve().parent.parent.parent / "brokers"
SCHEMA_PATH = BROKERS_DIR / "broker-schema-v2.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _broker_files():
    """所有 brokers/*.json，排除 schema 檔本身。"""
    return [p for p in BROKERS_DIR.glob("*.json") if "broker-schema" not in p.name]


@pytest.fixture
def schema():
    return _load(SCHEMA_PATH)


# ── S-01 ───────────────────────────────────────────────────────────────
def test_all_brokers_match_schema(schema):
    """所有 brokers/*.json 通過 v1 schema 驗證。"""
    jsonschema = pytest.importorskip("jsonschema")
    files = _broker_files()
    assert files, "至少要有一個 broker JSON 才能跑此測試"
    for p in files:
        spec = _load(p)
        try:
            jsonschema.validate(spec, schema)
        except jsonschema.ValidationError as e:
            pytest.fail(f"{p.name}: {e.message}")


# ── S-02 ───────────────────────────────────────────────────────────────
def test_required_top_level_keys():
    """每個 broker JSON 必有 required keys。"""
    required = {"id", "version", "display_name", "country",
                "integration", "auth", "environments", "capabilities"}
    for p in _broker_files():
        spec = _load(p)
        missing = required - set(spec.keys())
        assert not missing, f"{p.name} 缺少 keys: {missing}"


# ── S-03 ───────────────────────────────────────────────────────────────
def test_auth_method_enum():
    """auth.method 必在已知 enum 中。"""
    allowed = {"api_key_secret", "bearer_token", "oauth_bearer", "oauth_refresh",
               "session_login", "sdk_login"}
    for p in _broker_files():
        spec = _load(p)
        method = spec.get("auth", {}).get("method")
        assert method in allowed, f"{p.name} auth.method={method!r} 不在 {allowed}"


# ── S-04 ───────────────────────────────────────────────────────────────
def test_integration_type_enum():
    """integration.type 必為 'rest' 或 'sdk'。"""
    for p in _broker_files():
        spec = _load(p)
        t = spec.get("integration", {}).get("type")
        assert t in ("rest", "sdk"), f"{p.name} integration.type={t!r}"


# ── S-05 ───────────────────────────────────────────────────────────────
def test_environments_unique_base_url():
    """同 broker 內各 env 的 base_url 不重複（如有 base_url 欄位）。"""
    for p in _broker_files():
        spec = _load(p)
        urls = []
        for env_name, env_cfg in spec.get("environments", {}).items():
            url = env_cfg.get("base_url")
            if url:
                urls.append((env_name, url))
        seen = {}
        for env_name, url in urls:
            assert url not in seen, (
                f"{p.name} {env_name} 和 {seen[url]} 共用 base_url={url}"
            )
            seen[url] = env_name


# ── S-06 ───────────────────────────────────────────────────────────────
def test_capabilities_arrays_not_empty():
    """asset_classes / order_types / time_in_force 至少一筆。"""
    for p in _broker_files():
        spec = _load(p)
        caps = spec.get("capabilities", {})
        for key in ("asset_classes", "order_types", "time_in_force"):
            assert caps.get(key), f"{p.name} capabilities.{key} 不能空"


# ── S-07 ───────────────────────────────────────────────────────────────
def test_broker_id_matches_filename():
    """檔名 alpaca.json 必須含 id='alpaca'。"""
    for p in _broker_files():
        spec = _load(p)
        expected = p.stem  # 'alpaca' from 'alpaca.json'
        assert spec.get("id") == expected, (
            f"{p.name}: id={spec.get('id')!r} 與檔名不符"
        )


# ── S-08 ───────────────────────────────────────────────────────────────
def test_required_env_uses_prefix_template():
    """required_env 內字串必含 {PREFIX} 模板（之後 resolve 用）。"""
    for p in _broker_files():
        spec = _load(p)
        envs = spec.get("auth", {}).get("required_env", [])
        for var in envs:
            assert "{PREFIX}" in var, (
                f"{p.name} required_env 項目 {var!r} 缺少 {{PREFIX}} 模板"
            )
