"""把 accounts.json 列出的每個帳戶 data_dir 加入 git staging。"""
import json
import pathlib
import subprocess

import os as _os
ROOT = pathlib.Path(_os.environ.get("TR_WORKDIR") or pathlib.Path(__file__).resolve().parent.parent)


def main() -> int:
    accounts = json.loads((ROOT / "accounts.json").read_text())["accounts"]
    dirs = [a["data_dir"] for a in accounts if a.get("data_dir")]

    for d in dirs:
        if (ROOT / d).exists():
            subprocess.run(["git", "add", d], check=False)

    subprocess.run(["git", "add", "README.md", "accounts.json"], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
