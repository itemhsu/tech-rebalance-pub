#!/usr/bin/env python3
"""scripts/gen_manifest.py — 產生引擎 manifest.json（兩 repo 架構 GUI G1）。

GUI（管理 Repo B 薄殼）需要知道「這版引擎有哪些策略 / 券商」，但 Repo B 不含
strategies/ brokers/（在 wheel 裡）。引擎發版時產生此 manifest 附到 Release，
GUI 抓它餵下拉選單與必填 secret 推導。

必填 secret 來自引擎自己的 run_account._source_map（單一事實來源），確保 GUI
推導的 secret 名稱與引擎實際讀取的一致。

用法：python scripts/gen_manifest.py [輸出路徑，預設 manifest.json]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _engine_version() -> str:
    """從 pyproject.toml 讀 version（不依賴 tomllib，3.9 相容）。"""
    import re
    txt = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', txt, re.M)
    return m.group(1) if m else "0.0.0"


def _strategies() -> list[str]:
    out = []
    for f in sorted(glob.glob(str(ROOT / "strategies" / "*.json"))):
        name = os.path.basename(f)
        if "schema" in name:
            continue
        out.append(name[:-5])
    return out


def _brokers() -> dict:
    """嵌入「完整 broker spec」到 manifest（GUI 需要 auth.method、輸入欄位名、
    account_discovery 等），而非有損摘要。

    額外正規化兩個欄位給 GUI 直接用：
      - environments：dict.keys() → list
      - required_env：最終 secret 名（引擎 _source_map，單一事實來源）
    保留原始 auth（含輸入欄位名 {PREFIX}_API_KEY 等）供 credential_inputs 使用。
    """
    import run_account as ra
    out = {}
    for f in sorted(glob.glob(str(ROOT / "brokers" / "*.json"))):
        name = os.path.basename(f)
        if "schema" in name:
            continue
        bid = name[:-5]
        spec = json.loads(Path(f).read_text(encoding="utf-8"))
        # 嵌入「完整 spec」原封不動（含 auth / account_discovery /
        # environments dict（每環境 base_url）/ endpoints / response 路徑）。
        # 不可把 environments 壓成 list — probe_broker 需要 dict 取 base_url。
        entry = dict(spec)
        entry["required_env"] = list(ra._source_map("{PREFIX}", bid).values())
        out[bid] = entry
    return out


def build_manifest() -> dict:
    from engine.data_writer import SCHEMA_VERSION
    return {
        "manifest_version": "1",
        "engine_version": _engine_version(),
        "data_schema": SCHEMA_VERSION,
        "strategies": _strategies(),
        "brokers": _brokers(),
    }


def main(argv: list[str]) -> int:
    out_path = Path(argv[1]) if len(argv) > 1 else (ROOT / "manifest.json")
    manifest = build_manifest()
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"✅ manifest 寫出：{out_path}（engine {manifest['engine_version']}，"
          f"{len(manifest['strategies'])} 策略，{len(manifest['brokers'])} 券商）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
