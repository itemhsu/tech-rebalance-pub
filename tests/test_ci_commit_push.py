"""scripts/ci_commit_push.sh 行為驗證（fork 相容性：workflow 瘦身）。

用本機 bare remote 完整模擬 CI 的 commit→rebase→push，證明：
  - 無 staged 變更 → 不產生 commit（冪等）
  - 有變更 → commit 並 push 成功
無法在此環境觸發真實每日 workflow，故以此 hermetic 模擬替代驗證。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci_commit_push.sh"


def _git(args, cwd, **k):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "HOME": str(cwd), "PATH": __import__("os").environ["PATH"]}
    return subprocess.run(["git", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, **k)


def _setup(tmp_path):
    """建 bare remote + 一個 clone（含初始 commit）。回傳 work dir。"""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(["init", "--bare", "-b", "main", str(bare)], cwd=tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    _git(["init", "-b", "main"], cwd=work)
    _git(["remote", "add", "origin", str(bare)], cwd=work)
    (work / "seed.txt").write_text("seed")
    _git(["add", "."], cwd=work)
    _git(["commit", "-m", "seed"], cwd=work)
    _git(["push", "-u", "origin", "main"], cwd=work)
    return work


def _run_script(work, msg):
    return subprocess.run(["bash", str(SCRIPT), msg], cwd=work,
                          capture_output=True, text=True)


def test_bash_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_no_staged_changes_is_noop(tmp_path):
    work = _setup(tmp_path)
    before = _git(["rev-parse", "HEAD"], cwd=work).stdout.strip()
    r = _run_script(work, "should-not-commit")
    assert r.returncode == 0
    after = _git(["rev-parse", "HEAD"], cwd=work).stdout.strip()
    assert before == after, "無變更卻產生了 commit"
    assert "跳過" in r.stdout


def test_staged_change_commits_and_pushes(tmp_path):
    work = _setup(tmp_path)
    (work / "new.txt").write_text("data")
    _git(["add", "new.txt"], cwd=work)
    r = _run_script(work, "chore: add new")
    assert r.returncode == 0, r.stderr
    # 本地有新 commit
    assert _git(["log", "--oneline"], cwd=work).stdout.count("\n") >= 2
    # 遠端也收到了（log 含訊息）
    log = _git(["log", "origin/main", "--oneline"], cwd=work).stdout
    assert "add new" in log
