"""對所有 enabled 帳戶執行 update_index.py。"""
import json
import pathlib
import subprocess

import os as _os
ROOT = pathlib.Path(_os.environ.get("TR_WORKDIR") or pathlib.Path(__file__).resolve().parent.parent)


def main() -> int:
    accounts = json.loads((ROOT / "accounts.json").read_text())["accounts"]
    for a in accounts:
        if a.get("enabled", True):
            subprocess.run(
                ["python", "scripts/update_index.py",
                 "--account", str(a["id"]), "--output-dir", "mvp_data"],
                check=False,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
