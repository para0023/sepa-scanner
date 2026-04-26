"""
/api/scanner/* — 스캐너 API (RS 랭킹, VCP, Short, 52w High)
"""
import json
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/scanner", tags=["scanner"])


def _df_to_records(df):
    """DataFrame → JSON-safe list of dicts"""
    import pandas as pd
    if df is None or df.empty:
        return []
    # numpy/pandas 타입을 python 네이티브로 변환
    records = df.reset_index(drop=True).to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if hasattr(v, "item"):  # numpy scalar
                r[k] = v.item()
            elif isinstance(v, float) and (v != v):  # NaN
                r[k] = None
    return records


@router.get("/rs/{market}")
def get_rs_ranking(
    market: str,
    period: int = Query(60, ge=10, le=252),
    top_n: int = Query(100, ge=10, le=500),
):
    """RS 강세 상위 종목 랭킹"""
    from market_ranking import calc_market_ranking
    df = calc_market_ranking(market=market, period=period, top_n=top_n)
    return {"market": market, "period": period, "count": len(df), "data": _df_to_records(df)}


@router.get("/rs/{market}/vcp")
def get_rs_vcp_filter(
    market: str,
    period: int = Query(60, ge=10, le=252),
    top_n: int = Query(100, ge=10, le=500),
    force: bool = Query(False),
):
    """RS 상위 종목에 VCP 필터 적용"""
    from market_ranking import calc_market_ranking, apply_vcp_filter
    df = calc_market_ranking(market=market, period=period, top_n=top_n)
    df_vcp = apply_vcp_filter(df, market=market, period=period, use_cache=not force)
    return {
        "market": market, "period": period,
        "count": len(df_vcp),
        "data": _df_to_records(df_vcp),
    }


@router.get("/sepa/{market}")
def get_vcp_patterns(
    market: str,
    period: int = Query(60, ge=10, le=252),
    force: bool = Query(False),
):
    """VCP 패턴 후보 종목"""
    from market_ranking import scan_vcp_patterns
    df = scan_vcp_patterns(market=market, period=period, use_cache=not force)
    return {"market": market, "period": period, "count": len(df) if df is not None else 0, "data": _df_to_records(df)}


@router.get("/sepa/{market}/stream")
def get_vcp_patterns_stream(
    market: str,
    period: int = Query(60, ge=10, le=252),
    force: bool = Query(False),
):
    """VCP 패턴 스캔 (SSE 스트림 — 진행률 실시간 전송)"""
    from market_ranking import scan_vcp_patterns, _load_filter_cache

    # 캐시가 있으면 즉시 반환 (스트림 불필요)
    if not force:
        cached = _load_filter_cache("vcp_pattern", market, period)
        if cached is not None:
            def _cached():
                data = {"market": market, "period": period, "count": len(cached), "data": _df_to_records(cached)}
                yield "event: done\ndata: %s\n\n" % json.dumps(data, ensure_ascii=False)
            return StreamingResponse(_cached(), media_type="text/event-stream")

    def _stream():
        import threading
        result_holder = {"df": None, "error": None}

        def _progress(done, total):
            msg = json.dumps({"done": done, "total": total}, ensure_ascii=False)
            progress_events.append("event: progress\ndata: %s\n\n" % msg)

        progress_events = []

        def _run():
            try:
                result_holder["df"] = scan_vcp_patterns(
                    market=market, period=period,
                    use_cache=False, progress_cb=_progress,
                )
            except Exception as e:
                result_holder["error"] = str(e)

        t = threading.Thread(target=_run)
        t.start()

        sent = 0
        while t.is_alive():
            t.join(timeout=0.5)
            while sent < len(progress_events):
                yield progress_events[sent]
                sent += 1

        # 남은 progress 이벤트 전송
        while sent < len(progress_events):
            yield progress_events[sent]
            sent += 1

        if result_holder["error"]:
            yield "event: error\ndata: %s\n\n" % json.dumps({"error": result_holder["error"]})
        else:
            df = result_holder["df"]
            data = {"market": market, "period": period, "count": len(df) if df is not None else 0, "data": _df_to_records(df)}
            yield "event: done\ndata: %s\n\n" % json.dumps(data, ensure_ascii=False)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/short/{market}")
def get_short_candidates(
    market: str,
    period: int = Query(60),
    force: bool = Query(False),
):
    """숏 후보 종목"""
    from market_ranking import scan_short_candidates, INVERSE_ETF_MAP
    df = scan_short_candidates(period=period, use_cache=not force)
    # 인버스 ETF 매핑 테이블도 반환
    etf_list = []
    for ticker, info in INVERSE_ETF_MAP.items():
        for inv_ticker, inv_name in info.get("inverse", []):
            etf_list.append({
                "종목코드": inv_ticker,
                "종목명": inv_name,
                "원본종목": "%s (%s)" % (ticker, info.get("name", "")),
                "타입": "지수 인버스" if info.get("type") == "index" else "개별 인버스",
            })
    return {
        "market": market, "period": period,
        "count": len(df) if df is not None else 0,
        "data": _df_to_records(df),
        "inverse_etf": etf_list,
    }


@router.get("/universe/{market}/listing")
def get_market_listing(
    market: str,
    sort_by: str = Query("marcap", description="marcap|change|volume"),
    top_n: int = Query(100, ge=10, le=500),
):
    """시장 전종목 리스트 (시가총액/등락률/거래량 정렬)"""
    import FinanceDataReader as fdr
    listing = fdr.StockListing(market)
    df = listing[["Code", "Name", "Close", "Changes", "ChagesRatio", "Volume", "Marcap"]].copy()
    df = df.rename(columns={
        "Code": "종목코드", "Name": "종목명", "Close": "현재가",
        "Changes": "전일대비", "ChagesRatio": "등락률(%)",
        "Volume": "거래량", "Marcap": "시가총액",
    })
    df = df.dropna(subset=["종목명", "현재가"])
    df["현재가"] = df["현재가"].astype(int)
    df["시가총액(억)"] = (df["시가총액"] / 1e8).astype(int)
    df = df.drop(columns=["시가총액"])

    sort_map = {"marcap": "시가총액(억)", "change": "등락률(%)", "volume": "거래량"}
    sort_col = sort_map.get(sort_by, "시가총액(억)")
    df = df.sort_values(sort_col, ascending=False).head(top_n).reset_index(drop=True)

    return {"market": market, "sort_by": sort_by, "count": len(df), "data": _df_to_records(df)}


@router.get("/universe/{market}")
def get_52w_high(
    market: str,
    force: bool = Query(False),
):
    """52주 신고가 종목"""
    from market_ranking import scan_52w_high
    df = scan_52w_high(market=market, use_cache=not force)
    return {"market": market, "count": len(df) if df is not None else 0, "data": _df_to_records(df)}


@router.post("/rs/{market}/refresh")
def refresh_rs_ranking(
    market: str,
    period: int = Query(60),
):
    """RS 랭킹 강제 재계산"""
    from market_ranking import calc_market_ranking
    df = calc_market_ranking(market=market, period=period, use_cache=False)
    return {"market": market, "period": period, "count": len(df), "refreshed": True}
