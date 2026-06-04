"""CT-ALIGN — 跨產物版本/憑證對齊（fork 相容性計劃 §6.2）。

防止「各產物版本各走各的」的漂移，在 CI 就抓到，而非在某個 fork 的真錢帳戶爆。

涵蓋三個對齊契約：
  CT-ALIGN-VER  data.json 產出的 schema_version ⊆ 前端 mvp_dashboard 支援版本
  CT-ALIGN-RUN  每個 enabled 帳戶都有 workflow 會執行它（否則永遠不交易/不出報告）
  CT-ALIGN-SEC  執行某帳戶的 workflow，必須注入該帳戶（依 _source_map）所需的憑證 env
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── 共用解析 ──────────────────────────────────────────────────────────────────
def _enabled_accounts() -> list[dict]:
    data = json.loads((ROOT / "accounts.json").read_text(encoding="utf-8"))["accounts"]
    return [a for a in data if a.get("enabled", True)]


def _required_env_names(account: dict) -> set[str]:
    """此帳戶執行時，引擎會從 process env 讀取的憑證變數名（單一事實來源）。"""
    import run_account
    prefix = account.get("secret_prefix") or account.get("alpaca_secret_prefix")
    broker = account.get("broker", "alpaca")
    return set(run_account._source_map(prefix, broker).values())


def _workflows() -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8"))
            for p in (ROOT / ".github" / "workflows").glob("*.yml")]


def _accounts_run_by(wf_text: str) -> set[str]:
    """workflow 內 `run_account.py --account X` 的 X 集合（可能含 'all'）。"""
    return set(re.findall(r"run_account\.py\s+--account\s+(\w+)", wf_text))


def _env_names_defined(wf_text: str) -> set[str]:
    """workflow `env:` 區塊定義、且綁到 ${{ secrets.* }} 的變數名。"""
    return set(re.findall(r"^\s*([A-Z][A-Z0-9_]+):\s*\$\{\{", wf_text, re.M))


# ── CT-ALIGN-VER ─────────────────────────────────────────────────────────────
def test_dashboard_supports_emitted_schema_version():
    from engine.data_writer import SCHEMA_VERSION
    html = (ROOT / "mvp_dashboard.html").read_text(encoding="utf-8")
    supported = set(re.findall(r'SUPPORTED_SCHEMA_VERSION\s*=\s*"([^"]+)"', html))
    assert supported, "mvp_dashboard.html 找不到 SUPPORTED_SCHEMA_VERSION"
    assert SCHEMA_VERSION in supported, (
        f"data.json 產出 schema_version={SCHEMA_VERSION!r}，但前端只支援 {supported}。"
        " 改 data_writer.SCHEMA_VERSION 時必須同步 mvp_dashboard.html，否則使用者看到"
        "「版本不相容」橫幅。")


# ── CT-ALIGN-RUN ─────────────────────────────────────────────────────────────
def test_every_enabled_account_is_run_by_a_workflow():
    wfs = _workflows()
    unwired = []
    for acct in _enabled_accounts():
        aid = acct["id"]
        if not any((aid in _accounts_run_by(t)) or ("all" in _accounts_run_by(t))
                   for _, t in wfs):
            unwired.append(f"#{aid}({acct.get('strategy')})")
    assert not unwired, (
        "啟用但沒有任何 workflow 執行的帳戶（會永遠不交易/不出每日報告）："
        + ", ".join(unwired))


# ── CT-ALIGN-SEC ─────────────────────────────────────────────────────────────
def test_workflow_injects_required_credentials():
    wfs = _workflows()
    violations = []
    for acct in _enabled_accounts():
        aid = acct["id"]
        need = _required_env_names(acct)
        providing: set[str] = set()
        for _, t in wfs:
            runners = _accounts_run_by(t)
            if aid in runners or "all" in runners:
                providing |= _env_names_defined(t)
        missing = need - providing
        if missing:
            violations.append(f"#{aid}: 缺 {sorted(missing)}")
    assert not violations, (
        "下列帳戶在執行它的 workflow 中缺少憑證 env 注入（會因金鑰未設而停止交易）：\n  "
        + "\n  ".join(violations))
