"""把每帳戶的 trade_events.jsonl 複製到 mvp_data/<id>/，供 log HTML viewer fetch。"""
import json
import pathlib
import shutil

import os as _os
ROOT = pathlib.Path(_os.environ.get("TR_WORKDIR") or pathlib.Path(__file__).resolve().parent.parent)
MVP_DIR = ROOT / "mvp_data"


def main() -> int:
    accounts = json.loads((ROOT / "accounts.json").read_text())["accounts"]
    copied = 0
    for a in accounts:
        aid = str(a["id"])
        data_dir = a.get("data_dir")
        if not data_dir:
            continue
        src = ROOT / data_dir / "trade_events.jsonl"
        dst = MVP_DIR / aid / "trade_events.jsonl"
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  ✓ {src} → {dst}")
            copied += 1
        else:
            print(f"  · {src} 不存在，跳過")
    print(f"copied {copied} event files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
