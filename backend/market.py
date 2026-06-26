"""交易日曆與盤別時段判斷（台股，本機時區 = 台北時間）。

注意：國定假日清單需每年手動更新。weekend 一定準，假日清單漏了頂多在休市日
多打幾次 API（無害）。"""
from datetime import datetime, time

# 2026 台股休市日（國定假日，best-effort，請每年核對公告後更新）
TW_HOLIDAYS_2026 = {
    "2026-01-01",  # 元旦
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",  # 春節
    "2026-02-27",  # 228 補假
    "2026-04-03", "2026-04-06",  # 兒童節/清明連假
    "2026-05-01",  # 勞動節
    "2026-06-19",  # 端午節
    "2026-09-25",  # 中秋節
    "2026-10-09",  # 雙十補假
}

ROUND_OPEN, ROUND_CLOSE = time(9, 0), time(13, 30)   # 整股
ODD_OPEN, ODD_CLOSE = time(9, 10), time(13, 30)      # 盤中零股


def is_trading_day(dt: datetime) -> bool:
    if dt.weekday() >= 5:  # 週六日
        return False
    return dt.strftime("%Y-%m-%d") not in TW_HOLIDAYS_2026


def market_status(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    trading = is_trading_day(now)
    t = now.time()
    round_open = trading and ROUND_OPEN <= t <= ROUND_CLOSE
    odd_open = trading and ODD_OPEN <= t <= ODD_CLOSE
    return {
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_trading_day": trading,
        "round_open": round_open,   # 整股可交易
        "odd_open": odd_open,       # 盤中零股可交易
        "any_open": round_open or odd_open,
    }
