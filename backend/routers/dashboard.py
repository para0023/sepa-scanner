"""
/api/dashboard — 대시보드 요약 데이터 (분리 로딩)
"""
from fastapi import APIRouter

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/holdings")
def get_dashboard_holdings():
    """보유종목 + OTI + 자산 (빠름 — 파일 읽기만)"""
    from portfolio import set_portfolio_file, calc_oti, get_open_positions, get_total_capital, get_realized_pnl

    oti = {}
    holdings = {}
    assets = {}

    for market, pf in [("KR", "portfolio.json"), ("US", "portfolio_us.json")]:
        set_portfolio_file(pf)
        is_us = market == "US"
        _r = lambda v: round(v, 2) if is_us else round(v)

        try:
            oti[market] = calc_oti(days=3)
        except Exception:
            pass

        df = get_open_positions()
        capital = get_total_capital()
        pnl_df = get_realized_pnl()
        pnl_col = [c for c in pnl_df.columns if "비용차감손익" in c]
        cum_pnl = float(pnl_df[pnl_col[0]].sum()) if pnl_col and not pnl_df.empty else 0

        if df.empty:
            holdings[market] = []
            assets[market] = {"capital": _r(capital), "cum_pnl": _r(cum_pnl), "unrealized": 0, "total": _r(capital + cum_pnl), "total_ret": 0}
            continue

        rows = []
        for _, r in df.iterrows():
            avg = float(r["평균매수가"])
            qty = int(r["수량"])
            rows.append({
                "종목코드": r["종목코드"], "종목명": r["종목명"],
                "평균매수가": _r(avg), "수량": qty, "손절가": _r(float(r["손절가"])),
                "현재가": None, "수익률": None, "경과일": int(r["경과일"]),
                "매수금액": _r(avg * qty),
            })
        holdings[market] = rows
        assets[market] = {"capital": _r(capital), "cum_pnl": _r(cum_pnl), "unrealized": 0, "total": _r(capital + cum_pnl), "total_ret": 0}

    set_portfolio_file("portfolio.json")
    return {"oti": oti, "holdings": holdings, "stop_alerts": [], "assets": assets}


@router.get("/dashboard/indices")
def get_dashboard_indices(lookback: int = 1):
    """시장지수 + 매크로 (lookback: 1=전일, 5=전주, 20=전월, 250=전년)"""
    import FinanceDataReader as fdr
    from datetime import datetime, timedelta

    result = {}
    end = datetime.now()
    fetch_days = max(int(lookback * 1.5) + 60, 60)
    start = end - timedelta(days=fetch_days)

    all_codes = {
        "코스피": "KS11", "코스닥": "KQ11",
        "S&P500": "^GSPC", "나스닥": "^IXIC",
        "USD/KRW": "USD/KRW", "DXY": "DX-Y.NYB",
        "WTI": "CL=F", "Gold": "GC=F",
    }

    for label, code in all_codes.items():
        try:
            df = fdr.DataReader(code, start, end)
            if df is not None and len(df) >= 2:
                df = df.dropna(subset=["Close"])
                if len(df) < 2:
                    continue
                cur = float(df["Close"].iloc[-1])
                prev_idx = min(lookback, len(df) - 1)
                prev = float(df["Close"].iloc[-(prev_idx + 1)])
                if prev == 0 or cur != cur or prev != prev:  # NaN check
                    continue
                result[label] = {
                    "price": round(cur, 2),
                    "change": round(cur - prev, 2),
                    "change_pct": round((cur / prev - 1) * 100, 2),
                }
        except Exception:
            pass

    return {"indices": result}


@router.get("/dashboard/prices")
def get_dashboard_prices():
    """보유종목 현재가 일괄 조회 (느림 — yfinance)"""
    from portfolio import set_portfolio_file, get_open_positions, get_total_capital, get_realized_pnl
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    def _fetch_price(ticker):
        try:
            t = yf.Ticker(ticker if not ticker.isdigit() else f"{ticker}.KS")
            h = t.history(period="2d")
            if h is not None and not h.empty:
                return float(h["Close"].iloc[-1])
        except Exception:
            pass
        return 0

    holdings = {}
    stop_alerts = []
    assets = {}

    for market, pf in [("KR", "portfolio.json"), ("US", "portfolio_us.json")]:
        set_portfolio_file(pf)
        is_us = market == "US"
        _r = lambda v: round(v, 2) if is_us else round(v)

        df = get_open_positions()
        capital = get_total_capital()
        pnl_df = get_realized_pnl()
        pnl_col = [c for c in pnl_df.columns if "비용차감손익" in c]
        cum_pnl = float(pnl_df[pnl_col[0]].sum()) if pnl_col and not pnl_df.empty else 0

        if df.empty:
            holdings[market] = []
            assets[market] = {"capital": _r(capital), "cum_pnl": _r(cum_pnl), "unrealized": 0, "total": _r(capital + cum_pnl), "total_ret": 0}
            continue

        tickers = df["종목코드"].tolist()
        with ThreadPoolExecutor(max_workers=8) as pool:
            prices = dict(zip(tickers, pool.map(_fetch_price, tickers)))

        rows = []
        unrealized = 0
        for _, r in df.iterrows():
            t = r["종목코드"]
            cur = prices.get(t, 0)
            avg = float(r["평균매수가"])
            qty = int(r["수량"])
            sl = float(r["손절가"])
            ret_pct = round((cur / avg - 1) * 100, 2) if cur > 0 and avg > 0 else None
            sl_dist = round((cur - sl) / cur * 100, 2) if cur > 0 and sl > 0 else None

            rows.append({
                "종목코드": t, "종목명": r["종목명"],
                "평균매수가": _r(avg), "수량": qty, "손절가": _r(sl),
                "현재가": _r(cur) if cur > 0 else None,
                "수익률": ret_pct, "경과일": int(r["경과일"]),
                "매수금액": _r(avg * qty),
            })

            if cur > 0:
                unrealized += (cur - avg) * qty

            if sl_dist is not None:
                stop_alerts.append({
                    "종목코드": t, "시장": market, "종목명": r["종목명"],
                    "현재가": _r(cur) if cur > 0 else None,
                    "손절가": _r(sl),
                    "손절거리(%)": sl_dist,
                })

        holdings[market] = rows
        total_asset = capital + cum_pnl + unrealized
        total_ret = round((total_asset / capital - 1) * 100, 2) if capital > 0 else 0
        assets[market] = {
            "capital": _r(capital), "cum_pnl": _r(cum_pnl),
            "unrealized": _r(unrealized), "total": _r(total_asset), "total_ret": total_ret,
        }

    stop_alerts.sort(key=lambda x: x.get("손절거리(%)", 999))
    set_portfolio_file("portfolio.json")
    return {"holdings": holdings, "stop_alerts": stop_alerts, "assets": assets}


# 기존 snapshot은 호환용으로 유지
@router.get("/dashboard/snapshot")
def get_dashboard_snapshot():
    """전체 대시보드 (호환용 — 느림)"""
    h = get_dashboard_holdings()
    i = get_dashboard_indices()
    p = get_dashboard_prices()
    return {
        "indices": i["indices"],
        "oti": h["oti"],
        "holdings": p["holdings"],
        "stop_alerts": p["stop_alerts"],
        "assets": p["assets"],
    }
