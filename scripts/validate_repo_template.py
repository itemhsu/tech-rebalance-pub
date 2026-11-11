#!/usr/bin/env python3
"""scripts/validate_repo_template.py — repo_template.json 守門驗證器。

三層中的第二層（一致性檢查）。第一層由 JSON Schema 完成（先執行）。
任何一項失敗 → 非零退出，CI 紅燈擋下 merge。

檢查項目：
  schema  repo_template.json 符合 schemas/repo-template-schema-v1.json
  V4      同 section 內 path 不重複
  V5      每個 render 的 src 在 templates/ 真存在
  V6      templates/ 每個檔都被某個 render 引用（無孤兒）← 核心防護
  V7      path 不含 '..'、不以 '/' 開頭（路徑逃逸）
  V8      範本不得把引擎釘死在 `pub@{version}`；必須走 `vars.ENGINE_VERSION`（{version} 只當後援）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "repo_template.json"
SCHEMA = ROOT / "schemas" / "repo-template-schema-v1.json"
TEMPLATES_DIR = ROOT / "templates"

_SECTIONS = ("repo_b", "dashboard")


def _fail(msg: str) -> None:
    print(f"❌ {msg}")


def main() -> int:
    errors: list[str] = []

    # ── 載入 ─────────────────────────────────────────────────────────────
    if not MANIFEST.exists():
        _fail(f"找不到 {MANIFEST.name}")
        return 1
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"repo_template.json 非合法 JSON：{e}")
        return 1

    # ── 第一層：JSON Schema ──────────────────────────────────────────────
    try:
        import jsonschema
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(manifest, schema)
        print("✅ schema 通過")
    except FileNotFoundError:
        errors.append(f"找不到 schema：{SCHEMA}")
    except Exception as e:  # noqa: BLE001  jsonschema.ValidationError 等
        errors.append(f"schema 驗證失敗：{e}")

    # 收集所有 render 用到的 src（給 V6 用）
    referenced_srcs: set[str] = set()

    # ── V4 / V5 / V7 ─────────────────────────────────────────────────────
    for section in _SECTIONS:
        entries = manifest.get(section, []) or []
        seen: set[str] = set()
        for e in entries:
            path = e.get("path", "")
            policy = e.get("policy", "")
            # V4 path 不重複
            if path in seen:
                errors.append(f"[{section}] path 重複：{path}")
            seen.add(path)
            # V7 路徑逃逸
            if path.startswith("/") or ".." in Path(path).parts:
                errors.append(f"[{section}] path 不安全（逃逸）：{path}")
            # V5 render 的 src 存在
            if policy == "render":
                src = e.get("src", "")
                referenced_srcs.add(src)
                if not (ROOT / src).is_file():
                    errors.append(f"[{section}] render src 不存在：{src}")

    # ── V6 templates/ 無孤兒 ─────────────────────────────────────────────
    if TEMPLATES_DIR.is_dir():
        for f in TEMPLATES_DIR.rglob("*"):
            if f.is_file():
                rel = str(f.relative_to(ROOT))
                if rel not in referenced_srcs:
                    errors.append(f"孤兒範本（templates/ 有檔但無 render 引用）：{rel}")

    # ── V8 引擎版本不得被渲染釘死 ────────────────────────────────────────
    # sync(render) 把 {version} 換成 release tag；若範本寫 `pub@{version}`，
    # 重渲染就會蓋掉 repo 的 vars.ENGINE_VERSION 控制（2026-10 事故：TW workflow
    # 被釘回 v1.0.21，用舊引擎覆蓋所有帳戶 dashboard）。
    if TEMPLATES_DIR.is_dir():
        for f in TEMPLATES_DIR.rglob("*.yml"):
            txt = f.read_text(encoding="utf-8")
            if "tech-rebalance-pub@{version}" in txt:
                errors.append(f"{f.relative_to(ROOT)}：引擎被釘死 pub@{{version}}，"
                              "請改 ${{ vars.ENGINE_VERSION || '{version}' }}")

    # ── 結果 ─────────────────────────────────────────────────────────────
    if errors:
        for m in errors:
            _fail(m)
        print(f"\n共 {len(errors)} 個錯誤")
        return 1
    print("✅ repo_template.json 全部驗證通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
