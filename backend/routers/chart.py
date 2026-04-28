"""
/api/chart/{ticker} — 종목 차트 데이터 + 재무 API
기존 relative_strength.py 함수를 래핑하여 JSON으로 반환
"""
from fastapi import APIRouter, Query, HTTPException
import numpy as np
import json
from pathlib import Path

router = APIRouter(tags=["chart"])


@router.get("/chart/{ticker}")
def get_chart_data(
    ticker: str,
    period: int = Query(60, ge=10, le=1000),
    benchmark: str = Query(None, description="벤치마크 코드 (미입력 시 자동)"),
):
    import pandas as pd
    from relative_strength import (
        detect_market, get_benchmark, get_stock_name,
        fetch_data, align_data, calculate_mas, trim_to_period,
        calculate_ibd_rs, calc_entry_signal, calc_sell_signal,
        calc_sell_pressure,
    )

    market = detect_market(ticker)

    if benchmark:
        bench_code, bench_name = benchmark, benchmark
    else:
        bench_code, bench_name = get_benchmark(ticker, market)

    try:
        stock_df, index_df = fetch_data(ticker, bench_code, period)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    stock_df, index_df = align_data(stock_df, index_df)
    mas = calculate_mas(stock_df["Close"])

    # 신호/ATR을 trim 전 전체 데이터로 계산 (rolling window NaN 방지)
    entry_signal_full = calc_entry_signal(stock_df)
    sell_signal_full = calc_sell_signal(stock_df)
    sell_pressure_full = calc_sell_pressure(stock_df)

    # ATR(20) — 전체 데이터로 계산
    _high = stock_df["High"]
    _low = stock_df["Low"]
    _prev_close = stock_df["Close"].shift(1)
    _tr = pd.concat([
        _high - _low,
        (_high - _prev_close).abs(),
        (_low - _prev_close).abs(),
    ], axis=1).max(axis=1)
    _atr20 = _tr.rolling(20, min_periods=1).mean()
    _atr_pct_full = _atr20 / stock_df["Close"] * 100

    # trim
    stock_trimmed, index_trimmed, mas_trimmed = trim_to_period(
        stock_df, index_df, mas, period
    )

    # 신호/ATR도 같은 기간으로 trim
    entry_trimmed = entry_signal_full.tail(period)
    sell_trimmed = sell_signal_full.tail(period)
    pressure_trimmed = sell_pressure_full.tail(period)
    atr_trimmed = _atr_pct_full.tail(period)

    # RS 계산 — 전체 기간으로 RS line 계산 후, 표시 기간 시작점=100 재정규화
    try:
        rs_line_full, _, _, _ = calculate_ibd_rs(stock_df, index_df)
        _, rs_score, stock_ret, index_ret = calculate_ibd_rs(
            stock_trimmed, index_trimmed
        )
        # 표시 기간 시작점을 기준으로 100 재정규화
        trim_start = stock_trimmed.index[0]
        if trim_start in rs_line_full.index:
            anchor = rs_line_full[trim_start]
        else:
            pos = rs_line_full.index.searchsorted(trim_start)
            anchor = rs_line_full.iloc[min(pos, len(rs_line_full) - 1)]
        rs_line = rs_line_full.reindex(stock_trimmed.index) / anchor * 100
    except Exception:
        rs_line = pd.Series(dtype=float)
        rs_score = 0
        stock_ret = 0
        index_ret = 0

    dates = [d.strftime("%Y-%m-%d") for d in stock_trimmed.index]
    name = get_stock_name(ticker, market)

    # 매매 마커 + 손절가/익절가
    trades = []
    stop_loss_price = None
    take_profit_price = None
    try:
        from portfolio import _load, set_portfolio_file, get_open_positions
        pf = "portfolio_us.json" if market == "US" else "portfolio.json"
        set_portfolio_file(pf)
        pf_data = _load()
        for pos in pf_data.get("positions", []):
            if pos["ticker"] == ticker:
                for t in pos.get("trades", []):
                    if dates[0] <= t["date"] <= dates[-1]:
                        trades.append({
                            "date": t["date"],
                            "type": t["type"],
                            "price": t.get("price", 0),
                            "quantity": t.get("quantity", 0),
                        })
                # 보유 중인 포지션의 손절가/익절가
                if pos.get("status") == "open":
                    # 손절가: stop_loss_history 최신 > trades의 마지막 buy > 포지션 최상위
                    history = pos.get("stop_loss_history", [])
                    buys = [t for t in pos.get("trades", []) if t["type"] == "buy"]
                    if history:
                        sl = history[-1].get("price", 0)
                    elif buys:
                        sl = buys[-1].get("stop_loss", 0)
                    else:
                        sl = pos.get("stop_loss", 0)
                    if sl and float(sl) > 0:
                        stop_loss_price = float(sl)

                    # 익절가: trades의 마지막 buy > 포지션 최상위
                    tp = buys[-1].get("take_profit", 0) if buys else pos.get("take_profit", 0)
                    if tp and float(tp) > 0:
                        # 1차 익절 실행 여부 확인 (매도 이력이 있으면 제거)
                        sells = [t for t in pos.get("trades", []) if t["type"] == "sell"]
                        if not sells:
                            take_profit_price = float(tp)
    except Exception:
        pass

    # 벤치마크 종가 (원본)
    bench_close = index_trimmed["Close"]

    return {
        "info": {
            "ticker": ticker,
            "name": name,
            "market": market,
            "benchmark": bench_name,
            "period": period,
        },
        "ohlcv": {
            "dates": dates,
            "open": [round(float(x), 2 if market == "US" else 0) for x in stock_trimmed["Open"].tolist()],
            "high": [round(float(x), 2 if market == "US" else 0) for x in stock_trimmed["High"].tolist()],
            "low": [round(float(x), 2 if market == "US" else 0) for x in stock_trimmed["Low"].tolist()],
            "close": [round(float(x), 2 if market == "US" else 0) for x in stock_trimmed["Close"].tolist()],
            "volume": [int(v) for v in stock_trimmed["Volume"].tolist()],
        },
        "ma": {
            k: [round(float(x), 2 if market == "US" else 0) if pd.notna(x) else None for x in v.tolist()]
            for k, v in mas_trimmed.items()
        },
        "rs": {
            "line": [round(float(x), 2) if pd.notna(x) else None for x in rs_line.tolist()],
            "score": round(float(rs_score), 2),
            "stock_return": round(float(stock_ret), 2),
            "index_return": round(float(index_ret), 2),
        },
        "benchmark_line": [round(float(x), 2 if market == "US" else 0) if pd.notna(x) else None for x in bench_close.tolist()],
        "signals": {
            "entry": [round(float(x), 3) for x in entry_trimmed.tolist()],
            "sell": [round(float(x), 3) for x in sell_trimmed.tolist()],
            "pressure": [round(float(x), 3) for x in pressure_trimmed.tolist()],
        },
        "atr": [round(float(x), 2) if not np.isnan(x) else None for x in atr_trimmed.tolist()],
        "vol_ma5": [round(float(x)) if pd.notna(x) else None for x in stock_trimmed["Volume"].rolling(5, min_periods=1).mean().tolist()],
        "vol_ma60": [round(float(x)) if pd.notna(x) else None for x in stock_trimmed["Volume"].rolling(60, min_periods=1).mean().tolist()],
        "trades": trades,
        "stop_loss": stop_loss_price,
        "take_profit": take_profit_price,
    }


@router.get("/chart/{ticker}/financials")
def get_financials(ticker: str):
    """회사개요 + 연간/분기 재무데이터"""
    import yfinance as yf
    import pandas as pd
    from relative_strength import detect_market

    market = detect_market(ticker)
    is_kr = (market == "KR")
    unit_label = "억원" if is_kr else "백만$"
    unit_div = 1e8 if is_kr else 1e6
    yf_sym = ticker + ".KS" if is_kr else ticker

    result = {"company": None, "annual": None, "quarterly": None}

    # 회사 개요
    try:
        t = yf.Ticker(yf_sym)
        info = t.info or {}
        if not info.get("longBusinessSummary") and is_kr:
            info = yf.Ticker(ticker + ".KQ").info or {}
        result["company"] = {
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "description": info.get("longBusinessSummary", ""),
            "marketCap": info.get("marketCap", 0),
        }
    except Exception:
        pass

    # 사용자 저장 설명
    desc_file = Path(__file__).parent.parent.parent / "company_desc.json"
    try:
        if desc_file.exists():
            custom = json.load(open(desc_file, encoding="utf-8"))
            if ticker in custom:
                result["custom_desc"] = custom[ticker]
    except Exception:
        pass

    # 네이버 fallback (한국 종목)
    if is_kr and (not result.get("company") or not result["company"].get("description")):
        try:
            import urllib.request
            from html.parser import HTMLParser
            url = "https://finance.naver.com/item/coinfo.naver?code=%s" % ticker
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode("euc-kr", errors="ignore")
            # 간단 파싱
            import re
            match = re.search(r'<p class="summary_info">(.*?)</p>', html, re.S)
            if match and result.get("company"):
                result["company"]["description"] = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        except Exception:
            pass

    # 재무 데이터
    def _build(raw, yoy_periods=1):
        if raw is None or raw.empty:
            return None
        needed = [r for r in ["Total Revenue", "Operating Income"] if r in raw.index]
        if not needed:
            return None
        df = raw.loc[needed].T.dropna(how="all").copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        rows = []
        for dt, row in df.iterrows():
            r = {"date": dt.strftime("%Y-%m")}
            if "Total Revenue" in row:
                r["revenue"] = round(float(row["Total Revenue"]) / unit_div, 1) if pd.notna(row["Total Revenue"]) else None
            if "Operating Income" in row:
                r["operating_income"] = round(float(row["Operating Income"]) / unit_div, 1) if pd.notna(row["Operating Income"]) else None
            rows.append(r)
        # 증가율 계산
        for i in range(len(rows)):
            if i >= yoy_periods:
                prev = rows[i - yoy_periods]
                if rows[i].get("revenue") and prev.get("revenue") and prev["revenue"] != 0:
                    rows[i]["revenue_growth"] = round((rows[i]["revenue"] / prev["revenue"] - 1) * 100, 1)
                if rows[i].get("operating_income") and prev.get("operating_income") and prev["operating_income"] != 0:
                    rows[i]["oi_growth"] = round((rows[i]["operating_income"] / prev["operating_income"] - 1) * 100, 1)
        return {"unit": unit_label, "data": list(reversed(rows))}

    try:
        t2 = yf.Ticker(yf_sym)
        annual = t2.financials
        quarter = t2.quarterly_financials
        if is_kr and (annual is None or annual.empty):
            t3 = yf.Ticker(ticker + ".KQ")
            annual = t3.financials
            quarter = t3.quarterly_financials
        result["annual"] = _build(annual, 1)
        result["quarterly"] = _build(quarter, 4)
    except Exception:
        pass

    return result
