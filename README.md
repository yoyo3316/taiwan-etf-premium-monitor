# 台灣 ETF 盤中折溢價監控系統

在台股交易時段定期追蹤 **全部** TWSE 基本市況報導揭露的 ETF 盤中折溢價；當超過門檻時透過 **Telegram Bot** 告警，並提供 **Streamlit** 網頁儀表板。

> ⚠️ **重要聲明**  
> 本系統僅為**輔助監控與告警**工具。GitHub Actions 排程可能延遲數分鐘，**不可視為即時交易、報價或自動下單系統**。投資決策請自行判斷並以交易所／投信正式資訊為準。

## 功能摘要

| 項目 | 說明 |
|------|------|
| 資料來源 | 僅使用臺灣證券交易所（TWSE）官方端點 |
| 監控範圍 | `all_etf.txt` 涵蓋之全部 ETF（非少數指定代號） |
| 預設門檻 | 溢價 ≥ **+3.00%**、折價 ≤ **−3.00%** |
| 排程 | GitHub Actions 每 5 分鐘（UTC cron + 程式內 Asia/Taipei 再驗證） |
| 通知 | Telegram Bot（憑證僅來自環境變數／Secrets） |
| 防洗版 | 同一 ETF、同一方向在恢復正常前只通知一次 |
| 儀表板 | Streamlit：總覽、排行、搜尋、告警清單、閾值設定 |

## 資料來源（已驗證）

指定前端頁面為 JavaScript SPA，實際資料並非 HTML 靜態內容：

| 頁面 | URL |
|------|-----|
| ETF 即時指標價值揭露 | https://mis.twse.com.tw/stock/various-areas/etf-price/indicator-disclosure-etf?lang=zhHant |
| ETF 淨值揭露 | https://mis.twse.com.tw/stock/various-areas/etf-price/value-disclosure-etf?lang=zhHant |

前端 bundle（`category-*.js`）對應函式：

```js
// export S as k
function S() {
  return request({ method: "get", url: `/stock/data/all_etf.txt?_=${Date.now()}` });
}
```

**實際官方資料端點：**

```text
https://mis.twse.com.tw/stock/data/all_etf.txt
```

（可選）ETF 分類清單：`https://mis.twse.com.tw/stock/api/getCategory.jsp?ex=tse&i=B0`

### 欄位對照

| 欄位 | 意義 |
|------|------|
| `a` | ETF 代號 |
| `b` | ETF 名稱 |
| `e` | 成交價（市價） |
| `f` | 投信／總代理人預估淨值（指標價值） |
| `g` | 預估折溢價幅度 (%) |
| `h` | 前一營業日單位淨值 |
| `i` | 資料日期 `YYYYMMDD` |
| `j` | 資料時間 `HH:MM:SS` |

### 折溢價定義與交叉驗證

\[
折溢價率 = \frac{市價 - 預估淨值}{預估淨值} \times 100\%
\]

- 系統自行計算後與官方 `g` 欄交叉比對。
- 誤差 **> 0.05 個百分點** → 標記 `anomaly`，**不發送通知**。
- 市價／預估淨值／折溢價缺值，或預估淨值 ≤ 0 → 不通知。
- 資料時間超過 **10 分鐘**（可設定）→ 視為過期，不通知。
- 僅在 **Asia/Taipei** 平日 **08:50–13:30**（含盤前 08:50 起）且非休市日發送告警。

## 架構

```text
GitHub Actions (每 5 分鐘)
  └─ scripts/run_monitor.py
       ├─ 抓取 TWSE all_etf.txt
       ├─ 計算／驗證折溢價
       ├─ Telegram 通知（交易時段）
       └─ 寫入 data/latest.json、data/alert_state.json 並 commit

Streamlit Community Cloud
  └─ streamlit_app.py
       ├─ 可即時向 TWSE 抓取
       └─ 或讀取 repo 內 data/latest.json 快照
```

## 快速開始（本機）

### 1. 安裝

```bash
cd taiwan-etf-premium-monitor
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境變數

複製 `.env.example` 後自行匯出（**勿提交真實 Token**）：

```bash
# PowerShell 範例
$env:TELEGRAM_BOT_TOKEN="你的 token"
$env:TELEGRAM_CHAT_ID="你的 chat id"
```

或：

```bash
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
```

### 3. 執行監控（單次）

```bash
# 僅抓取與驗證，不發 Telegram
python scripts/run_monitor.py --no-notify -v

# 正式模式（交易時段內才會通知）
python scripts/run_monitor.py -v
```

### 4. 啟動儀表板

```bash
streamlit run streamlit_app.py
```

## Telegram 設定

1. 向 [@BotFather](https://t.me/BotFather) 建立 Bot，取得 **Bot Token**。
2. 取得 Chat ID（可對 bot 說話後用 `getUpdates` 查詢，或使用既有群組 ID）。
3. **僅**以環境變數或 GitHub Secrets 提供：
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. 禁止寫入程式碼、設定檔、README、JSON、commit 或前端頁面。

### 通知內容

- ETF 代號、名稱  
- 市價、預估淨值／指標價值  
- 折溢價百分比  
- 類型：溢價警示／折價警示  
- 資料時間  
- TWSE 資料來源連結  

### 防洗版規則

- 觸發溢價／折價後寫入 `data/alert_state.json` 鎖定。
- 同一 ETF、同一方向在**回到門檻內**前不再重複通知。
- 回到正常區間後解除鎖定，之後可再次通知。

## GitHub 部署

### 1. 建立公開 Repository

將本專案推上 GitHub（公開 repo 即可使用免費 Actions 分鐘額度與 Streamlit Cloud）。

### 2. 設定 Secrets

Repo → **Settings → Secrets and variables → Actions**：

| Secret | 說明 |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `TELEGRAM_CHAT_ID` | 接收聊天室 ID |

可選 **Variables**：`PREMIUM_THRESHOLD`、`DISCOUNT_THRESHOLD`、`DATA_MAX_AGE_MINUTES`。

### 3. Actions 排程說明

- Workflow：`.github/workflows/monitor.yml`
- Cron（UTC）：`*/5 0-6 * * 1-5`（週一至週五，約涵蓋台北交易時段）
- **程式內仍以 Asia/Taipei 二次判斷**交易日與 08:50–13:30（08:50 盤前監控起）。
- GitHub 排程**不保證準時**，可能延遲數分鐘甚至更久。
- 每次成功執行會 commit `data/latest.json` 與 `data/alert_state.json` 供儀表板／狀態使用。

### 4. Streamlit Community Cloud

1. 登入 [share.streamlit.io](https://share.streamlit.io)
2. 選擇本 repository
3. Main file path：`streamlit_app.py`
4. Python version：3.11（建議）
5. 部署後即可公開瀏覽儀表板

儀表板**不需要** Telegram Secrets；告警由 Actions 負責。

## 專案結構

```text
taiwan-etf-premium-monitor/
├── streamlit_app.py          # 網頁儀表板
├── requirements.txt
├── scripts/run_monitor.py    # Actions / CLI 入口
├── src/
│   ├── config.py
│   ├── twse_client.py        # TWSE all_etf.txt 客戶端
│   ├── market_hours.py       # 台北時區交易時段／休市
│   ├── monitor.py            # 監控與交叉驗證
│   ├── telegram_notify.py
│   ├── state.py              # 告警鎖定
│   └── storage.py            # 快照 I/O
├── data/
│   ├── settings.json         # 可調整閾值
│   ├── latest.json           # Actions 寫入
│   └── alert_state.json      # 鎖定狀態
└── .github/workflows/monitor.yml
```

## 安全與限制

- 不將 `TELEGRAM_*` 寫入 repo。
- 不使用 CMoney、Yahoo、Wantgoo、FinMind 或投信網站作為**主要**資料來源。
- 預估淨值由投信／總代理人提供，TWSE 僅轉載；僅供參考。
- 休市日、週末、開盤前／收盤後不送告警。

## 授權與免責

本專案僅供學習與個人輔助監控使用。作者不對資料正確性、通知及時性或任何投資損益負責。
