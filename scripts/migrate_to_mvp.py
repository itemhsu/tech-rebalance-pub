"""scripts/migrate_to_mvp.py — 產生 MVP dashboard 資料（純資料驅動）。

歷史：本檔曾有 migrate_top10() / migrate_d2p2t6() 兩個「每策略硬寫」的函式，
違反 JSON-driven 設計。已移除——改由 engine.report_generator 對 accounts.json
逐帳戶通用產生（分組排名也通用化，讀 latest_rankings.json）。通用 helper 已搬進
engine.mvp_helpers（進 wheel，薄殼可用）。本檔保留為 CLI 入口 + 向後相容 re-export。

用法：
  python scripts/migrate_to_mvp.py [--strategy all|<id>] [--output-dir DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# 向後相容：舊程式/測試仍可 `from scripts.migrate_to_mvp import _extract_nav_history` 等
from engine.mvp_helpers import (   # noqa: F401
    _load_json, _extract_history_list, _extract_nav_history, _extract_trade_log,
    _load_benchmark_drawdown, _align_benchmark, _compute_benchmark_nav,
    _save_dated_snapshot,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate")


def main():
    parser = argparse.ArgumentParser(description="產生 MVP dashboard 資料（資料驅動）")
    parser.add_argument("--output-dir", default=str(ROOT / "mvp_data"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strategy", default="all",
                        help="all＝所有 enabled 帳戶；或單一帳戶 id（手動單跑）")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.strategy == "all":
        from engine.report_generator import generate_all
        results = generate_all(output_dir, dry_run=args.dry_run)
        for aid, st in results.items():
            logger.info("  帳戶 #%s：%s", aid, st)
        if any(v == "fail" for v in results.values()):
            logger.error("部分帳戶報告產生失敗")
            sys.exit(1)
        logger.info("✅ 報告產生完成（資料驅動）！輸出目錄：%s", output_dir)
        return

    # 單一帳戶（手動單跑用）—— 一樣走通用產生器，依 account id
    from engine.report_generator import generate_for_account
    from engine.accounts import get_account
    st = generate_for_account(get_account(args.strategy), output_dir, dry_run=args.dry_run)
    logger.info("✅ 帳戶 #%s：%s", args.strategy, st)
    if st == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
