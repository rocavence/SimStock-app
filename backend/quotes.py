"""TWSE MIS 即時報價 client。

免費快照來源，約 15 秒延遲、會擋過於頻繁的請求，因此：
- 盤中由背景 poller 每 15 秒抓一次「持股 ∪ 自選」全部代碼（單一請求）
- 一律帶 User-Agent，啟動時先 warm-up 取得 cookie
"""
import time as _time
import httpx

MIS_BASE = "https://mis.twse.com.tw/stock"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://mis.twse.com.tw/stock/index.jsp",
}

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(headers=HEADERS, timeout=10.0)
        try:  # warm-up 取得 cookie
            await _client.get(f"{MIS_BASE}/index.jsp")
        except Exception:
            pass
    return _client


async def close_client():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _num(x):
    """MIS 數值欄位可能是 '-'（無資料），轉成 float 或 None。"""
    try:
        if x in (None, "-", ""):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse(entry: dict) -> dict:
    z = _num(entry.get("z"))           # 最近成交價
    y = _num(entry.get("y"))           # 昨收
    bids = (entry.get("b") or "").split("_")
    asks = (entry.get("a") or "").split("_")
    bid = _num(bids[0]) if bids and bids[0] else None
    ask = _num(asks[0]) if asks and asks[0] else None
    # 成交價可能為 '-'（尚未成交），退而用買/賣價或昨收
    price = z or ask or bid or y
    return {
        "code": entry.get("c"),
        "name": entry.get("n"),
        "price": price,
        "prev_close": y,
        "open": _num(entry.get("o")),
        "high": _num(entry.get("h")),
        "low": _num(entry.get("l")),
        "limit_up": _num(entry.get("u")),
        "limit_down": _num(entry.get("w")),
        "bid": bid,
        "ask": ask,
        "volume": _num(entry.get("v")),
        "time": entry.get("t"),
        "updated": entry.get("d"),
    }


async def _query(channels: list[str]) -> list[dict]:
    if not channels:
        return []
    client = await get_client()
    ex_ch = "|".join(channels)
    url = f"{MIS_BASE}/api/getStockInfo.jsp"
    params = {"ex_ch": ex_ch, "json": "1", "delay": "0", "_": int(_time.time() * 1000)}
    r = await client.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    return data.get("msgArray", []) or []


def classify(entry: dict) -> str:
    """用基金全名(nf)/名稱(n)判斷證券類型：bond_etf / etf / stock。"""
    nf = entry.get("nf") or ""
    n = entry.get("n") or ""
    if "債" in (nf + n):
        return "bond_etf"
    if "基金" in nf or "ETF" in (nf + n):
        return "etf"
    return "stock"


async def resolve(code: str) -> dict | None:
    """解析上市(tse)/上櫃(otc)與證券類型，回傳 {code, name, market, sec_type}。"""
    for market in ("tse", "otc"):
        rows = await _query([f"{market}_{code}.tw"])
        if rows and rows[0].get("n"):
            return {"code": code, "name": rows[0]["n"], "market": market,
                    "sec_type": classify(rows[0])}
    return None


async def fetch_quotes(securities: list[dict]) -> dict[str, dict]:
    """securities: [{code, market}, ...] → {code: quote}"""
    channels = [f"{s['market']}_{s['code']}.tw" for s in securities]
    rows = await _query(channels)
    out = {}
    for entry in rows:
        q = _parse(entry)
        if q["code"]:
            out[q["code"]] = q
    return out
