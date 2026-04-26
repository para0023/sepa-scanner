"""
/api/watchlist/* — 그룹 분석 API
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("/groups")
def get_groups(market: str = Query("KR")):
    """그룹 목록 + 종목"""
    from watchlist import load_watchlists
    wl = load_watchlists()
    groups = wl.get(market, {})
    return {"market": market, "groups": groups}


class GroupCreate(BaseModel):
    name: str

@router.post("/groups")
def create_group(req: GroupCreate, market: str = Query("KR")):
    from watchlist import add_group
    add_group(market, req.name)
    return {"status": "ok"}


@router.delete("/groups/{name}")
def delete_group_api(name: str, market: str = Query("KR")):
    from watchlist import delete_group
    delete_group(market, name)
    return {"status": "ok"}


class TickerAdd(BaseModel):
    ticker: str

@router.post("/groups/{name}/ticker")
def add_ticker_api(name: str, req: TickerAdd, market: str = Query("KR")):
    from watchlist import add_ticker
    add_ticker(market, name, req.ticker)
    return {"status": "ok"}


@router.delete("/groups/{name}/ticker/{ticker}")
def remove_ticker_api(name: str, ticker: str, market: str = Query("KR")):
    from watchlist import remove_ticker
    remove_ticker(market, name, ticker)
    return {"status": "ok"}


@router.get("/groups/rs")
def get_all_group_rs(market: str = Query("KR"), period: int = Query(60)):
    """전체 그룹 RS 랭킹"""
    from watchlist import load_watchlists, calc_group_index, load_group_rs_cache, save_group_rs_cache
    wl = load_watchlists()
    groups = wl.get(market, {})
    if not groups:
        return {"data": []}

    # 캐시 우선
    cached = load_group_rs_cache(market, groups)
    if cached:
        return {"data": cached}

    benchmark_name = "코스피" if market == "KR" else "S&P 500"
    rows = []
    for gname, gtickers in groups.items():
        if not gtickers:
            continue
        gi = calc_group_index(market, gtickers, period=period)
        if gi:
            rows.append({
                "그룹명": gname,
                "RS Score": gi["rs_score"],
                "그룹수익률(%)": gi["group_ret"],
                f"{benchmark_name}(%)": gi["bench_ret"],
                "종목수": len(gtickers),
            })

    if rows:
        save_group_rs_cache(market, groups, rows)
    return {"data": rows}


@router.get("/groups/{name}/chart")
def get_group_chart(name: str, market: str = Query("KR"), period: int = Query(60)):
    """그룹 지수 차트 데이터 (그룹지수 + 벤치마크 + RS Line)"""
    from watchlist import load_watchlists, calc_group_index
    wl = load_watchlists()
    tickers = wl.get(market, {}).get(name, [])
    if not tickers:
        return {"error": "그룹이 비어있습니다"}

    gi = calc_group_index(market, tickers, period=period)
    if not gi:
        return {"error": "데이터 부족"}

    dates = [d.strftime("%Y-%m-%d") for d in gi["group_idx"].index]
    return {
        "group_name": name,
        "market": market,
        "period": period,
        "dates": dates,
        "group_idx": [round(float(v), 2) for v in gi["group_idx"].values],
        "benchmark": [round(float(v), 2) for v in gi["benchmark"].values],
        "rs_line": [round(float(v), 2) for v in gi["rs_line"].values],
        "rs_score": gi["rs_score"],
        "group_ret": gi["group_ret"],
        "bench_ret": gi["bench_ret"],
        "valid_tickers": gi["valid_tickers"],
        "names": gi["names"],
    }


@router.get("/groups/{name}/detail")
def get_group_detail(name: str, market: str = Query("KR"), period: int = Query(60)):
    """그룹 내 종목 상세 (종목명 + 현재가 + 기간 수익률)"""
    from watchlist import load_watchlists
    import FinanceDataReader as fdr
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor

    wl = load_watchlists()
    tickers = wl.get(market, {}).get(name, [])
    if not tickers:
        return {"data": []}

    end = datetime.now()
    start = end - timedelta(days=int(period * 1.5) + 30)

    # 한국 종목명 매핑
    krx_map = {}
    if market == "KR":
        try:
            krx = fdr.StockListing("KRX")[["Code", "Name"]].dropna()
            krx_map = dict(zip(krx["Code"], krx["Name"]))
        except Exception:
            pass

    def _fetch_one(ticker):
        try:
            df = fdr.DataReader(ticker, start, end)
            if df is None or df.empty:
                return None
            df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=["Close"])
            if len(df) < 2:
                return None
            cur = float(df["Close"].iloc[-1])
            prev_idx = min(period, len(df) - 1)
            prev = float(df["Close"].iloc[-(prev_idx + 1)])
            ret = round((cur / prev - 1) * 100, 2) if prev > 0 else 0
            name_str = krx_map.get(ticker, ticker) if market == "KR" else ticker
            return {"종목코드": ticker, "종목명": name_str, "현재가": round(cur, 2), "수익률(%)": ret}
        except Exception:
            return None

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for r in pool.map(_fetch_one, tickers):
            if r:
                results.append(r)

    results.sort(key=lambda x: x["수익률(%)"], reverse=True)
    return {"data": results}


@router.post("/groups/rs/refresh")
def refresh_group_rs(market: str = Query("KR"), period: int = Query(60)):
    """그룹 RS 강제 재계산"""
    from watchlist import load_watchlists, calc_group_index, save_group_rs_cache
    wl = load_watchlists()
    groups = wl.get(market, {})
    benchmark_name = "코스피" if market == "KR" else "S&P 500"
    rows = []
    for gname, gtickers in groups.items():
        if not gtickers:
            continue
        gi = calc_group_index(market, gtickers, period=period)
        if gi:
            rows.append({
                "그룹명": gname,
                "RS Score": gi["rs_score"],
                "그룹수익률(%)": gi["group_ret"],
                f"{benchmark_name}(%)": gi["bench_ret"],
                "종목수": len(gtickers),
            })
    if rows:
        save_group_rs_cache(market, groups, rows)
    return {"data": rows}
