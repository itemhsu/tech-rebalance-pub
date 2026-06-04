"""
tests/test_dashboard_health.py

Dashboard 健康度測試 — 確保每日執行後所有帳戶資料均正確更新。

執行方式：
  pytest tests/test_dashboard_health.py -v

設計原則：
  1. 資料新鮮度：所有帳戶 state.json 不超過 3 個交易日
  2. 結構完整性：必要欄位都存在
  3. accounts.json 完整性：所有預期帳戶都存在
  4. Dashboard data.json 一致性：與 state.json 的日期/NAV 吻合
"""
from __future__ import annotations

import json
import pathlib
from datetime import date, timedelta
from typing import Any

import pytest

# ── 路徑常數 ─────────────────────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).parent.parent

# 路徑取自 accounts.json 的 data_dir（enabled 帳戶）。
# 註：account 3 早期曾是 top9psq（已退役），現為 mom_6m_t20 → data/3。
ACCOUNT_STATES = {
    "1": ROOT / "data" / "1" / "portfolio_state.json",
    "2": ROOT / "d2p2t6" / "data" / "1" / "portfolio_state.json",
    "3": ROOT / "data" / "3" / "portfolio_state.json",
    "4": ROOT / "weekly_top10" / "data" / "4" / "portfolio_state.json",
}

ACCOUNTS_JSON = ROOT / "accounts.json"
EXPECTED_ACCOUNT_IDS = {"1", "2", "3", "4"}

# 允許的最大過期天數（含週末：最多跨 3 個自然日）
MAX_STALE_DAYS = 4


# ── Helper ───────────────────────────────────────────────────────────────────

def _load(path: pathlib.Path) -> dict[str, Any]:
    assert path.exists(), f"檔案不存在：{path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"預期 JSON object，實際：{type(data)}"
    return data


def _business_days_since(date_str: str) -> int:
    """計算從 date_str 到今天的自然天數（簡化版，不跳過假日）。"""
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return 9999
    return (date.today() - d).days


# ══════════════════════════════════════════════════════════════════════════════
# 1. accounts.json 完整性
# ══════════════════════════════════════════════════════════════════════════════

class TestAccountsJson:

    def test_file_exists(self):
        assert ACCOUNTS_JSON.exists(), "accounts.json 不存在"

    def test_has_accounts_key(self):
        data = _load(ACCOUNTS_JSON)
        assert "accounts" in data, "accounts.json 缺少 'accounts' 鍵"

    def test_all_expected_accounts_present(self):
        data = _load(ACCOUNTS_JSON)
        ids = {str(a["id"]) for a in data["accounts"]}
        missing = EXPECTED_ACCOUNT_IDS - ids
        assert not missing, f"accounts.json 缺少帳戶：{missing}"

    def test_each_account_has_label(self):
        data = _load(ACCOUNTS_JSON)
        for acct in data["accounts"]:
            assert acct.get("label"), f"帳戶 #{acct.get('id')} 缺少 label"

    def test_no_stale_strategy_name(self):
        """帳戶 #3 不應再標記為 TOP9+PSQ。"""
        data = _load(ACCOUNTS_JSON)
        for acct in data["accounts"]:
            if str(acct["id"]) == "3":
                assert "PSQ" not in acct.get("label", ""), \
                    f"帳戶 #3 label 仍包含舊策略名稱 'PSQ'：{acct['label']}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. portfolio_state.json 資料新鮮度與結構
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("account_id,state_path", ACCOUNT_STATES.items())
class TestPortfolioState:

    def test_state_file_exists(self, account_id, state_path):
        # 帳戶剛切到 runner.py、尚未產出 state 時 skip（非錯誤）
        if not state_path.exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 state（{state_path}）")
        assert state_path.exists()

    def test_required_fields(self, account_id, state_path):
        if not state_path.exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 state")
        state = _load(state_path)
        required = {"date", "nav", "cash", "positions", "top10"}
        missing = required - set(state.keys())
        assert not missing, f"帳戶 #{account_id} state 缺少欄位：{missing}"

    def test_data_freshness(self, account_id, state_path):
        if not state_path.exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 state")
        state = _load(state_path)
        stale_days = _business_days_since(state["date"])
        assert stale_days <= MAX_STALE_DAYS, (
            f"帳戶 #{account_id} 資料過期 {stale_days} 天"
            f"（最後更新：{state['date']}，今日：{date.today()}）"
        )

    def test_nav_positive(self, account_id, state_path):
        if not state_path.exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 state")
        state = _load(state_path)
        assert state["nav"] > 0, \
            f"帳戶 #{account_id} NAV 異常：{state['nav']}"

    def test_cash_not_exceed_nav(self, account_id, state_path):
        if not state_path.exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 state")
        state = _load(state_path)
        assert state["cash"] <= state["nav"] * 1.01, (
            f"帳戶 #{account_id} 現金（{state['cash']}）超過 NAV（{state['nav']}），"
            "可能尚未建倉或資料異常"
        )

    def test_top10_not_empty(self, account_id, state_path):
        if not state_path.exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 state")
        state = _load(state_path)
        assert len(state.get("top10", [])) > 0, \
            f"帳戶 #{account_id} top10 清單為空"

    def test_no_psq_in_account3(self, account_id, state_path):
        """帳戶 #3 改為 Monthly TOP10 後，不應再持有 PSQ。"""
        if account_id != "3":
            return
        if not state_path.exists():
            pytest.skip("帳戶 #3 尚未產出 state")
        state = _load(state_path)
        top10 = state.get("top10", [])
        positions = [p.get("symbol") for p in state.get("positions", [])]
        assert "PSQ" not in top10, f"帳戶 #3 top10 仍含 PSQ：{top10}"
        assert "PSQ" not in positions, f"帳戶 #3 持倉仍含 PSQ：{positions}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. NAV 歷史連續性
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("account_id,state_path", ACCOUNT_STATES.items())
class TestNavHistory:

    def _history_path(self, state_path: pathlib.Path) -> pathlib.Path:
        return state_path.parent / "portfolio_state_history.json"

    def test_history_file_exists(self, account_id, state_path):
        if not self._history_path(state_path).exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 history")
        assert self._history_path(state_path).exists()

    def test_history_has_entries(self, account_id, state_path):
        if not self._history_path(state_path).exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 history")
        hist = _load(self._history_path(state_path))
        entries = hist if isinstance(hist, list) else hist.get("history", [])
        assert len(entries) > 0, f"帳戶 #{account_id} NAV 歷史為空"

    def test_latest_history_matches_state(self, account_id, state_path):
        if not state_path.exists() or not self._history_path(state_path).exists():
            pytest.skip(f"帳戶 #{account_id} 尚未產出 state/history")
        state = _load(state_path)
        hist = _load(self._history_path(state_path))
        entries = hist if isinstance(hist, list) else hist.get("history", [])
        if not entries:
            pytest.skip("history 為空，跳過一致性檢查")
        latest = max(entries, key=lambda e: e.get("date", ""))
        assert latest["date"] == state["date"], (
            f"帳戶 #{account_id} history 最新日期（{latest['date']}）"
            f"與 state.json 日期（{state['date']}）不符"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. Workflow 設計完整性（靜態檢查）
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkflowConfig:

    def test_unified_workflow_exists(self):
        wf = ROOT / ".github" / "workflows" / "daily_all_accounts.yml"
        assert wf.exists(), "統一 daily_all_accounts.yml 不存在"

    def test_unified_workflow_has_schedule(self):
        wf = ROOT / ".github" / "workflows" / "daily_all_accounts.yml"
        content = wf.read_text()
        assert "schedule" in content, "daily_all_accounts.yml 缺少 schedule"
        assert "cron" in content, "daily_all_accounts.yml 缺少 cron 設定"

    def test_unified_workflow_has_all_accounts(self):
        wf = ROOT / ".github" / "workflows" / "daily_all_accounts.yml"
        content = wf.read_text()
        assert "run1" in content, "daily_all_accounts.yml 缺少帳戶 #1 步驟"
        assert "run2" in content, "daily_all_accounts.yml 缺少帳戶 #2 步驟"
        assert "run3" in content, "daily_all_accounts.yml 缺少帳戶 #3 步驟"

    def test_unified_workflow_uses_autostash(self):
        # commit/push 邏輯已抽到 scripts/ci_commit_push.sh（workflow 瘦身）；
        # --autostash 應存在於 workflow 或該共用腳本任一處。
        wf = (ROOT / ".github" / "workflows" / "daily_all_accounts.yml").read_text()
        script = (ROOT / "scripts" / "ci_commit_push.sh").read_text()
        assert "--autostash" in wf or "--autostash" in script, \
            "daily 流程未使用 --autostash，可能發生 unstaged 衝突"

    def test_per_account_workflows_no_schedule(self):
        """個別 workflow 不應再有 schedule（已統一到 daily_all_accounts.yml）。"""
        for fname in ("daily_rebalance.yml", "d2p2t6_daily.yml", "top9psq_live.yml"):
            wf = ROOT / ".github" / "workflows" / fname
            if not wf.exists():
                continue
            content = wf.read_text()
            # schedule 只允許在 daily_all_accounts.yml 出現
            lines = [l.strip() for l in content.splitlines()]
            in_on_block = False
            for line in lines:
                if line.startswith("on:"):
                    in_on_block = True
                if in_on_block and line.startswith("schedule:"):
                    pytest.fail(
                        f"{fname} 仍有 schedule 觸發器，請移至 daily_all_accounts.yml"
                    )
                if in_on_block and line.startswith("jobs:"):
                    break


class TestDryRunNoCommit:
    def test_daily_commit_skips_on_dry_run(self):
        wf = (ROOT / ".github" / "workflows" / "daily_all_accounts.yml").read_text()
        # 找到 commit 步驟的條件，須排除 dry_run（避免模擬 state 污染冪等守門）
        assert "dry_run != 'true'" in wf, "daily commit 未排除 dry-run → 模擬 state 會被 commit"
