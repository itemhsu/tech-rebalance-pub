"""engine/paths.py — 區分「引擎自帶資產」與「使用者工作目錄」（兩 repo 架構地基）。

兩種根：
  package_root()  引擎隨碼走的資產：strategies/ schemas/ brokers/ 參考資料（universe / shares）
  workdir()       使用者的設定與資料：accounts.json + data/{id}/

關鍵：workdir() 預設 = package_root()，所以未設 TR_WORKDIR 時行為與舊版逐位元組相同
（零風險遷移）；未來兩 repo 模式只要設 TR_WORKDIR 指向 Repo B 的 checkout 即可分離。
"""
from __future__ import annotations

import os
from pathlib import Path


def package_root() -> Path:
    """引擎套件根目錄（engine/ 的上一層）。"""
    return Path(__file__).resolve().parent.parent


def workdir() -> Path:
    """使用者工作目錄（accounts.json + data/）。預設同 package_root()。

    設定環境變數 TR_WORKDIR 可指向外部目錄（兩 repo 模式：Repo B 的 checkout）。
    """
    wd = os.environ.get("TR_WORKDIR")
    return Path(wd) if wd else package_root()
