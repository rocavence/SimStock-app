"""下單與成本計算：手續費、證交稅、漲跌停與時段檢查、成交與庫存更新。

簡化：以即時價（或使用者給的限價）直接成交，不建委託簿撮合引擎。
shares 一律以「股」為單位（整股 = 張數 × 1000，零股 = 1~999 股）。
"""
import math
from datetime import datetime

from . import db
from .market import market_status


class TradeError(Exception):
    pass


def _fee(gross: float, lot_type: str, s: dict) -> float:
    rate = float(s["fee_rate"]) * float(s["fee_discount"])
    raw = gross * rate
    floor = float(s["fee_min_round"] if lot_type == "round" else s["fee_min_odd"])
    # 手續費無條件捨去到整數元，並套用最低收費
    return max(math.floor(raw), floor)


def _tax(gross: float, sec_type: str, s: dict) -> float:
    if sec_type == "bond_etf":
        return 0  # 債券 ETF 免證交稅
    rate = float(s["etf_tax_rate"] if sec_type == "etf" else s["tax_rate"])
    return math.floor(gross * rate)


def normalize_shares(lot_type: str, quantity: int) -> int:
    """round: quantity 是張數 → ×1000；odd: quantity 是股數，須 1~999。"""
    if quantity <= 0:
        raise TradeError("數量必須大於 0")
    if lot_type == "round":
        return quantity * 1000
    if quantity >= 1000:
        raise TradeError("零股數量須為 1~999 股；整股請用張數下單")
    return quantity


def estimate_buy_cost(price: float, lot_type: str, quantity: int, s: dict) -> float:
    """買進預估應付現金（成交額 + 手續費），用於預約單資金預留。"""
    shares = normalize_shares(lot_type, quantity)
    gross = price * shares
    return gross + _fee(gross, lot_type, s)


def execute_order(code: str, side: str, lot_type: str, quantity: int,
                  quote: dict, limit_price: float | None = None) -> dict:
    if side not in ("buy", "sell"):
        raise TradeError("side 必須是 buy 或 sell")
    if lot_type not in ("round", "odd"):
        raise TradeError("lot_type 必須是 round 或 odd")

    s = db.get_settings()
    status = market_status()
    if s["enforce_hours"] == "1":
        open_flag = status["round_open"] if lot_type == "round" else status["odd_open"]
        if not open_flag:
            label = "整股(09:00–13:30)" if lot_type == "round" else "盤中零股(09:10–13:30)"
            raise TradeError(f"目前非{label}交易時段，無法成交")

    if not quote or quote.get("price") is None:
        raise TradeError("查無即時報價，無法成交")

    # 決定成交價：限價須在漲跌停內；市價用即時價
    price = limit_price if limit_price is not None else quote["price"]
    up, down = quote.get("limit_up"), quote.get("limit_down")
    if up is not None and price > up:
        raise TradeError(f"價格 {price} 超過漲停 {up}")
    if down is not None and price < down:
        raise TradeError(f"價格 {price} 低於跌停 {down}")

    shares = normalize_shares(lot_type, quantity)
    gross = round(price * shares, 4)
    fee = _fee(gross, lot_type, s)

    conn = db.get_conn()
    try:
        acct = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
        if acct is None:
            raise TradeError("尚未開始模擬，請先轉入存款")
        sec = conn.execute("SELECT * FROM securities WHERE code = ?", (code,)).fetchone()
        name = sec["name"] if sec else code
        hold = conn.execute("SELECT * FROM holdings WHERE code = ?", (code,)).fetchone()

        realized, tax = 0.0, 0
        if side == "buy":
            net = -(gross + fee)
            if acct["cash"] + net < 0:
                raise TradeError(f"現金不足：需 {gross + fee:.0f}，餘 {acct['cash']:.0f}")
            old_sh = hold["shares"] if hold else 0
            old_cost = hold["avg_cost"] if hold else 0.0
            new_sh = old_sh + shares
            new_avg = (old_cost * old_sh + gross + fee) / new_sh  # 成本含手續費
            conn.execute(
                "INSERT INTO holdings(code, shares, avg_cost) VALUES (?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET shares=?, avg_cost=?",
                (code, new_sh, new_avg, new_sh, new_avg),
            )
        else:  # sell
            if hold is None or hold["shares"] < shares:
                have = hold["shares"] if hold else 0
                raise TradeError(f"持股不足：欲賣 {shares} 股，庫存 {have} 股")
            sec_type = sec["sec_type"] if sec else "stock"
            tax = _tax(gross, sec_type, s)
            net = gross - fee - tax
            realized = round(net - hold["avg_cost"] * shares, 4)
            remain = hold["shares"] - shares
            if remain == 0:
                conn.execute("DELETE FROM holdings WHERE code = ?", (code,))
            else:
                conn.execute("UPDATE holdings SET shares = ? WHERE code = ?", (remain, code))

        conn.execute("UPDATE account SET cash = cash + ?, realized_pnl = realized_pnl + ? WHERE id = 1",
                     (net, realized))
        conn.execute(
            "INSERT INTO transactions(ts, code, name, side, lot_type, shares, price, gross, fee, tax, net, realized) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), code, name, side, lot_type,
             shares, price, gross, fee, tax, net, realized),
        )
        conn.commit()
        return {"code": code, "name": name, "side": side, "lot_type": lot_type,
                "shares": shares, "price": price, "gross": gross, "fee": fee,
                "tax": tax, "net": net, "realized": realized}
    finally:
        conn.close()
