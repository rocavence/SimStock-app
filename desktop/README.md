# SimStock 桌面 App（選單列版）

把本機版「台股模擬交易」包成**自包含、可雙擊**的 macOS 選單列 App。
雙擊後右上角選單列出現一顆圖示，內建後端自動啟動，點選單即可開出可調大小的懸浮視窗。

> 目標機器：**Apple Silicon Mac、免簽章**（自用）。要跨 Intel/Windows 需在該平台各自重打包。

---

## 使用

```bash
open /Applications/SimStock.app      # 或 desktop/dist/SimStock.app
```

選單列圖示 → 選單：

| 項目 | 說明 |
|------|------|
| **開啟視窗** | 開出懸浮、可自由調整大小的視窗（WKWebView）顯示 web app |
| **Port：8888** | 點擊修改後端埠號（重啟後生效） |
| **存檔位置：…** | 原生資料夾選擇器，指定 `save.json` 存放處（重啟後生效） |
| **視窗置頂（懸浮）** | 切換視窗是否永遠浮在最上層 |
| **重新啟動** | 套用 port / 存檔位置變更 |
| **結束** | 離開（一併關掉內建後端） |

設定寫在 `~/Library/Application Support/SimStock-app/config.json`。

---

## 重新打包

改完程式碼後：

```bash
cd ~/Code/SimStock-app
bash desktop/build.sh        # 自動：建 venv → 畫 icon → PyInstaller 凍結
open desktop/dist/SimStock.app
```

產物：`desktop/dist/SimStock.app`（~39MB，含 Python 執行期）。

### 元件

| 檔案 | 作用 |
|------|------|
| `app.py` | 選單列 App 本體：rumps 選單 + PyObjC `WKWebView` 視窗 + 背景執行緒跑 `uvicorn` |
| `SimStock-app.spec` | PyInstaller 設定（打包前端、隱藏匯入、`LSUIElement` agent、ATS 允許 localhost） |
| `build.sh` | 一鍵打包腳本 |
| `make-icon.swift` | CoreGraphics 畫 1024 icon（squircle + 漸層 + 浮起 K 線卡片，仿 Findly 精緻度） |
| `.venv/` | 打包專用 venv（rumps / pyobjc-WebKit / pyinstaller），不影響專案的 `../.venv` |

---

## 設計重點 / 坑

- **為何不用 pywebview**：pywebview 會自建 `NSApplication` 事件迴圈，和 rumps 的打架。改用 PyObjC 直接建 `WKWebView`，同一個 `NSApplication`，同樣是原生 WebKit、可調大小。
- **凍結路徑守衛**：`backend/main.py`、`backend/db.py` 以 `getattr(sys, "frozen", False)` 分流——
  - 凍結時：前端讀 `sys._MEIPASS/frontend`；DB 改寫 `~/Library/Application Support/SimStock-app/sim.db`（`_MEIPASS` 唯讀，不能放 SQLite）。
  - 開發時：行為完全不變（前端讀 repo、DB 用 `data/sim.db`）。
- **存檔位置必須在 import backend 前設好**：`db.py` 於 import 當下就解析 `SAVE_FILE`，所以 `app.py` 先設 `TWSTOCK_SAVE_DIR` 環境變數再啟動 uvicorn。預設仍落 `~/Dropbox/Apps/twstock-saves/`（沿用既有資料）。
- **uvicorn 固定 `loop="asyncio"`, `http="h11"`**：避免凍結時缺 uvloop/httptools 的原生相依。
- **Python 3.14**：本機唯一可用版本，PyInstaller 6.21 可正常凍結。
- **免 GUI 冒煙測試**：`TWSTOCK_SMOKE=1 desktop/dist/SimStock.app/Contents/MacOS/SimStock`，只啟動後端、檢查 8888 後立即退出。
