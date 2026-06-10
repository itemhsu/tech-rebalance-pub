"""tests/conftest.py — 誠實 auto-skip：fresh clone 缺執行期產物的測試以「指名理由」skip。

設計約束（no-fake-pass）：
- 只有當某測試所需的**具名產物真的不存在**時才 skip。
- 每個 skip 的 reason 必定**指名**缺少的產物；不靜默、不假綠。
- CI / dev repo 有該產物時照常執行 → **CI 契約不變**。
- 真正的邏輯 bug 不在此處理（例：test_runner_e2e_mock 的 mock 已直接修正）。
- collection 期就讀檔的兩個模組（test_email_sections_valid / test_report_generator）
  改用各自 module-level `pytest.skip(allow_module_level=True)` 守衛——import 期錯誤
  此 hook 攔不到。

`pytest -rs` 會列出每個 skip 與其指名理由，供誠實稽核。
"""
from __future__ import annotations

import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# 一般執行期產物缺席的據實理由（由 run-account / dashboard 產生，部署或 CI 才有）
_RUNTIME = ("provisioned at runtime by run-account / dashboard build "
            "(CI or dev repo); absent in a fresh clone")

# module 檔名 stem -> (該模組所需的具名產物 [相對 repo root], 理由)
# 理由依產物性質誠實區分，不一律謊稱 "CI-provisioned"。
_ENV_MODULES = {
    "test_unit10_dashboard":  (["mvp_dashboard.html"], _RUNTIME),
    "test_unit12_smoke":      (["accounts.json", "mvp_dashboard.html"], _RUNTIME),
    "test_dashboard_health":  (["accounts.json"], _RUNTIME),
    "test_email_renderer":    (["accounts.json"], _RUNTIME),
    "test_unit2_accounts":    (["accounts.json"], _RUNTIME),
    "test_from_env":          (["accounts.json"], _RUNTIME),
}


def _missing(rel_paths):
    return [p for p in rel_paths if not (_ROOT / p).exists()]


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = getattr(item, "path", None) or getattr(item, "fspath", None)
        stem = pathlib.Path(str(path)).stem if path is not None else ""
        spec = _ENV_MODULES.get(stem)
        if not spec:
            continue
        required, why = spec
        miss = _missing(required)
        if miss:
            item.add_marker(pytest.mark.skip(
                reason=f"requires runtime artifact(s): {', '.join(miss)} — {why}"))
