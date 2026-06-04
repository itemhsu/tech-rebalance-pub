# 🤖 科技股自動再平衡系統

每個美股交易日收盤後，自動依市值選出前 10 大科技股並以等權重再平衡持倉。

## 🖥️ 桌面管理控制台（macOS App）

不想用命令列也能管理帳戶、金鑰與排程。下載桌面版 GUI：

| 平台 | 下載 |
|---|---|
| macOS | **[最新版下載（公開 Releases）](https://github.com/itemhsu/tradingadmin/releases/latest)** → 下載 `TradingAdmin-macOS.dmg` |

**安裝**：開啟 `.dmg`，把 `TradingAdmin.app` 拖到 `Applications`。

**首次開啟**：對 App **右鍵 → 開啟**（未經 Apple 公證，直接雙擊會被 Gatekeeper 擋）。

**需求**：先安裝並登入 GitHub CLI（`brew install gh` → `gh auth login`）。App 全程透過 GitHub API 讀寫設定，**不會在本機留下任何代碼**。

## 策略說明

| 項目 | 規格 |
|---|---|
| 持倉標的 | 市值前 10 大科技股（候選池 25 檔） |
| 目標比重 | 等權重，每檔 10% |
| 再平衡容忍帶 | ±2%（帶內不觸發，降低交易成本） |
| 再平衡時機 | 有新股票進入/跌出前 10 名時 |
| 交易帳戶 | Alpaca Paper Trading（初期）→ Live（驗證後） |
| 執行時間 | 每日 UTC 15:15（台灣時間 23:15），收盤後執行 |
| 資料來源 | Alpaca API（收盤價）× SEC EDGAR（流通股數） |

## 快速開始

### 本機設定

```bash
# 1. 安裝依賴
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 設定環境變數（複製並修改）
cp .env.example .env
# 編輯 .env，填入 Alpaca Paper Trading API Key

# 3. 測試執行（DRY_RUN 模式）
DRY_RUN=true python main.py

# 4. 執行單元測試
pytest tests/ -v
```

### `.env.example`

```
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_SECRET_KEY=your_paper_secret_key_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
DRY_RUN=true
```

### GitHub Actions 設定

在 GitHub Repo Settings → Secrets and variables → Actions 設定：

| Secret | 說明 |
|---|---|
| `ALPACA_API_KEY` | Alpaca API Key ID |
| `ALPACA_SECRET_KEY` | Alpaca API Secret Key |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets`（Paper）或 `https://api.alpaca.markets`（Live）|

## 專案結構

```
tech-rebalance/
├── .github/workflows/daily_rebalance.yml  # 每日自動執行
├── data/
│   ├── universe.json                       # 候選股票（25 檔）
│   ├── shares_outstanding.json             # 流通股數（每季更新）
│   ├── portfolio_state.json                # 最新持倉快照（自動生成）
│   └── portfolio_state_history.json        # NAV 歷史（自動生成）
├── tests/                                  # 單元測試
├── main.py          # 主程式
├── universe.py      # 股票宇宙管理
├── market_cap.py    # 市值計算與排名
├── portfolio.py     # 持倉管理與再平衡邏輯
├── trader.py        # Alpaca API 封裝
├── dashboard.py     # HTML Dashboard 生成
├── logger.py        # README 日誌更新
└── dashboard.html   # 即時 Dashboard（自動生成）
```

## 🔀 Fork 維護與相容性

若你是從上游 `itemhsu/tech-rebalance` **fork** 出來的，請依下列方式維護，避免與上游脫節：

**拉取上游修復（保留你的私有設定）**
```bash
bash scripts/sync_upstream.sh --dry-run   # 先看上游有哪些新 commit，不改動
bash scripts/sync_upstream.sh             # 實際合併；accounts.json / data/ 自動保留本地版本
```

**相容性測試（改動契約面前後都該跑）**
```bash
python -m pytest tests/test_compat_*.py tests/test_schema_compat.py
```
涵蓋：schema 合法性、版本標記、向前/向後相容、跨產物對齊（data.json↔前端、Secrets↔workflow）、
字串耦合（selection method / event type）、生成管線 idempotent。CI 會在動到 `schemas/` /
`strategies/` / `brokers/` / `accounts.json` 時自動跑（`.github/workflows/compat_ci.yml`）。

**改 schema 的規則 —— 只做加法**
- 允許：加 optional 欄位、放寬 enum/界限。
- **禁止就地破壞**（加 required、移除欄位、收窄 enum/type）→ 會打爆所有 fork。
  確需破版時：**把 schema 檔名 bump**（如 `data-schema-v1` → `-v2`），舊檔不動。
  `scripts/schema_compat.py` 會在 CI 偵測並擋下違規。

> 📋 完整設計：[Fork 相容性與上游變更影響管理計劃](https://itemhsu.github.io/tech-rebalance-dashboard/fork-compatibility-plan.html)

## Dashboard

> 🔗 [查看即時持倉 Dashboard](dashboard.html)（需啟用 GitHub Pages）

啟用方式：Settings → Pages → Source: Deploy from a branch → Branch: main / (root)

## 緊急操作

```bash
# 手動觸發（DRY_RUN 模式）
# GitHub Actions → Daily Rebalance → Run workflow → dry_run: true

# 停止自動交易（臨時）
# 將 .github/workflows/daily_rebalance.yml 中的 cron 行注解掉，commit
```

---

## 交易日誌

<!-- TRADING_LOG_START -->
| 日期 | NAV (USD) | 執行交易 | 前10名持股 | 備註 |
|------|-----------|---------|-----------|------|
| 2026-05-05 | $99,988.04 | 買入 AAPL×35; 買入 AMD×27; 買入 AMZN×36; 買入 AVGO×23; 買入 GOOGL×25; 買入 META×16… 共10筆 | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,V,AMD | — |
| 2026-05-06 | $102,591.34 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-07 | $102,999.23 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-08 | $104,076.25 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-11 | $104,724.54 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-12 | $103,434.49 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-13 | $103,995.41 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-14 | $105,746.10 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-15 | $103,809.60 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-19 | $102,450.07 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,V,AMD | 首次建倉 |
| 2026-05-20 | $103,819.86 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-21 | $104,530.47 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-22 | $104,535.46 | 賣出 AMD×4 | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | — |
| 2026-05-26 | $105,795.84 | 買入 AAPL×1; 買入 AMZN×1; 買入 NVDA×1; 買入 V×1 | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-27 | $106,175.47 | 買入 AAPL×1; 買入 AMZN×1; 買入 NVDA×1; 買入 V×1 | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-28 | $107,821.21 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
| 2026-05-29 | $108,104.93 | 無交易（持倉無異動） | NVDA,AAPL,MSFT,AMZN,GOOGL,TSM,AVGO,META,AMD,V | 首次建倉 |
<!-- TRADING_LOG_END -->
