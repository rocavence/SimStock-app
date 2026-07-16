"""SQLite 存取層。單帳號模擬器，資料檔放在 data/sim.db。

另設「自動存檔」：每次資料變動寫一份 JSON 到固定資料夾，啟動時若 db 為空會自動還原，
確保資料不因 db 被刪或換機而遺失。"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# 凍結（PyInstaller）時 _MEIPASS 為唯讀，DB 改寫到使用者可寫目錄；開發時維持 repo data/
if getattr(sys, "frozen", False):
    _data_dir = Path.home() / "Library" / "Application Support" / "SimStock-app"
    _data_dir.mkdir(parents=True, exist_ok=True)
    DB_PATH = _data_dir / "sim.db"
else:
    DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sim.db"

def _default_save_dir() -> Path:
    """優先放 Dropbox/Apps（跨機同步），找不到再退回 Documents。"""
    for base in (Path.home() / "Dropbox" / "Apps",
                 Path.home() / "Library" / "CloudStorage" / "Dropbox" / "Apps"):
        if base.exists():
            return base / "twstock-saves"
    return Path.home() / "Documents" / "twstock-saves"


# 記住「資料來源路徑」的指標檔，放使用者家目錄 → 不隨 app 部署位置或 db 刪除而消失
POINTER_FILE = Path.home() / ".SimStock-app" / "datasource.txt"


def _resolve_save_file() -> Path:
    """決定資料存檔/讀取的單一路徑（唯一真相）：
    1) 環境變數 TWSTOCK_SAVE_DIR 2) 使用者記住的路徑 3) 預設 Dropbox/Apps。"""
    if os.environ.get("TWSTOCK_SAVE_DIR"):
        return Path(os.environ["TWSTOCK_SAVE_DIR"]) / "save.json"
    if POINTER_FILE.exists():
        p = Path(POINTER_FILE.read_text(encoding="utf-8").strip()).expanduser()
        if p.name:
            return p
    return _default_save_dir() / "save.json"


SAVE_FILE = _resolve_save_file()
SAVE_DIR = SAVE_FILE.parent
LAST_SAVE = {"path": str(SAVE_FILE), "ts": None}


def set_data_source(path) -> Path:
    """切換資料來源並記住（寫入指標檔），之後存檔/讀取都用這個路徑。"""
    global SAVE_FILE, SAVE_DIR
    p = Path(path).expanduser()
    SAVE_FILE, SAVE_DIR = p, p.parent
    LAST_SAVE["path"] = str(p)
    POINTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    POINTER_FILE.write_text(str(p), encoding="utf-8")
    return p


def import_from(path) -> dict:
    """讀入指定路徑的投資資料，並記住該路徑為往後的資料來源。"""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(str(p))
    json.loads(p.read_text(encoding="utf-8"))  # 先驗證可解析
    set_data_source(p)
    load_snapshot(p)
    return {"path": str(p)}

DEFAULT_SETTINGS = {
    "fee_rate": "0.001425",     # 手續費率
    "fee_discount": "1.0",       # 券商折扣（電子下單常見 0.6）
    "fee_min_round": "20",       # 整股最低手續費
    "fee_min_odd": "1",          # 零股最低手續費
    "tax_rate": "0.003",         # 一般股票賣出證交稅
    "etf_tax_rate": "0.001",     # 股票型 ETF 賣出證交稅（債券 ETF 免稅）
    "enforce_hours": "1",        # 是否強制交易時段（1/0）
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL NOT NULL,
            initial_deposit REAL NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS securities (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            market TEXT NOT NULL,          -- tse / otc
            sec_type TEXT NOT NULL DEFAULT 'stock'  -- stock / etf / bond_etf
        );
        CREATE TABLE IF NOT EXISTS holdings (
            code TEXT PRIMARY KEY,
            shares INTEGER NOT NULL,       -- 以「股」為單位（1張 = 1000股）
            avg_cost REAL NOT NULL,        -- 含買進手續費的每股成本
            FOREIGN KEY (code) REFERENCES securities(code)
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            side TEXT NOT NULL,            -- buy / sell
            lot_type TEXT NOT NULL,        -- round / odd
            shares INTEGER NOT NULL,
            price REAL NOT NULL,
            gross REAL NOT NULL,           -- price * shares
            fee REAL NOT NULL,
            tax REAL NOT NULL,
            net REAL NOT NULL,             -- 現金實際增減（買為負、賣為正）
            realized REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS watchlist (
            code TEXT PRIMARY KEY,
            FOREIGN KEY (code) REFERENCES securities(code)
        );
        CREATE TABLE IF NOT EXISTS pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            side TEXT NOT NULL,            -- buy / sell
            lot_type TEXT NOT NULL,        -- round / odd
            quantity INTEGER NOT NULL,     -- round=張數, odd=股數
            limit_price REAL,              -- NULL = 開盤市價
            est_cost REAL NOT NULL DEFAULT 0,  -- 買進預估金額（含手續費），用於資金預留
            status TEXT NOT NULL DEFAULT 'pending',  -- pending / filled / failed / cancelled
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    # 遷移：舊 DB 的 securities 可能沒有 sec_type 欄位
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(securities)").fetchall()]
    if "sec_type" not in cols:
        conn.execute("ALTER TABLE securities ADD COLUMN sec_type TEXT NOT NULL DEFAULT 'stock'")
    pcols = [r["name"] for r in conn.execute("PRAGMA table_info(pending_orders)").fetchall()]
    if pcols and "est_cost" not in pcols:
        conn.execute("ALTER TABLE pending_orders ADD COLUMN est_cost REAL NOT NULL DEFAULT 0")
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    has_account = conn.execute("SELECT 1 FROM account WHERE id=1").fetchone() is not None
    conn.commit()
    conn.close()
    # db 為空但有存檔 → 自動還原（防 db 被刪 / 換機）
    if not has_account and SAVE_FILE.exists():
        load_snapshot()


def get_settings() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def account_exists() -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM account WHERE id = 1").fetchone()
    conn.close()
    return row is not None


def save_info() -> dict:
    return {"path": str(SAVE_FILE), "ts": LAST_SAVE["ts"]}


def save_snapshot() -> Path:
    """把全部資料表寫成 JSON 存檔（原子寫入）。每次資料變動後呼叫。"""
    conn = get_conn()
    rows = lambda t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
    acct = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
    data = {
        "version": 1,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "account": dict(acct) if acct else None,
        "securities": rows("securities"),
        "holdings": rows("holdings"),
        "transactions": rows("transactions"),
        "watchlist": [dict(r) for r in conn.execute(
            "SELECT w.code, s.name FROM watchlist w LEFT JOIN securities s ON s.code=w.code ORDER BY w.code")],
        "pending_orders": rows("pending_orders"),
        "settings": {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")},
    }
    conn.close()
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SAVE_DIR / (SAVE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SAVE_FILE)
    LAST_SAVE["ts"] = data["saved_at"]
    return SAVE_FILE


def load_snapshot(src=None) -> bool:
    """從存檔還原所有資料表（覆蓋現有 db）。src 預設為目前資料來源。"""
    src = Path(src) if src else SAVE_FILE
    if not src.exists():
        return False
    data = json.loads(src.read_text(encoding="utf-8"))
    conn = get_conn()
    try:
        for t in ("holdings", "transactions", "watchlist", "pending_orders", "securities", "account"):
            conn.execute(f"DELETE FROM {t}")
        a = data.get("account")
        if a:
            conn.execute("INSERT INTO account(id,cash,initial_deposit,realized_pnl,created_at) VALUES (1,?,?,?,?)",
                         (a["cash"], a["initial_deposit"], a["realized_pnl"], a["created_at"]))
        for s in data.get("securities", []):
            conn.execute("INSERT OR REPLACE INTO securities(code,name,market,sec_type) VALUES (?,?,?,?)",
                         (s["code"], s["name"], s["market"], s.get("sec_type", "stock")))
        for h in data.get("holdings", []):
            conn.execute("INSERT INTO holdings(code,shares,avg_cost) VALUES (?,?,?)",
                         (h["code"], h["shares"], h["avg_cost"]))
        for w in data.get("watchlist", []):
            conn.execute("INSERT OR IGNORE INTO watchlist(code) VALUES (?)", (w["code"],))
        for t in data.get("transactions", []):
            conn.execute("INSERT INTO transactions(id,ts,code,name,side,lot_type,shares,price,gross,fee,tax,net,realized) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (t["id"], t["ts"], t["code"], t["name"], t["side"], t["lot_type"], t["shares"],
                          t["price"], t["gross"], t["fee"], t["tax"], t["net"], t["realized"]))
        for p in data.get("pending_orders", []):
            conn.execute("INSERT INTO pending_orders(id,created_at,code,name,side,lot_type,quantity,limit_price,est_cost,status,note) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (p["id"], p["created_at"], p["code"], p["name"], p["side"], p["lot_type"],
                          p["quantity"], p.get("limit_price"), p.get("est_cost", 0), p["status"], p.get("note", "")))
        for k, v in data.get("settings", {}).items():
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (k, v))
        conn.commit()
    finally:
        conn.close()
    LAST_SAVE["ts"] = data.get("saved_at")
    return True
