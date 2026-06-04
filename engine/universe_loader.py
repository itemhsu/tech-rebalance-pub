"""統一 universe loader — 從 v3 spec 解析 {group_id: [symbols]}。

支援 source.type：
  - inline     {"symbols": [...]}
  - csv_file   {"path": "...", "symbol_column": "..."}
  - json_file  {"path": "...", "key": "stocks"}  ← 從 JSON 取 array

支援 universe.type：
  - single    → {"__all__": [...]}
  - grouped   → {group_id: [...]} （每個 group 各有 source）

設計原則：fail loud — 未知 source.type、CSV 解析失敗、JSON key 不存在
都會 raise，不能靜默 fallback 到別的 universe（這曾經是隱蔽 bug）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

from engine.paths import package_root

# universe 定義是引擎自帶資產 → package_root()（保留 _ROOT 名稱供既有測試 monkeypatch）
_ROOT = package_root()
logger = logging.getLogger("universe_loader")


def _load_inline(source: dict) -> List[str]:
    return [str(s).upper() for s in (source.get("symbols") or [])]


def _load_csv(source: dict) -> List[str]:
    path_str = source.get("path", "")
    col = source.get("symbol_column", "symbol")
    csv_path = _ROOT / path_str
    if not csv_path.exists():
        raise FileNotFoundError(f"universe CSV 不存在：{csv_path}")
    import pandas as pd
    df = pd.read_csv(csv_path)
    if col not in df.columns:
        raise KeyError(
            f"CSV {csv_path} 缺欄位 {col!r}；現有欄位 {list(df.columns)}"
        )
    return [str(s).upper() for s in df[col].tolist()]


def _load_json(source: dict) -> List[str]:
    path_str = source.get("path", "")
    key = source.get("key", "stocks")
    json_path = _ROOT / path_str
    if not json_path.exists():
        raise FileNotFoundError(f"universe JSON 不存在：{json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if key not in data:
        raise KeyError(
            f"JSON {json_path} 缺 key {key!r}；現有 keys {list(data.keys())}"
        )
    syms = data[key]
    if not isinstance(syms, list):
        raise TypeError(
            f"JSON {json_path}.{key} 必須是 list，實際是 {type(syms).__name__}"
        )
    return [str(s).upper() for s in syms]


_SOURCE_LOADERS = {
    "inline":    _load_inline,
    "csv_file":  _load_csv,
    "json_file": _load_json,
}


def _load_source(source: dict, context: str) -> List[str]:
    st = source.get("type")
    loader = _SOURCE_LOADERS.get(st)
    if loader is None:
        raise ValueError(
            f"{context}.source.type={st!r} 不支援；"
            f"請用 {sorted(_SOURCE_LOADERS)} 之一"
        )
    return loader(source)


def load_universe_groups(spec: dict) -> Dict[str, List[str]]:
    """從 spec.universe 解析 {group_id: [symbols]}。"""
    u = spec.get("universe", {})
    utype = u.get("type")

    if utype == "single":
        return {"__all__": _load_source(u.get("source", {}), "universe")}

    if utype == "grouped":
        out: Dict[str, List[str]] = {}
        for g in u.get("groups", []):
            gid = g["id"]
            out[gid] = _load_source(g.get("source", {}), f"universe.groups[{gid}]")
        return out

    raise ValueError(
        f"universe.type={utype!r} 不支援；請用 'single' 或 'grouped'"
    )


def all_symbols(groups: Dict[str, List[str]]) -> List[str]:
    """攤平 group 字典為唯一 symbol list（保序）。"""
    seen, out = set(), []
    for syms in groups.values():
        for s in syms:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out
