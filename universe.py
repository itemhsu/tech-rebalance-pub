"""
universe.py — 股票宇宙管理
載入候選股票清單與流通股數，並驗證資料完整性。
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
UNIVERSE_PATH = DATA_DIR / "universe.json"
SHARES_PATH   = DATA_DIR / "shares_outstanding.json"


def load_universe(path: Path = UNIVERSE_PATH) -> list[str]:
    """從 universe.json 載入候選股票代號清單。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    symbols = data["stocks"]
    logger.info("載入股票宇宙：%d 檔（最後更新 %s）", len(symbols), data.get("last_updated", "?"))
    return symbols


def load_shares_outstanding(path: Path = SHARES_PATH) -> dict[str, int]:
    """從 shares_outstanding.json 載入流通股數。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    shares = {k: int(v) for k, v in data["shares"].items()}
    logger.info("載入流通股數：%d 檔（最後更新 %s）", len(shares), data.get("last_updated", "?"))
    return shares


def validate_universe(symbols: list[str], shares: dict[str, int]) -> None:
    """
    驗證所有候選股票都有對應的流通股數資料。
    若有缺漏，raise ValueError 並列出缺漏的代號。
    """
    missing = [s for s in symbols if s not in shares]
    if missing:
        raise ValueError(
            f"以下股票在 shares_outstanding.json 中缺少流通股數：{missing}\n"
            "請更新 data/shares_outstanding.json 後重新執行。"
        )
    logger.info("資料驗證通過：所有 %d 檔股票均有流通股數資料", len(symbols))
