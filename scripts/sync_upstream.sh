#!/usr/bin/env bash
# sync_upstream.sh — fork 從上游 itemhsu/tech-rebalance 拉取修復（fork 相容性計劃 §5）。
#
# 解決 fork 最高風險：workflow / 引擎碼 / schema 被 fork 複製走後，拿不到上游修復。
# 本腳本把上游的改動合併進來，同時「保留 fork 私有檔」（帳戶設定、各帳戶資料目錄），
# 不讓上游覆蓋你的 accounts.json / data/。
#
# 用法：
#   bash scripts/sync_upstream.sh --dry-run     # 只看上游有什麼新東西，不改動
#   bash scripts/sync_upstream.sh               # 實際合併（自動保留私有檔）
#
# 環境變數：
#   UPSTREAM_URL   上游 repo（預設 https://github.com/itemhsu/tech-rebalance）
#   UPSTREAM_BRANCH 上游分支（預設 main）
set -euo pipefail

UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/itemhsu/tech-rebalance}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# fork 私有、不可被上游覆蓋的路徑（合併衝突時一律保留本地版本）
PRIVATE_PATHS=(
  "accounts.json"
  "data"
  "d2p2t6/data"
  "weekly_top10/data"
)

say() { printf '\033[36m▶ %s\033[0m\n' "$*"; }
err() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; }

# 2) 確保 upstream remote 存在
if ! git remote get-url upstream >/dev/null 2>&1; then
  say "新增 upstream remote → $UPSTREAM_URL"
  git remote add upstream "$UPSTREAM_URL"
fi

say "抓取 upstream/$UPSTREAM_BRANCH …"
git fetch --quiet upstream "$UPSTREAM_BRANCH"

# 3) 顯示即將進來的改動
INCOMING="$(git rev-list --count "HEAD..upstream/${UPSTREAM_BRANCH}")"
if [ "$INCOMING" = "0" ]; then
  say "已是最新，無上游更新。"
  exit 0
fi
say "上游有 $INCOMING 個新 commit："
git log --oneline "HEAD..upstream/${UPSTREAM_BRANCH}" | sed 's/^/    /'
echo
say "受影響檔案："
git diff --stat "HEAD..upstream/${UPSTREAM_BRANCH}" | sed 's/^/    /'

if [ "$DRY_RUN" = "1" ]; then
  echo
  say "（--dry-run）未改動任何東西。移除 --dry-run 即實際合併。"
  exit 0
fi

# 4) 實際合併前：工作目錄必須乾淨（dry-run 已在上面提前返回）
if [ -n "$(git status --porcelain)" ]; then
  err "工作目錄有未提交變更，請先 commit 或 stash 再同步。"
  exit 1
fi

say "合併中（私有檔將保留本地版本）…"
if ! git merge --no-ff --no-commit "upstream/${UPSTREAM_BRANCH}" >/dev/null 2>&1; then
  : # 有衝突，下面處理
fi

# 5) 私有檔一律用本地版本（fork 自己的設定/資料）
for p in "${PRIVATE_PATHS[@]}"; do
  if git ls-files --error-unmatch "$p" >/dev/null 2>&1 || [ -e "$p" ]; then
    git checkout --ours -- "$p" 2>/dev/null || true
    git add -- "$p" 2>/dev/null || true
  fi
done

# 6) 還有非私有衝突 → 中止，請使用者手動處理（避免留下半合併狀態）
UNMERGED="$(git diff --name-only --diff-filter=U || true)"
if [ -n "$UNMERGED" ]; then
  err "下列檔案有衝突（非私有），請手動解決後 git commit："
  echo "$UNMERGED" | sed 's/^/    /'
  err "或執行 git merge --abort 放棄本次同步。"
  exit 2
fi

git commit --quiet -m "sync: pull upstream fixes from ${UPSTREAM_URL}@${UPSTREAM_BRANCH}"
say "✅ 同步完成。私有檔（accounts.json / data/）已保留本地版本。"
say "建議接著跑：python -m pytest tests/test_compat_*.py  確認契約相容。"
