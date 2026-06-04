# Repo B 範本 — 你的交易系統（薄殼）

兩 repo 架構的「使用者端」：本 repo 只放 **設定 + 資料 + 金鑰**，引擎以**固定版本**安裝。

## 內容
- `accounts.json` — 你的帳戶↔策略對應（改這個就換策略，毋須動引擎）
- `data/` — 各帳戶的 portfolio_state / history / trade_events（引擎自動寫入）
- `.github/workflows/daily.yml` — 薄 workflow：裝固定版引擎 → `run-account --all` → commit data

## 一次性設定
1. 用本資料夾內容**建一個 private repo**（保管你的資料與金鑰）。
2. 設 Actions Secrets：
   - `ACC1_ALPACA_KEY` / `ACC1_ALPACA_SECRET`（券商金鑰）
   - `EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECIPIENT`（寄報告，選用）
   - `ENGINE_INSTALL_TOKEN`（能讀取私有引擎 repo 的 fine-grained PAT；若引擎 repo 設為 public 則免）
3. 編輯 `accounts.json` 填你的帳戶。

## 更新引擎
把 `daily.yml` 裡 `@v1.0.0` 改成新版本號即可（一行）。所有引擎修復隨之生效，**不會分歧**。

## 為什麼這樣設計
引擎碼不再被 fork 複製，而是按版本「引用」；本 repo 永遠只有這幾個檔。
詳見 [兩 repo 架構提案](https://itemhsu.github.io/tech-rebalance-dashboard/two-repo-architecture-plan.html)。
