#!/usr/bin/env python3
"""schema_compat.py — 偵測 JSON Schema 的「破壞性變更」（fork 相容性計劃 §6.2）。

破壞性變更 = 會讓「舊資料 × 新 schema」或「新資料 × 舊 schema」驗證失敗的改動，
這種改動會打爆所有還沒同步的 fork。規則：

  破壞（禁止，除非把檔名 bump 成新版 e.g. -v2→-v3）：
    - 新增 required 欄位
    - additionalProperties: true → false
    - 在 additionalProperties:false 下移除某 property
    - enum 移除既有值（收窄）
    - type 變更或收窄（[str,null] → str）
    - 數值/長度界限收窄（minimum↑ / maximum↓ / minLength↑ / maxLength↓ / 新增界限）
    - 新增或變更 pattern

  非破壞（允許，加法）：
    - 新增 optional property
    - 移除 required 條目（放寬）
    - enum 加入新值（放大）
    - additionalProperties: false → true
    - 放寬界限

用法：
    python scripts/schema_compat.py OLD.json NEW.json     # 破壞→exit 1 並列出
"""
from __future__ import annotations

import json
import sys
from typing import Any, List


def _type_widened(old: Any, new: Any) -> bool:
    """新 type 是否為舊 type 的超集（放寬，非破壞）。"""
    o = set(old if isinstance(old, list) else [old])
    n = set(new if isinstance(new, list) else [new])
    return o.issubset(n)


def _enum_key(v: Any):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def breaking_changes(old: Any, new: Any, path: str = "$") -> List[str]:
    """回傳 old→new 的破壞性變更敘述清單（空＝相容）。"""
    out: List[str] = []
    if not isinstance(old, dict) or not isinstance(new, dict):
        return out

    # required 新增
    old_req, new_req = set(old.get("required", [])), set(new.get("required", []))
    for r in sorted(new_req - old_req):
        out.append(f"{path}: 新增 required 欄位 '{r}'（舊資料可能缺→破壞）")

    # type 變更/收窄
    if "type" in old and "type" in new and old["type"] != new["type"]:
        if not _type_widened(old["type"], new["type"]):
            out.append(f"{path}: type {old['type']!r} → {new['type']!r}（變更/收窄→破壞）")

    # enum 收窄
    if "enum" in old and "enum" in new:
        removed = {_enum_key(v) for v in old["enum"]} - {_enum_key(v) for v in new["enum"]}
        if removed:
            out.append(f"{path}: enum 移除值 {sorted(removed)}（舊資料含此值→破壞）")

    # additionalProperties 收緊
    oap = old.get("additionalProperties", True)
    nap = new.get("additionalProperties", True)
    if oap is True and nap is False:
        out.append(f"{path}: additionalProperties true→false（舊的額外欄位被拒→破壞）")

    old_props = old.get("properties", {})
    new_props = new.get("properties", {})

    # additionalProperties:false 下移除 property
    if nap is False:
        for k in sorted(set(old_props) - set(new_props)):
            out.append(f"{path}.properties: 移除 '{k}'（additionalProperties:false 下舊資料含它→破壞）")

    # 界限收窄 / 新增界限
    for key, tighter in (("minimum", lambda o, n: n > o),
                         ("minLength", lambda o, n: n > o),
                         ("maximum", lambda o, n: n < o),
                         ("maxLength", lambda o, n: n < o)):
        if key in new and key not in old:
            out.append(f"{path}: 新增約束 {key}={new[key]}（舊資料可能違反→破壞）")
        elif key in old and key in new and tighter(old[key], new[key]):
            out.append(f"{path}: {key} 收窄 {old[key]}→{new[key]}（→破壞）")

    # pattern 新增/變更
    if new.get("pattern") and old.get("pattern") != new.get("pattern"):
        out.append(f"{path}: pattern {old.get('pattern')!r}→{new.get('pattern')!r}（→破壞）")

    # 遞迴：共有的 properties
    for k in sorted(set(old_props) & set(new_props)):
        out += breaking_changes(old_props[k], new_props[k], f"{path}.{k}")

    # 遞迴：items / if / then / else（data-schema 用到 if/then/else）
    for kw in ("items", "if", "then", "else"):
        if isinstance(old.get(kw), dict) and isinstance(new.get(kw), dict):
            sep = "[]" if kw == "items" else f".{kw}"
            out += breaking_changes(old[kw], new[kw], f"{path}{sep}")

    return out


def main(argv: List[str]) -> int:
    if len(argv) != 3:
        print("用法：python scripts/schema_compat.py OLD.json NEW.json", file=sys.stderr)
        return 2
    old = json.loads(open(argv[1], encoding="utf-8").read())
    new = json.loads(open(argv[2], encoding="utf-8").read())
    changes = breaking_changes(old, new)
    if changes:
        print(f"❌ 偵測到 {len(changes)} 項破壞性 schema 變更：")
        for c in changes:
            print(f"  - {c}")
        print("\n如為刻意破版：請把檔名 bump（如 -v2 → -v3），保留舊版檔不動。")
        return 1
    print("✅ 無破壞性變更（相容）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
