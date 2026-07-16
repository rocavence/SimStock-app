# 台股模擬交易 SimStock-app

本機 Web App，模擬台股整股 + 盤中零股交易：轉入存款 → 下單 → 看持股損益，盤中即時抓 TWSE 報價。

## 桌面 App 下載

到 [Releases](../../releases/latest) 下載 `SimStock-*-macos-arm64.zip`，解壓得到 `SimStock.app`。

> **僅支援 Apple Silicon Mac（macOS 11+）**，未做 Apple 簽章，首次開啟需解隔離：
> ```bash
> xattr -dr com.apple.quarantine /path/to/SimStock.app
> ```
> 或第一次開被擋時：系統設定 → 隱私權與安全性 → 仍要開啟。

選單列一顆圖示 → 開出懸浮視窗即可操作，後端自動內建啟動。打包方式見 [`desktop/README.md`](desktop/README.md)。

## 特色
- **整股（張）+ 盤中零股（股）**，分別判斷交易時段（整股 09:00–13:30、零股 09:10–13:30）
- **真實成本**：手續費 0.1425%（可設折扣與最低收費）、賣出證交稅 0.3%、漲跌停 ±10% 檢查
- **即時報價**：TWSE MIS 免費 API，盤中每 15 秒輪詢（資料源本身約 15 秒延遲，再快無意義）
- 交易日曆判斷（週末/國定假日不抓）
- SQLite 存帳，可一鍵重置重新入金

## 安裝與啟動
```bash
cd ~/Code/SimStock-app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --port 8888 --reload
```
開瀏覽器 → http://127.0.0.1:8888

## 設定（settings 表，可直接改 DB 或之後加 UI）
| key | 預設 | 說明 |
|-----|------|------|
| fee_rate | 0.001425 | 手續費率 |
| fee_discount | 1.0 | 券商折扣（電子下單常見 0.6） |
| fee_min_round / fee_min_odd | 20 / 1 | 整股 / 零股最低手續費 |
| tax_rate | 0.003 | 賣出證交稅 |
| enforce_hours | 1 | 是否強制交易時段（測試可設 0 全時段成交） |

## 簡化說明（刻意不做的）
- 以即時價/限價直接成交，**不建委託簿撮合排隊**（對模擬無必要）
- 國定假日為 `backend/market.py` 內手動清單，**每年需更新**
- 當沖證交稅減半、定期定額等未模擬

## 注意
免費報價來源僅供模擬，非交易依據；勿高頻打 API 以免被擋。
