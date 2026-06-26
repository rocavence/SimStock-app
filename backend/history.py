"""日 K 線歷史資料：上市用 TWSE STOCK_DAY，上櫃用 TPEx。

兩邊回傳格式相同：[日期, 量, 額, 開, 高, 低, 收, ...]，日期為民國年「115/06/05」。
"""
from datetime import date
import httpx

H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}


def _roc_to_iso(s: str) -> str:
    y, m, d = s.strip().split("/")
    return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_rows(rows) -> list[dict]:
    out = []
    for r in rows or []:
        try:
            o, h, l, c = _num(r[3]), _num(r[4]), _num(r[5]), _num(r[6])
        except IndexError:
            continue
        if None in (o, h, l, c):
            continue
        out.append({"time": _roc_to_iso(r[0]), "open": o, "high": h, "low": l, "close": c})
    return out


async def _twse(client, code, y, m):
    r = await client.get("https://www.twse.com.tw/exchangeReport/STOCK_DAY",
                         params={"response": "json", "date": f"{y}{m:02d}01", "stockNo": code})
    return _parse_rows(r.json().get("data", []))


async def _tpex(client, code, y, m):
    r = await client.get("https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock",
                         params={"code": code, "date": f"{y}/{m:02d}/01", "response": "json"})
    tables = r.json().get("tables") or []
    return _parse_rows(tables[0].get("data", []) if tables else [])


async def history(code: str, market: str, months: int = 3) -> list[dict]:
    today = date.today()
    ym, y, m = [], today.year, today.month
    for _ in range(months):
        ym.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    fetch = _twse if market == "tse" else _tpex
    seen = {}
    async with httpx.AsyncClient(headers=H, timeout=15) as client:
        for (yy, mm) in ym:
            try:
                for row in await fetch(client, code, yy, mm):
                    seen[row["time"]] = row
            except Exception:
                pass
    return sorted(seen.values(), key=lambda r: r["time"])
