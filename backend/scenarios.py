"""策略對照：用相同本金跑兩種配置，自建立日起依即時報價比較報酬。

進場價在第一次呼叫時擷取（存到 SAVE_DIR/scenarios.json），之後固定不變，
報酬隨行情變化累積，讓使用者看「分散低波 vs 妖股集中」的差距。
"""
import json
from datetime import datetime

from . import db, quotes

SCEN_FILE = db.SAVE_DIR / "scenarios.json"
CAPITAL = 15000

# 兩個對照組（code, 股數），股數對應約 15,000 本金
_DEFS = {
    "balanced": {"label": "分散低波", "desc": "投等債＋低波高息＋台股大盤＋美股",
                 "holdings": [("00772B", 102), ("00713", 58), ("0050", 33), ("00646", 46)]},
    "yolo": {"label": "妖股集中", "desc": "全壓單一高波動股（華通）",
             "holdings": [("2313", 57)]},
}


def _all_codes() -> set:
    return {c for d in _DEFS.values() for c, _ in d["holdings"]}


async def _sec(code: str):
    conn = db.get_conn()
    r = conn.execute("SELECT code, market FROM securities WHERE code=?", (code,)).fetchone()
    conn.close()
    if r:
        return {"code": r["code"], "market": r["market"]}
    info = await quotes.resolve(code)
    return {"code": info["code"], "market": info["market"]} if info else None


async def _quote_map() -> dict:
    secs = [s for s in [await _sec(c) for c in _all_codes()] if s]
    return await quotes.fetch_quotes(secs)


async def ensure_entries() -> dict:
    if SCEN_FILE.exists():
        return json.loads(SCEN_FILE.read_text(encoding="utf-8"))
    qmap = await _quote_map()
    data = {"created": datetime.now().strftime("%Y-%m-%d %H:%M"), "capital": CAPITAL, "baskets": {}}
    for key, d in _DEFS.items():
        hold, spent = [], 0.0
        for code, sh in d["holdings"]:
            q = qmap.get(code) or {}
            entry = q.get("price")
            hold.append({"code": code, "name": q.get("name", code), "shares": sh, "entry": entry})
            if entry:
                spent += sh * entry
        data["baskets"][key] = {"label": d["label"], "desc": d["desc"],
                                "holdings": hold, "cash": round(CAPITAL - spent, 2)}
    db.SAVE_DIR.mkdir(parents=True, exist_ok=True)
    SCEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


async def compare() -> dict:
    data = await ensure_entries()
    qmap = await _quote_map()
    baskets = []
    for key, b in data["baskets"].items():
        cur = b["cash"]
        rows = []
        for h in b["holdings"]:
            q = qmap.get(h["code"]) or {}
            price = q.get("price")
            val = price * h["shares"] if price else None
            if val:
                cur += val
            rows.append({"code": h["code"], "name": h["name"], "shares": h["shares"],
                         "entry": h["entry"], "price": price,
                         "value": round(val) if val else None,
                         "pnl_pct": round((price - h["entry"]) / h["entry"] * 100, 2)
                         if (price and h["entry"]) else None})
        baskets.append({"key": key, "label": b["label"], "desc": b["desc"],
                        "invested": CAPITAL, "current": round(cur),
                        "pnl": round(cur - CAPITAL), "pnl_pct": round((cur - CAPITAL) / CAPITAL * 100, 2),
                        "holdings": rows})

    # 記錄每日淨值點（同一天只留最新一筆），畫成走勢線
    today = datetime.now().strftime("%Y-%m-%d")
    point = {"date": today}
    for b in baskets:
        point[b["key"]] = b["pnl_pct"]
    hist = [h for h in data.get("history", []) if h.get("date") != today]
    hist.append(point)
    hist.sort(key=lambda h: h["date"])
    data["history"] = hist
    SCEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"created": data["created"], "capital": CAPITAL,
            "baskets": baskets, "history": hist}


def reset():
    if SCEN_FILE.exists():
        SCEN_FILE.unlink()
