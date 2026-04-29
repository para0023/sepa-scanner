"""
/api/portfolio/* — 포트폴리오 CRUD + 분석
"""
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _set_market(market: str):
    from portfolio import set_portfolio_file
    pf = "portfolio_us.json" if market == "US" else "portfolio.json"
    set_portfolio_file(pf)


class BuyRequest(BaseModel):
    ticker: str
    name: str
    date: str
    price: float
    quantity: int
    stop_loss: float
    entry_reason: str
    memo: str = ""
    take_profit: float = 0
    entry_type_override: Optional[str] = None


class SellRequest(BaseModel):
    position_id: str
    date: str
    price: float
    quantity: int
    reason: str = ""


@router.get("/positions")
def get_positions(market: str = Query("KR")):
    """보유 포지션 (현재가 없이 즉시 반환)"""
    _set_market(market)
    from portfolio import get_open_positions
    df = get_open_positions()
    if df is None or df.empty:
        return {"market": market, "data": []}
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if hasattr(v, "item"):
                r[k] = v.item()
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {"market": market, "data": records}


@router.get("/positions/prices")
def get_positions_prices(market: str = Query("KR")):
    """보유 종목 현재가 일괄 조회 (별도 호출)"""
    _set_market(market)
    from portfolio import get_open_positions
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    df = get_open_positions()
    if df is None or df.empty:
        return {"prices": {}}

    def _fetch_price(ticker):
        try:
            t = yf.Ticker(ticker if not ticker.isdigit() else "%s.KS" % ticker)
            h = t.history(period="2d")
            if h is not None and not h.empty:
                return float(h["Close"].iloc[-1])
        except Exception:
            pass
        return 0

    tickers = df["종목코드"].tolist()
    with ThreadPoolExecutor(max_workers=8) as pool:
        prices = dict(zip(tickers, pool.map(_fetch_price, tickers)))

    is_us = market == "US"
    return {"prices": {t: (round(p, 2) if is_us else round(p)) if p > 0 else None for t, p in prices.items()}}


class StopLossUpdate(BaseModel):
    position_id: str
    date: str
    price: float
    note: str = ""

@router.post("/stop-loss/update")
def update_stop_loss_api(req: StopLossUpdate, market: str = Query("KR")):
    """손절가 수정"""
    _set_market(market)
    from portfolio import update_stop_loss
    ok = update_stop_loss(req.position_id, req.date, req.price, req.note)
    return {"success": ok}


@router.get("/reentry-check/{ticker}")
def check_reentry(ticker: str, market: str = Query("KR")):
    """재진입 경고 체크 — 마지막 청산일로부터 경과일 확인"""
    _set_market(market)
    from portfolio import _load
    from datetime import datetime

    data = _load()
    last_exit = None
    last_result = None

    for pos in data.get("positions", []):
        if pos["ticker"] == ticker and pos["status"] == "closed":
            sells = [t for t in pos.get("trades", []) if t["type"] == "sell"]
            buys = [t for t in pos.get("trades", []) if t["type"] == "buy"]
            if sells:
                exit_date = sells[-1]["date"]
                if last_exit is None or exit_date > last_exit:
                    last_exit = exit_date
                    # 손익 판단
                    if buys and sells:
                        avg_buy = sum(t["price"] * t["quantity"] for t in buys) / sum(t["quantity"] for t in buys)
                        avg_sell = sum(t["price"] * t["quantity"] for t in sells) / sum(t["quantity"] for t in sells)
                        last_result = "win" if avg_sell > avg_buy else "loss"

    if not last_exit:
        return {"warning": None}

    days_since = (datetime.now() - datetime.strptime(last_exit, "%Y-%m-%d")).days
    min_days = 30 if last_result == "win" else 14  # 익절 후 30일, 손절 후 14일

    if days_since < min_days:
        return {
            "warning": True,
            "last_exit": last_exit,
            "result": last_result,
            "days_since": days_since,
            "min_days": min_days,
            "message": "%s %d일 전 %s. 최소 %d일 대기 권장 (잔여 %d일)" % (
                ticker, days_since,
                "익절" if last_result == "win" else "손절",
                min_days, min_days - days_since
            ),
        }
    return {"warning": False, "last_exit": last_exit, "days_since": days_since}


@router.post("/buy")
def add_buy(req: BuyRequest, market: str = Query("KR")):
    _set_market(market)
    from portfolio import add_buy
    pos_id = add_buy(
        ticker=req.ticker, name=req.name, date=req.date,
        price=req.price, quantity=req.quantity,
        stop_loss=req.stop_loss, entry_reason=req.entry_reason,
        memo=req.memo, take_profit=req.take_profit,
        entry_type_override=req.entry_type_override,
    )
    return {"position_id": pos_id, "status": "ok"}


@router.post("/sell")
def add_sell(req: SellRequest, market: str = Query("KR")):
    _set_market(market)
    from portfolio import add_sell
    ok = add_sell(
        position_id=req.position_id, date=req.date,
        price=req.price, quantity=req.quantity, reason=req.reason,
    )
    return {"success": ok}


@router.get("/oti")
def get_oti(market: str = Query("KR")):
    _set_market(market)
    from portfolio import calc_oti
    return calc_oti(days=3)


@router.get("/oti/history")
def get_oti_history(market: str = Query("KR"), lookback: int = Query(60)):
    _set_market(market)
    from portfolio import calc_oti_history
    df = calc_oti_history(days=3, lookback=lookback)
    if df.empty:
        return {"data": []}
    return {"data": [{"date": str(r["날짜"].date()), "oti": int(r["OTI"])} for _, r in df.iterrows()]}


@router.get("/exposure/history")
def get_exposure_history(market: str = Query("KR"), lookback: int = Query(90)):
    _set_market(market)
    from portfolio import calc_exposure_history
    df = calc_exposure_history(lookback=lookback)
    if df.empty:
        return {"data": []}
    return {"data": [{"date": str(r["날짜"]), "exposure": float(r["익스포져"])} for _, r in df.iterrows()]}


@router.get("/market-score")
def get_market_score(market: str = Query("KR"), lookback: int = Query(90)):
    """시장점수 (추세 강도) 히스토리"""
    import FinanceDataReader as fdr
    import pandas as pd
    from datetime import datetime, timedelta

    index_code = "KS11" if market == "KR" else "^GSPC"
    end = datetime.now()
    start = end - timedelta(days=lookback + 60)
    df = fdr.DataReader(index_code, start, end)
    if df.empty or len(df) < 30:
        return {"data": [], "current": None}

    close = df["Close"]
    volume = df["Volume"]
    ma20 = close.rolling(20).mean()
    slope = (ma20 / ma20.shift(10) - 1) * 100
    vol_ma60 = volume.rolling(60).mean()
    vol_ratio = volume / vol_ma60
    rolling_low = close.rolling(20).min()
    low_rising = rolling_low > rolling_low.shift(10)

    def _s(s):
        if s <= -3: return 0
        elif s <= -1: return 30
        elif s <= 0: return 50
        elif s <= 1: return 70
        elif s <= 3: return 80
        else: return 100

    def _p(above, vr):
        if above: return 100
        elif vr <= 1.0: return 50
        else: return 20

    result = pd.DataFrame({"날짜": df.index, "종가": close, "MA20": ma20, "기울기": slope}).dropna()
    result["기울기점수"] = result["기울기"].apply(_s)
    result["위치점수"] = [_p(
        bool(close.loc[i] > ma20.loc[i]) if i in close.index and i in ma20.index else False,
        float(vol_ratio.loc[i]) if i in vol_ratio.index else 1.0
    ) for i in result.index]
    result["저점점수"] = [100 if (i in low_rising.index and bool(low_rising.loc[i])) else 30 for i in result.index]
    result["시장점수"] = (result["기울기점수"] * 0.5 + result["위치점수"] * 0.3 + result["저점점수"] * 0.2).round(0).astype(int)
    result = result.tail(lookback)

    last = result.iloc[-1]
    ms = int(last["시장점수"])
    slope_val = float(last["기울기"])
    level = "최적" if ms >= 85 else "양호" if ms >= 70 else "보통" if ms >= 50 else "주의" if ms >= 30 else "위험"

    return {
        "data": [{"date": d.strftime("%Y-%m-%d"), "score": int(s)} for d, s in zip(result["날짜"], result["시장점수"])],
        "current": {"score": ms, "level": level, "slope": round(slope_val, 1)},
    }


@router.get("/pnl/realized")
def get_realized_pnl(market: str = Query("KR")):
    _set_market(market)
    from portfolio import get_realized_pnl
    df = get_realized_pnl()
    if df.empty:
        return {"data": []}
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if hasattr(v, "item"):
                r[k] = v.item()
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {"data": records}


@router.get("/trade-log")
def get_trade_log(market: str = Query("KR")):
    _set_market(market)
    from portfolio import get_trade_log
    df = get_trade_log()
    if df.empty:
        return {"data": []}
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if hasattr(v, "item"):
                r[k] = v.item()
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {"data": records}


@router.get("/pnl/by-ticker")
def get_position_pnl(market: str = Query("KR")):
    """종목별 성과 분석"""
    _set_market(market)
    from portfolio import get_position_pnl
    df = get_position_pnl()
    if df.empty:
        return {"data": []}
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if hasattr(v, "item"):
                r[k] = v.item()
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {"data": records}


@router.get("/equity-curve")
def get_equity_curve(market: str = Query("KR")):
    """에퀴티 커브"""
    _set_market(market)
    from portfolio import get_equity_curve
    df = get_equity_curve()
    if df.empty:
        return {"data": []}
    return {"data": [
        {"date": str(r.get("날짜", "")), "cum_pnl": float(r.get("누적손익", 0))}
        for _, r in df.iterrows()
    ]}


@router.get("/monthly-performance")
def get_monthly_perf(market: str = Query("KR")):
    """월별 성과"""
    _set_market(market)
    from portfolio import get_monthly_performance
    df = get_monthly_performance()
    if df.empty:
        return {"data": []}
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if hasattr(v, "item"):
                r[k] = v.item()
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {"data": records}


@router.get("/weekly/weeks")
def get_weeks(market: str = Query("KR")):
    """거래가 있는 주간 목록"""
    _set_market(market)
    from portfolio import get_available_weeks
    return {"weeks": get_available_weeks()}


@router.get("/weekly/review")
def get_weekly(market: str = Query("KR"), week: str = Query(None)):
    """주간 리뷰 데이터"""
    _set_market(market)
    from portfolio import get_weekly_review
    data = get_weekly_review(week)
    if not data:
        return {}
    # numpy/pandas 변환
    import json
    import pandas as pd

    # DataFrame은 제거 (프론트에서 안 씀)
    if "trades_df" in data:
        del data["trades_df"]

    def _clean(obj):
        if hasattr(obj, "item"):
            return obj.item()
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if isinstance(obj, float) and obj != obj:
            return None
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        if isinstance(obj, pd.Timestamp):
            return obj.strftime("%Y-%m-%d")
        return obj

    cleaned = json.loads(json.dumps(data, default=_clean))
    return cleaned


@router.get("/weekly/pdf")
def get_weekly_pdf(market: str = Query("KR"), week: str = Query(None)):
    """주간 리포트 PDF 생성 + 차트 이미지 자동 생성"""
    _set_market(market)
    from portfolio import get_weekly_review
    from weekly_pdf import generate_weekly_pdf
    from relative_strength import build_trade_chart_image
    from fastapi.responses import Response
    import FinanceDataReader as fdr

    data = get_weekly_review(week)
    if not data:
        raise HTTPException(status_code=404, detail="주간 데이터 없음")

    # 차트 이미지 자동 생성
    chart_imgs = {}
    all_trades = data.get("entries", []) + data.get("exits", []) + data.get("both", [])
    for t in all_trades:
        tk = t["종목코드"]
        if tk in chart_imgs:
            continue
        try:
            dates = [b["날짜"] for b in t.get("매수", [])] + [s["날짜"] for s in t.get("매도", [])]
            last_date = max(dates) if dates else week
            img = build_trade_chart_image(tk, last_date, period=180)
            if img:
                chart_imgs[tk] = img
        except Exception:
            pass

    # 시장 데이터
    mkt_data = []
    try:
        for label, code in {"코스피": "KS11", "코스닥": "KQ11", "USD/KRW": "USD/KRW", "WTI": "CL=F"}.items():
            mdf = fdr.DataReader(code, data["week_start"], data["week_end"])
            if mdf is not None and len(mdf) >= 2:
                sv = float(mdf["Close"].iloc[0])
                ev = float(mdf["Close"].iloc[-1])
                mkt_data.append({"지표": label, "시작": round(sv, 2), "종료": round(ev, 2), "변동률(%)": round((ev / sv - 1) * 100, 2)})
    except Exception:
        pass

    currency = "원" if market == "KR" else "$"
    pdf_bytes = generate_weekly_pdf(data, chart_images=chart_imgs, market_data=mkt_data, currency=currency)

    filename = "weekly_report_%s_%s.pdf" % (market, week or "latest")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=%s" % filename},
    )


class CapitalFlowRequest(BaseModel):
    date: str
    amount: float
    note: str = ""


@router.get("/capital")
def get_capital_info(market: str = Query("KR")):
    """자본금 정보 + 입출금 이력"""
    _set_market(market)
    from portfolio import get_total_capital, get_capital_flows
    capital = get_total_capital()
    flows_df = get_capital_flows()
    flows = []
    if not flows_df.empty:
        flows = flows_df.to_dict(orient="records")
        for r in flows:
            for k, v in r.items():
                if hasattr(v, "item"):
                    r[k] = v.item()
    return {"capital": capital, "flows": flows}


@router.post("/capital/flow")
def add_capital(req: CapitalFlowRequest, market: str = Query("KR")):
    """입출금 기록"""
    _set_market(market)
    from portfolio import add_capital_flow
    add_capital_flow(req.date, req.amount, req.note)
    return {"status": "ok"}


@router.delete("/capital/flow/{flow_id}")
def delete_capital(flow_id: str, market: str = Query("KR")):
    """입출금 삭제"""
    _set_market(market)
    from portfolio import delete_capital_flow
    ok = delete_capital_flow(flow_id)
    return {"success": ok}


@router.get("/capital/balance")
def get_system_balance(market: str = Query("KR")):
    """시스템 추정 예수금 (원금 + 누적실현손익 - 보유종목 매수금액)"""
    _set_market(market)
    from portfolio import get_total_capital, get_realized_pnl, get_open_positions

    capital = get_total_capital()
    pnl_df = get_realized_pnl()
    pnl_col = [c for c in pnl_df.columns if "비용차감손익" in c]
    cum_pnl = float(pnl_df[pnl_col[0]].sum()) if pnl_col and not pnl_df.empty else 0

    # 보유종목 매수금액 합계
    df = get_open_positions()
    invested = 0
    if not df.empty:
        for _, r in df.iterrows():
            invested += float(r["평균매수가"]) * int(r["수량"])

    deposit = capital + cum_pnl - invested  # 예수금

    return {
        "capital": round(capital),
        "cum_pnl": round(cum_pnl),
        "invested": round(invested),
        "deposit": round(deposit),
    }
