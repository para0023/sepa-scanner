"""
/api/chart/{ticker} — 종목 차트 데이터 API
기존 relative_strength.py 함수를 래핑하여 JSON으로 반환
"""
from fastapi import APIRouter, Query, HTTPException
import numpy as np

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

    # 매매 마커 데이터
    trades = []
    try:
        from portfolio import _load, set_portfolio_file
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
            "open": [round(float(x)) for x in stock_trimmed["Open"].tolist()],
            "high": [round(float(x)) for x in stock_trimmed["High"].tolist()],
            "low": [round(float(x)) for x in stock_trimmed["Low"].tolist()],
            "close": [round(float(x)) for x in stock_trimmed["Close"].tolist()],
            "volume": [int(v) for v in stock_trimmed["Volume"].tolist()],
        },
        "ma": {
            k: [round(float(x)) if pd.notna(x) else None for x in v.tolist()]
            for k, v in mas_trimmed.items()
        },
        "rs": {
            "line": [round(float(x), 2) if pd.notna(x) else None for x in rs_line.tolist()],
            "score": round(float(rs_score), 2),
            "stock_return": round(float(stock_ret), 2),
            "index_return": round(float(index_ret), 2),
        },
        "benchmark_line": [round(float(x)) if pd.notna(x) else None for x in bench_close.tolist()],
        "signals": {
            "entry": [round(float(x), 3) for x in entry_trimmed.tolist()],
            "sell": [round(float(x), 3) for x in sell_trimmed.tolist()],
            "pressure": [round(float(x), 3) for x in pressure_trimmed.tolist()],
        },
        "atr": [round(float(x), 2) if not np.isnan(x) else None for x in atr_trimmed.tolist()],
        "trades": trades,
    }
