"""engine/upstream_check 測試（fork 相容性 §5：每日 email 落後提示）。

關鍵保證：任何失敗都回 None（絕不破壞/洗版每日郵件）；上游本尊→0→無提示。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine.upstream_check as uc


def _runner(map_):
    """回傳依命令前綴對應結果的假 runner。map_: list[(substr, returncode, stdout)]。"""
    def run(cmd, **k):
        joined = " ".join(cmd)
        for substr, rc, out in map_:
            if substr in joined:
                return SimpleNamespace(returncode=rc, stdout=out, stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="no match")
    return run


def test_identical_returns_zero(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    r = _runner([("commits/main", 0, "abc123\n")])
    assert uc.behind_count(runner=r) == 0


def test_behind_returns_count(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "local1")
    r = _runner([("commits/main", 0, "up9\n"), ("compare/", 0, "5\n")])
    assert uc.behind_count(runner=r) == 5


def test_api_failure_returns_none(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "local1")
    r = _runner([("commits/main", 1, "")])      # API 失敗
    assert uc.behind_count(runner=r) is None


def test_no_local_sha_returns_none(monkeypatch):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    r = _runner([("rev-parse", 1, "")])         # 取不到本地 sha
    assert uc.behind_count(runner=r) is None


def test_exception_returns_none(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "x")

    def boom(*a, **k):
        raise OSError("gh not found")
    assert uc.behind_count(runner=boom) is None


def test_notice_text_when_behind(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "local1")
    r = _runner([("commits/main", 0, "up9\n"), ("compare/", 0, "3\n")])
    n = uc.behind_notice(runner=r)
    assert n and "3" in n and "sync_upstream" in n


def test_notice_none_when_uptodate(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "same")
    r = _runner([("commits/main", 0, "same\n")])
    assert uc.behind_notice(runner=r) is None
