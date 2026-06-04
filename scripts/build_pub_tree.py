#!/usr/bin/env python3
"""scripts/build_pub_tree.py — 依白名單建公開鏡像樹 + 安全掃描（pub 拆分 S1）。

把 scripts/pub_allowlist.txt 列出的檔案複製到目標目錄，再做雙重安全掃描：
  1) 路徑禁列：帳戶設定/狀態、.env、live workflow 等絕不可出現
  2) 內容掃描：未去敏 email、GitHub PAT 樣式

任何違規 → 非零退出、不產出可用樹（寧可不推，不可外洩）。

用法：python scripts/build_pub_tree.py <輸出目錄>
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "scripts" / "pub_allowlist.txt"

# 路徑禁列：產出樹內若出現任一 → 中止（白名單之外的第二道防線）
DENY_PATH_GLOBS = [
    "accounts.json", ".env",
    "data/[0-9]*", "data/[0-9]*/**",
    "data/portfolio_state.json", "data/portfolio_state_history.json",
    "data/email_send_log.jsonl", "data/benchmark_365_cache.json",
    "**/trade_events.jsonl",
    "d2p2t6/data/**", "weekly_top10/data/**", "mom_6m_t20/**", "top9psq/**",
    ".github/workflows/daily_all_accounts.yml",
    ".github/workflows/harvest.yml",
    ".github/workflows/email_watchdog.yml",
    ".github/workflows/test_email.yml",
    ".github/workflows/tradier_smoke.yml",
    ".github/workflows/momentum_tool_v2.yml",
]

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_PAT_RE = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_EMAIL_OK = ("example.com", "noreply", "users.noreply", "github-actions")


# ── 白名單解析 ────────────────────────────────────────────────────────────────
def parse_allowlist() -> tuple[list[str], list[str]]:
    includes, excludes = [], []
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        (excludes if line.startswith("!") else includes).append(line.lstrip("!"))
    return includes, excludes


def _glob_files(pattern: str) -> set[str]:
    out = set()
    for p in glob.glob(str(ROOT / pattern), recursive=True):
        if os.path.isfile(p):
            out.add(os.path.relpath(p, ROOT))
    return out


def selected_files() -> set[str]:
    includes, excludes = parse_allowlist()
    keep: set[str] = set()
    for pat in includes:
        keep |= _glob_files(pat)
    drop: set[str] = set()
    for pat in excludes:
        drop |= _glob_files(pat)
    return keep - drop


# ── 安全掃描 ──────────────────────────────────────────────────────────────────
def scan_tree(dest: Path) -> list[str]:
    """回傳違規清單（空＝乾淨）。"""
    violations: list[str] = []
    # 1) 路徑禁列（過濾掉 glob 對不存在路徑回傳字面值的 quirk）
    for pat in DENY_PATH_GLOBS:
        for p in glob.glob(str(dest / pat), recursive=True):
            if os.path.exists(p):
                violations.append(f"禁列路徑：{os.path.relpath(p, dest)}")
    # 2) 內容掃描
    for f in dest.rglob("*"):
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in _EMAIL_RE.findall(text):
            if not any(ok in m for ok in _EMAIL_OK):
                violations.append(f"未去敏 email：{m}（{f.relative_to(dest)}）")
        if _PAT_RE.search(text):
            violations.append(f"疑似 GitHub PAT（{f.relative_to(dest)}）")
    return sorted(set(violations))


def build(dest: Path) -> int:
    if dest.exists():
        shutil.rmtree(dest)
    files = selected_files()
    for rel in sorted(files):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    print(f"複製 {len(files)} 個檔到 {dest}")
    violations = scan_tree(dest)
    if violations:
        print(f"\n❌ 安全掃描發現 {len(violations)} 項違規，中止：")
        for v in violations:
            print(f"  - {v}")
        shutil.rmtree(dest, ignore_errors=True)
        return 1
    print("✅ 安全掃描通過（無個資/金鑰）")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：python scripts/build_pub_tree.py <輸出目錄>", file=sys.stderr)
        return 2
    return build(Path(argv[1]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
