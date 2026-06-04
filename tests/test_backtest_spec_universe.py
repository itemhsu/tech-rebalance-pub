"""Regression：回測工具 spec_engine 必須支援 json_file universe source。

歷史 bug：top10.json 改用 json_file（指 data/universe.json）後，
backtest_anchor/tool_v2 的 spec_engine 只認 inline/csv_file → 回空 universe
→ momentum 每日回測 workflow FAILED top10。

用 subprocess 跑（與真實回測工具相同：fresh process 內 backtest 的 engine/
正確解析，避免與頂層 engine/ 套件在同進程衝突）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "backtest_anchor" / "tool_v2"


def _resolve(strategy_id: str) -> int:
    """在子進程載 backtest spec_engine，回傳該策略 universe source 解析到的檔數。"""
    code = (
        "import sys, json;"
        f"sys.path.insert(0, {str(TOOL)!r});"
        "from engine.spec_engine import SpecEngine;"
        f"spec=json.load(open({str(ROOT / 'strategies')!r}+'/'+{strategy_id!r}+'.json'));"
        "e=SpecEngine.__new__(SpecEngine); e.strategy_id='t';"
        "print(len(e._load_source(spec['universe']['source'])))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, f"子進程失敗：{out.stderr[-400:]}"
    return int(out.stdout.strip().splitlines()[-1])


def test_top10_json_file_resolves_nonempty():
    n = _resolve("top10")
    assert n >= 20, f"top10 universe 不該為空，實際 {n}"


def test_top10_v3_json_file_resolves_nonempty():
    n = _resolve("top10_v3")
    assert n >= 20, f"top10_v3 universe 不該為空，實際 {n}"
