"""回歸：load_accounts 必須保留 broker/environment（否則 refresh_nav 誤判 alpaca）。"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.accounts import load_accounts, Account


def test_broker_field_preserved(tmp_path):
    p = tmp_path / "accounts.json"
    p.write_text(json.dumps({"accounts": [
        {"id": "6", "strategy": "tw_tech_top10", "label": "sini",
         "broker": "sinopac", "environment": "paper", "secret_prefix": "ACC6",
         "enabled": True}
    ]}), encoding="utf-8")
    accs = load_accounts(p)
    a = accs[0]
    assert isinstance(a, Account)
    assert a.broker == "sinopac"        # ★ 不再被白名單過濾掉
    assert a.environment == "paper"
