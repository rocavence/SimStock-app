"""台股模擬交易 — FastAPI 後端 + 即時報價背景輪詢。

啟動：cd ~/Code/SimStock-app && uvicorn backend.main:app --reload
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, history, quotes, scenarios, trading
from .market import market_status

# 凍結（PyInstaller）時前端隨包打進 _MEIPASS；開發時用 repo 內路徑
if getattr(sys, "frozen", False):
    FRONTEND = Path(sys._MEIPASS) / "frontend"
else:
    FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
POLL_OPEN_SEC = 15    # 盤中輪詢間隔
POLL_CLOSED_SEC = 60  # 收盤後重新判斷間隔

QUOTE_CACHE: dict[str, dict] = {}   # code -> quote
LAST_POLL: dict[str, str] = {"ts": "—"}


def tracked_securities() -> list[dict]:
    """需即時報價的代碼：持股 ∪ 自選 ∪ 待成交預約單。"""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT code, market FROM securities WHERE code IN ("
        "  SELECT code FROM holdings UNION SELECT code FROM watchlist "
        "  UNION SELECT code FROM pending_orders WHERE status='pending'"
        ")"
    ).fetchall()
    conn.close()
    return [{"code": r["code"], "market": r["market"]} for r in rows]


async def refresh_quotes():
    secs = tracked_securities()
    if not secs:
        return
    try:
        QUOTE_CACHE.update(await quotes.fetch_quotes(secs))
        LAST_POLL["ts"] = datetime.now().strftime("%H:%M:%S")
    except Exception as e:  # 來源不穩時不讓 poller 掛掉
        print(f"[poller] fetch error: {e}")


def process_pending():
    """開盤時把預約委託逐筆以現價（或限價）送出成交。"""
    status = market_status()
    if not status["any_open"]:
        return
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM pending_orders WHERE status='pending' ORDER BY id").fetchall()
    conn.close()
    changed = False
    for o in rows:
        session_open = status["round_open"] if o["lot_type"] == "round" else status["odd_open"]
        if not session_open:
            continue  # 該盤別還沒開（如零股 09:10 前），等下一輪
        quote = QUOTE_CACHE.get(o["code"])
        if not quote or quote.get("price") is None:
            continue  # 還沒報價，下一輪再試
        try:
            trading.execute_order(o["code"], o["side"], o["lot_type"], o["quantity"],
                                  quote, o["limit_price"])
            _set_pending(o["id"], "filled", f"開盤成交 @ {quote['price']}")
        except trading.TradeError as e:
            _set_pending(o["id"], "failed", str(e))
        changed = True
    if changed:
        db.save_snapshot()


def _set_pending(pid: int, status: str, note: str):
    conn = db.get_conn()
    conn.execute("UPDATE pending_orders SET status=?, note=? WHERE id=?", (status, note, pid))
    conn.commit()
    conn.close()


async def poller():
    await refresh_quotes()  # 啟動先抓一次（即使收盤，拿到最後收盤價）
    while True:
        open_now = market_status()["any_open"]
        if open_now:
            await refresh_quotes()
            process_pending()
        await asyncio.sleep(POLL_OPEN_SEC if open_now else POLL_CLOSED_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(poller())
    yield
    task.cancel()
    await quotes.close_client()


app = FastAPI(title="台股模擬交易", lifespan=lifespan)


# ---------- models ----------
class DepositIn(BaseModel):
    amount: float


class ImportIn(BaseModel):
    path: str


class OrderIn(BaseModel):
    code: str
    side: str           # buy / sell
    lot_type: str       # round / odd
    quantity: int       # round=張數, odd=股數
    limit_price: float | None = None


class WatchIn(BaseModel):
    code: str


class WatchBulkIn(BaseModel):
    codes: list[str]


# ---------- helpers ----------
async def ensure_security(code: str) -> dict:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM securities WHERE code = ?", (code,)).fetchone()
    conn.close()
    if row:
        return {"code": row["code"], "name": row["name"], "market": row["market"],
                "sec_type": row["sec_type"]}
    info = await quotes.resolve(code)
    if not info:
        raise HTTPException(404, f"查無此代碼：{code}")
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO securities(code, name, market, sec_type) VALUES (?,?,?,?)",
                 (info["code"], info["name"], info["market"], info["sec_type"]))
    conn.commit()
    conn.close()
    return info


def portfolio_snapshot() -> dict:
    conn = db.get_conn()
    acct = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
    holds = conn.execute(
        "SELECT h.code, h.shares, h.avg_cost, s.name FROM holdings h "
        "JOIN securities s ON s.code = h.code ORDER BY h.code"
    ).fetchall()
    reserved = conn.execute(
        "SELECT COALESCE(SUM(est_cost),0) r FROM pending_orders WHERE status='pending'"
    ).fetchone()["r"]
    conn.close()

    positions, market_value = [], 0.0
    for h in holds:
        q = QUOTE_CACHE.get(h["code"], {})
        price = q.get("price")
        value = price * h["shares"] if price else None
        cost = h["avg_cost"] * h["shares"]
        unreal = (value - cost) if value is not None else None
        if value:
            market_value += value
        positions.append({
            "code": h["code"], "name": h["name"], "shares": h["shares"],
            "avg_cost": round(h["avg_cost"], 4), "price": price,
            "market_value": round(value, 2) if value else None,
            "unrealized": round(unreal, 2) if unreal is not None else None,
            "unrealized_pct": round(unreal / cost * 100, 2) if (unreal is not None and cost) else None,
            "prev_close": q.get("prev_close"), "limit_up": q.get("limit_up"),
            "limit_down": q.get("limit_down"),
        })

    cash = acct["cash"] if acct else 0.0
    initial = acct["initial_deposit"] if acct else 0.0
    realized = acct["realized_pnl"] if acct else 0.0
    total = cash + market_value
    return {
        "started": acct is not None,
        "cash": round(cash, 2),
        "initial_deposit": round(initial, 2),
        "realized_pnl": round(realized, 2),
        "market_value": round(market_value, 2),
        "total_assets": round(total, 2),
        "total_pnl": round(total - initial, 2) if acct else 0,
        "total_pnl_pct": round((total - initial) / initial * 100, 2) if initial else 0,
        "pending_reserved": round(reserved, 2),
        "reservable_cash": round(cash - reserved, 2),
        "positions": positions,
    }


# ---------- routes ----------
@app.get("/api/status")
def api_status():
    return {
        "market": market_status(),
        "last_poll": LAST_POLL["ts"],
        "portfolio": portfolio_snapshot(),
        "save": db.save_info(),
    }


@app.post("/api/account/deposit")
def api_deposit(body: DepositIn):
    """存入存款。第一次存入即開始模擬；之後可再存入加碼。"""
    if body.amount <= 0:
        raise HTTPException(400, "金額須大於 0")
    conn = db.get_conn()
    if conn.execute("SELECT 1 FROM account WHERE id=1").fetchone() is None:
        conn.execute(
            "INSERT INTO account(id, cash, initial_deposit, realized_pnl, created_at) "
            "VALUES (1, ?, ?, 0, ?)",
            (body.amount, body.amount, datetime.now().isoformat()),
        )
    else:
        conn.execute(
            "UPDATE account SET cash = cash + ?, initial_deposit = initial_deposit + ? WHERE id=1",
            (body.amount, body.amount),
        )
    conn.commit()
    conn.close()
    db.save_snapshot()
    return portfolio_snapshot()


@app.post("/api/import")
async def api_import(body: ImportIn):
    """讀入指定路徑的投資資料，並記住該路徑為往後的資料來源。"""
    try:
        info = db.import_from(body.path)
    except FileNotFoundError:
        raise HTTPException(404, f"找不到檔案：{body.path}")
    except (ValueError, OSError) as e:
        raise HTTPException(400, f"檔案無法讀取或格式錯誤：{e}")
    await refresh_quotes()  # 匯入後立即暖快取，自選/持股馬上有報價
    return {"ok": True, "path": info["path"], "portfolio": portfolio_snapshot()}


@app.post("/api/account/reset")
def api_reset():
    """清空一切，回到未開始狀態（不預設任何金額）。"""
    conn = db.get_conn()
    conn.execute("DELETE FROM holdings")
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM pending_orders")
    conn.execute("DELETE FROM watchlist")
    conn.execute("DELETE FROM account")
    conn.commit()
    conn.close()
    db.save_snapshot()
    return portfolio_snapshot()


@app.post("/api/order")
async def api_order(body: OrderIn):
    if not db.account_exists():
        raise HTTPException(400, "尚未開始模擬，請先存入存款")
    info = await ensure_security(body.code)
    s = db.get_settings()
    status = market_status()
    session_open = status["round_open"] if body.lot_type == "round" else status["odd_open"]

    # 取得即時報價（預約估價 / 立即成交都需要）
    quote = QUOTE_CACHE.get(info["code"])
    if quote is None:
        fetched = await quotes.fetch_quotes([{"code": info["code"], "market": info["market"]}])
        quote = fetched.get(info["code"])
        if quote:
            QUOTE_CACHE[info["code"]] = quote

    # 收盤（且有開啟時段限制）→ 轉為預約委託，開盤自動成交
    if s["enforce_hours"] == "1" and not session_open:
        try:
            trading.normalize_shares(body.lot_type, body.quantity)  # 先驗數量
        except trading.TradeError as e:
            raise HTTPException(400, str(e))

        est = 0.0
        if body.side == "buy":  # 買進需預留資金
            price = body.limit_price if body.limit_price is not None else (quote or {}).get("price")
            if price is None:
                raise HTTPException(400, "查無報價，無法估算預約金額")
            est = trading.estimate_buy_cost(price, body.lot_type, body.quantity, s)
            conn = db.get_conn()
            cash = conn.execute("SELECT cash FROM account WHERE id=1").fetchone()["cash"]
            reserved = conn.execute(
                "SELECT COALESCE(SUM(est_cost),0) r FROM pending_orders WHERE status='pending'"
            ).fetchone()["r"]
            conn.close()
            if reserved + est > cash:
                raise HTTPException(
                    400, f"資金不足以預約：可預約 {cash - reserved:,.0f} 元，此單需 {est:,.0f} 元")

        conn = db.get_conn()
        conn.execute(
            "INSERT INTO pending_orders(created_at, code, name, side, lot_type, quantity, limit_price, est_cost) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), info["code"], info["name"],
             body.side, body.lot_type, body.quantity, body.limit_price, est),
        )
        conn.commit()
        conn.close()
        db.save_snapshot()
        label = "整股(09:00)" if body.lot_type == "round" else "盤中零股(09:10)"
        return {"pending": True,
                "message": f"已預約：{info['name']} {'買進' if body.side=='buy' else '賣出'}，"
                           f"將於下一個{label}開盤以{'限價' if body.limit_price else '市價'}成交",
                "portfolio": portfolio_snapshot()}

    # 盤中 → 立即成交
    try:
        result = trading.execute_order(body.code, body.side, body.lot_type,
                                       body.quantity, quote, body.limit_price)
    except trading.TradeError as e:
        raise HTTPException(400, str(e))
    db.save_snapshot()
    return {"order": result, "portfolio": portfolio_snapshot()}


@app.get("/api/pending")
def api_pending():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM pending_orders ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.delete("/api/pending/{pid}")
def api_pending_cancel(pid: int):
    conn = db.get_conn()
    conn.execute("DELETE FROM pending_orders WHERE id=? AND status='pending'", (pid,))
    conn.commit()
    conn.close()
    db.save_snapshot()
    return {"ok": True}


@app.get("/api/transactions")
def api_transactions(limit: int = 100):
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/watchlist")
async def api_watchlist():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT w.code, s.name, s.market FROM watchlist w JOIN securities s ON s.code = w.code ORDER BY w.code"
    ).fetchall()
    conn.close()
    # 快取缺的（如剛匯入、輪詢還沒跑）即時補抓一次，避免要查一次才出現
    missing = [{"code": r["code"], "market": r["market"]} for r in rows if r["code"] not in QUOTE_CACHE]
    if missing:
        QUOTE_CACHE.update(await quotes.fetch_quotes(missing))
    return [{"code": r["code"], "name": r["name"],
             "quote": QUOTE_CACHE.get(r["code"])} for r in rows]


@app.post("/api/watchlist")
async def api_watch_add(body: WatchIn):
    info = await ensure_security(body.code)
    conn = db.get_conn()
    conn.execute("INSERT OR IGNORE INTO watchlist(code) VALUES (?)", (info["code"],))
    conn.commit()
    conn.close()
    db.save_snapshot()
    await refresh_quotes()
    return {"ok": True, "security": info}


@app.post("/api/watchlist/bulk")
async def api_watch_bulk(body: WatchBulkIn):
    """批次加入自選股：貼一串代碼，逐一解析、加入，回報加入與查無。"""
    added, notfound = [], []
    for raw in body.codes:
        code = raw.strip().upper()
        if not code:
            continue
        try:
            info = await ensure_security(code)
        except HTTPException:
            notfound.append(code)
            continue
        conn = db.get_conn()
        conn.execute("INSERT OR IGNORE INTO watchlist(code) VALUES (?)", (info["code"],))
        conn.commit()
        conn.close()
        added.append(info["code"])
    db.save_snapshot()
    await refresh_quotes()
    return {"ok": True, "added": added, "notfound": notfound}


@app.delete("/api/watchlist/{code}")
def api_watch_del(code: str):
    conn = db.get_conn()
    conn.execute("DELETE FROM watchlist WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    db.save_snapshot()
    return {"ok": True}


@app.get("/api/scenarios")
async def api_scenarios():
    return await scenarios.compare()


@app.delete("/api/scenarios")
def api_scenarios_reset():
    scenarios.reset()
    return {"ok": True}


@app.get("/api/history/{code}")
async def api_history(code: str):
    info = await ensure_security(code)
    candles = await history.history(info["code"], info["market"])
    return {"security": info, "candles": candles}


@app.get("/api/quote/{code}")
async def api_quote(code: str):
    info = await ensure_security(code)
    fetched = await quotes.fetch_quotes([{"code": info["code"], "market": info["market"]}])
    q = fetched.get(code)
    if q:
        QUOTE_CACHE[code] = q
    return {"security": info, "quote": q}


@app.get("/api/settings")
def api_get_settings():
    return db.get_settings()


# ---------- frontend ----------
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(FRONTEND / "favicon.svg", media_type="image/svg+xml")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
