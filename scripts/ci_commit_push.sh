#!/usr/bin/env bash
# ci_commit_push.sh "<commit message>" — 提交已 staged 的變更並推送（CI 共用）。
#
# fork 相容性計劃（workflow 瘦身）：把每日 workflow 重複的
# 「commit → pull --rebase --autostash -X theirs → push」集中一處，
# 日後要改推送策略只需動這支腳本（fork pull 一次即得）。
#
# 行為：
#   - 無 staged 變更 → 不提交、直接成功返回（冪等，不會產生空 commit）
#   - 有變更 → commit、rebase 上遠端最新、push
set -euo pipefail

msg="${1:?用法: ci_commit_push.sh \"<commit message>\"}"
branch="${2:-main}"

if git diff --staged --quiet; then
  echo "無 staged 變更，跳過 commit"
  exit 0
fi

git commit -m "$msg"
git pull --rebase --autostash -X theirs origin "$branch"
git push
