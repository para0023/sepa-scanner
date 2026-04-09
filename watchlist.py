"""
그룹 Watchlist 관리 및 RS 계산 모듈
- 로컬 모드: JSON 파일 기반
- 클라우드 모드: Supabase DB 기반
"""
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import FinanceDataReader as fdr

from relative_strength import align_data, calculate_ibd_rs, get_stock_name

WATCHLIST_FILE        = Path(__file__).parent / "watchlists.json"
WATCHLIST_STOCKS_FILE = Path(__file__).parent / "watchlist_stocks.json"


def _is_cloud() -> bool:
    env_val = os.environ.get("SEPA_LOCAL")
    if env_val is not None:
        return env_val != "1"
    try:
        import streamlit as st
        return st.secrets.get("app", {}).get("SEPA_LOCAL", "1") != "1"
    except Exception:
        return False

def _get_user_id() -> str:
    try:
        import streamlit as st
        return st.session_state.get("user_id", "")
    except Exception:
        return ""

def _get_supabase():
    try:
        import streamlit as st
        return st.session_state.get("supabase_client")
    except Exception:
        return None

_CACHE_DIR = Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

KR_BENCHMARK = "KS11"   # 코스피
US_BENCHMARK = "^GSPC"  # S&P 500

MAX_WORKERS = 8
RS_PERIOD   = 252        # 1년 기준


# ─────────────────────────────────────────────
# 저장/로드
# ─────────────────────────────────────────────

def load_watchlists() -> dict:
    """{"KR": {"그룹명": ["ticker", ...]}, "US": {...}}"""
    if _is_cloud():
        return _load_watchlists_supabase()
    if not WATCHLIST_FILE.exists():
        return {"KR": {}, "US": {}}
    try:
        data = json.load(open(WATCHLIST_FILE, encoding="utf-8"))
        data.setdefault("KR", {})
        data.setdefault("US", {})
        return data
    except Exception:
        return {"KR": {}, "US": {}}


def save_watchlists(data: dict):
    if _is_cloud():
        _save_watchlists_supabase(data)
        return
    json.dump(data, open(WATCHLIST_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def _load_watchlists_supabase() -> dict:
    sb, uid = _get_supabase(), _get_user_id()
    if not sb or not uid:
        return {"KR": {}, "US": {}}
    try:
        res = sb.table("watchlist_groups").select("*").eq("user_id", uid).execute()
        result = {"KR": {}, "US": {}}
        for row in (res.data or []):
            market = row.get("market", "KR")
            result.setdefault(market, {})
            result[market][row["group_name"]] = row.get("tickers", [])
        return result
    except Exception:
        return {"KR": {}, "US": {}}


def _save_watchlists_supabase(data: dict):
    sb, uid = _get_supabase(), _get_user_id()
    if not sb or not uid:
        return
    try:
        sb.table("watchlist_groups").delete().eq("user_id", uid).execute()
        for market, groups in data.items():
            for group_name, tickers in groups.items():
                sb.table("watchlist_groups").insert({
                    "user_id": uid,
                    "market": market,
                    "group_name": group_name,
                    "tickers": tickers,
                }).execute()
    except Exception as e:
        print(f"[Supabase watchlist 저장 실패] {e}")


def add_group(market: str, group_name: str):
    data = load_watchlists()
    data[market].setdefault(group_name, [])
    save_watchlists(data)


def delete_group(market: str, group_name: str):
    data = load_watchlists()
    data[market].pop(group_name, None)
    save_watchlists(data)


def _resolve_kr_ticker(value: str) -> str:
    """한글 종목명이면 코드로 변환, 이미 코드면 그대로 반환"""
    value = value.strip()
    if value.isdigit():
        return value
    # "종목명  (코드)" 형식에서 코드 추출
    if "(" in value and ")" in value:
        return value.split("(")[-1].rstrip(")").strip()
    # 순수 한글 이름 → KRX 조회
    if any(ord(c) > 127 for c in value):
        try:
            import FinanceDataReader as _fdr
            krx = _fdr.StockListing("KRX")[["Code", "Name"]].dropna()
            match = krx[krx["Name"] == value]
            if not match.empty:
                return match.iloc[0]["Code"]
        except Exception:
            pass
    return value


def add_ticker(market: str, group_name: str, ticker: str):
    data = load_watchlists()
    tickers = data[market].setdefault(group_name, [])
    if market == "KR":
        ticker = _resolve_kr_ticker(ticker)
    else:
        ticker = ticker.strip().upper()
    if ticker and ticker not in tickers:
        tickers.append(ticker)
    save_watchlists(data)


def remove_ticker(market: str, group_name: str, ticker: str):
    data = load_watchlists()
    tickers = data[market].get(group_name, [])
    if ticker in tickers:
        tickers.remove(ticker)
    save_watchlists(data)


# ─────────────────────────────────────────────
# RS 계산
# ─────────────────────────────────────────────

def _calc_rs_single(ticker: str, market: str, benchmark_df: pd.DataFrame, period: int = RS_PERIOD) -> dict:
    """단일 종목 RS Score 계산"""
    try:
        end   = datetime.now()
        start = end - timedelta(days=RS_PERIOD * 2)
        stock_df = fdr.DataReader(ticker, start, end)
        if stock_df is None or stock_df.empty:
            return None
        stock_df = stock_df[~stock_df.index.duplicated(keep="last")].sort_index()
        stock_df, bench = align_data(stock_df, benchmark_df)
        # period 기간으로 자르기
        stock_df = stock_df.tail(period)
        bench    = bench.reindex(stock_df.index)
        if len(stock_df) < 20:
            return None
        _, rs_score, stock_ret, _ = calculate_ibd_rs(stock_df, bench)
        name = get_stock_name(ticker, market)
        current_price = stock_df["Close"].iloc[-1]
        return {
            "종목코드": ticker,
            "종목명":   name,
            "RS Score": round(rs_score, 1),
            "수익률(%)": round(stock_ret, 2),
            "현재가":   current_price,
        }
    except Exception:
        return None


def calc_group_rs(market: str, tickers: list, period: int = RS_PERIOD, progress_cb=None) -> pd.DataFrame:
    """
    그룹 내 종목들의 RS Score 계산.
    반환: DataFrame (종목코드, 종목명, RS Score, 수익률, 현재가)
    """
    if not tickers:
        return pd.DataFrame()

    benchmark_code = KR_BENCHMARK if market == "KR" else US_BENCHMARK

    # 벤치마크 데이터 한 번만 조회
    try:
        end   = datetime.now()
        start = end - timedelta(days=RS_PERIOD * 2)
        benchmark_df = fdr.DataReader(benchmark_code, start, end)
        benchmark_df = benchmark_df[~benchmark_df.index.duplicated(keep="last")].sort_index()
    except Exception:
        return pd.DataFrame()

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(_calc_rs_single, t, market, benchmark_df.copy(), period): t
            for t in tickers
        }
        for future in as_completed(future_map):
            done += 1
            if progress_cb:
                progress_cb(done, len(tickers))
            try:
                r = future.result(timeout=30)
                if r:
                    results.append(r)
            except Exception:
                pass

    if not results:
        return pd.DataFrame()

    # 종목명 일괄 보정: KRX 한 번만 조회
    if market == "KR":
        try:
            krx_map = dict(zip(
                *[fdr.StockListing("KRX")[c] for c in ["Code", "Name"]]
            ))
            for r in results:
                r["종목명"] = krx_map.get(r["종목코드"], r["종목명"])
        except Exception:
            pass

    df = pd.DataFrame(results).sort_values("RS Score", ascending=False).reset_index(drop=True)
    df.index = range(1, len(df) + 1)
    return df


# ─────────────────────────────────────────────
# 그룹 지수 (동일 비중) + RS Line 계산
# ─────────────────────────────────────────────

def _fetch_close(ticker: str) -> pd.Series:
    """종목 종가 시리즈 반환 (실패 시 None)"""
    try:
        end   = datetime.now()
        start = end - timedelta(days=RS_PERIOD * 2)
        df = fdr.DataReader(ticker, start, end)
        if df is None or df.empty:
            return None
        df = df[~df.index.duplicated(keep="last")].sort_index()
        s = df["Close"].dropna()
        return s if len(s) >= 20 else None
    except Exception:
        return None


def calc_group_index(market: str, tickers: list, period: int = 252):
    """
    동일 비중 그룹 지수 계산.
    - 공통 거래일 기준으로 각 종목 종가를 기준일(첫날) = 100 정규화
    - 종목별 평균 → 그룹 지수
    - 벤치마크도 동일 정규화
    - RS Line = 그룹지수 / 벤치마크지수 × 100

    반환: {
        "group_idx":    pd.Series (날짜 인덱스, 그룹 지수),
        "benchmark":    pd.Series (날짜 인덱스, 벤치마크 정규화),
        "rs_line":      pd.Series (날짜 인덱스, RS Line),
        "rs_score":     float,
        "group_ret":    float (%),
        "bench_ret":    float (%),
        "names":        dict {ticker: name},
        "valid_tickers": list,
    }
    """
    benchmark_code = KR_BENCHMARK if market == "KR" else US_BENCHMARK

    # 벤치마크 조회
    try:
        end   = datetime.now()
        start = end - timedelta(days=RS_PERIOD * 2)
        bench_raw = fdr.DataReader(benchmark_code, start, end)
        bench_raw = bench_raw[~bench_raw.index.duplicated(keep="last")].sort_index()
        bench_close = bench_raw["Close"].dropna()
    except Exception:
        return None

    # 종목별 종가 병렬 조회
    close_map = {}
    name_map  = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(_fetch_close, t): t for t in tickers}
        for future in as_completed(future_map):
            t = future_map[future]
            try:
                s = future.result(timeout=30)
                if s is not None:
                    close_map[t] = s
                    name_map[t]  = get_stock_name(t, market)
            except Exception:
                pass

    if not close_map:
        return None

    # 공통 날짜 교집합 (벤치마크 + 모든 종목)
    common_idx = bench_close.index
    for s in close_map.values():
        common_idx = common_idx.intersection(s.index)

    # 차트용: 최대 2년(504거래일)치 데이터 유지
    common_idx = common_idx.sort_values()
    if len(common_idx) > RS_PERIOD * 2:
        common_idx = common_idx[-RS_PERIOD * 2:]
    if len(common_idx) < 10:
        return None

    # 정규화 (기준일 = 100)
    normed = {}
    for t, s in close_map.items():
        aligned = s.reindex(common_idx).ffill()
        base    = aligned.iloc[0]
        if base > 0:
            normed[t] = aligned / base * 100

    if not normed:
        return None

    # 그룹 지수 = 동일 비중 평균 (전체 252일)
    group_idx = pd.DataFrame(normed).mean(axis=1)

    # 벤치마크 정규화
    bench_aligned = bench_close.reindex(common_idx).ffill()
    bench_normed  = bench_aligned / bench_aligned.iloc[0] * 100

    # RS Score / 수익률: period 구간 기준으로 계산
    calc_n  = min(period, len(group_idx))
    g_calc  = group_idx.iloc[-calc_n:]
    b_calc  = bench_normed.iloc[-calc_n:]
    q = max(1, calc_n // 4)
    g_recent = (g_calc.iloc[-1] / g_calc.iloc[-q] - 1) * 100
    g_older  = (g_calc.iloc[-q] / g_calc.iloc[0]  - 1) * 100
    b_recent = (b_calc.iloc[-1] / b_calc.iloc[-q] - 1) * 100
    b_older  = (b_calc.iloc[-q] / b_calc.iloc[0]  - 1) * 100
    rs_score = (2 * g_recent + g_older) - (2 * b_recent + b_older)

    group_ret = (g_calc.iloc[-1] / g_calc.iloc[0] - 1) * 100
    bench_ret = (b_calc.iloc[-1] / b_calc.iloc[0] - 1) * 100

    # RS Line: period 시작점을 100으로 정규화 (전체 기간 표시, period 기준점 변화)
    rs_ratio       = group_idx / bench_normed
    period_base    = rs_ratio.iloc[-calc_n]
    rs_line        = rs_ratio / period_base * 100

    return {
        "group_idx":     group_idx,
        "benchmark":     bench_normed,
        "rs_line":       rs_line,
        "rs_score":      round(rs_score, 1),
        "group_ret":     round(group_ret, 2),
        "bench_ret":     round(bench_ret, 2),
        "names":         name_map,
        "valid_tickers": list(normed.keys()),
    }


def build_group_chart(result: dict, group_name: str, benchmark_name: str) -> go.Figure:
    """그룹 지수 차트 — 개별 종목 차트와 동일한 삼성증권 스타일"""
    from relative_strength import C, calculate_mas, _signal_colors

    group_idx = result["group_idx"]   # pd.Series, 기준=100
    benchmark = result["benchmark"]   # pd.Series, 기준=100
    rs_line   = result["rs_line"]     # pd.Series
    rs_score  = result["rs_score"]
    group_ret = result["group_ret"]
    bench_ret = result["bench_ret"]

    # 이동평균 계산
    mas = calculate_mas(group_idx)

    # 수축신호 (가격수축, Close만 사용, 거래량 없음)
    window      = 3
    roll_range  = group_idx.rolling(window).max() - group_idx.rolling(window).min()
    price_ratio = roll_range / roll_range.shift(window)
    signal      = ((price_ratio - 0.3) / (1.5 - 0.3)).clip(0, 1).fillna(0.5)

    # 분배신호 (고저폭 급등 = 과열 경계)
    prev_val      = group_idx.shift(1).replace(0, 1e-9)
    expand_range  = (group_idx.rolling(window).max() - group_idx.rolling(window).min()) / prev_val
    expand_signal = (expand_range / 0.05 / 3.0).clip(0, 1).fillna(0)  # 15%면 1.0

    rs_color  = C["rs_up"]  if rs_score >= 0 else C["rs_down"]
    rs_label  = "강세 ▲"   if rs_score >= 0 else "약세 ▼"
    date_str  = group_idx.index[-1].strftime("%Y.%m.%d")

    rs_spread = max(float(rs_line.max() - rs_line.min()), 0.5)
    rs_pad    = rs_spread * 0.35
    rs_yrange = [float(rs_line.min()) - rs_pad, float(rs_line.max()) + rs_pad]

    # ── 4패널: 수축신호 / 분배신호 / 가격선 / RS ──
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.018,
        row_heights=[0.04, 0.04, 0.60, 0.28],
    )

    # Row 1: 수축신호 바
    fig.add_trace(go.Bar(
        x=group_idx.index,
        y=[1] * len(group_idx),
        marker_color=_signal_colors(signal),
        marker_line_width=0,
        width=24 * 3600 * 1000,
        showlegend=False,
        hovertemplate="수축신호: %{customdata:.2f}<extra></extra>",
        customdata=signal.values,
    ), row=1, col=1)

    fig.update_yaxes(
        showticklabels=False, showgrid=False, zeroline=False,
        row=1, col=1,
    )
    fig.add_annotation(
        x=0, y=0.5, xref="x domain", yref="y domain",
        text="수축신호", showarrow=False,
        xanchor="right", xshift=-6, textangle=0,
        font=dict(size=10, color="#222222"),
        row=1, col=1,
    )

    # Row 2: 분배신호 바
    fig.add_trace(go.Bar(
        x=group_idx.index,
        y=[1] * len(group_idx),
        marker_color=_signal_colors(expand_signal),
        marker_line_width=0,
        width=24 * 3600 * 1000,
        showlegend=False,
        hovertemplate="분배신호: %{customdata:.2f}<extra></extra>",
        customdata=expand_signal.values,
    ), row=2, col=1)

    fig.update_yaxes(
        showticklabels=False, showgrid=False, zeroline=False,
        row=2, col=1,
    )
    fig.add_annotation(
        x=0, y=0.5, xref="x domain", yref="y domain",
        text="분배신호", showarrow=False,
        xanchor="right", xshift=-6, textangle=0,
        font=dict(size=10, color="#222222"),
        row=2, col=1,
    )

    # Row 3: 그룹 지수선 + 벤치마크 비교선 + MA
    fig.add_trace(go.Scatter(
        x=benchmark.index, y=benchmark.values,
        mode="lines", name=benchmark_name,
        line=dict(color=C["index_line"], width=1.2, dash="dot"),
        opacity=0.75,
        hoverinfo="skip",
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=group_idx.index, y=group_idx.values,
        mode="lines", name=group_name,
        line=dict(color=C["up"], width=2),
        hovertemplate="<b>%{x|%Y.%m.%d}</b><br>그룹지수: <b>%{y:.2f}</b><extra></extra>",
    ), row=3, col=1)

    ma_lines = [
        ("MA5",   "ma5",   C["ma5"],   1.2),
        ("MA20",  "ma20",  C["ma20"],  1.2),
        ("MA60",  "ma60",  C["ma60"],  1.4),
        ("MA120", "ma120", C["ma120"], 1.4),
        ("MA200", "ma200", C["ma200"], 1.6),
    ]
    for label, key, color, width in ma_lines:
        fig.add_trace(go.Scatter(
            x=group_idx.index, y=mas[key],
            mode="lines", name=label,
            line=dict(color=color, width=width),
            hoverinfo="none",
        ), row=3, col=1)

    # Row 4: RS Line
    fig.add_hline(
        y=100,
        line=dict(color=C["rs_zero"], width=1, dash="dash"),
        row=4, col=1,
    )

    rs_line_color = C["rs_up"] if rs_line.iloc[-1] >= 100 else C["rs_down"]

    fig.add_trace(go.Scatter(
        x=rs_line.index, y=[100] * len(rs_line),
        mode="lines", line=dict(color="rgba(0,0,0,0)", width=0),
        showlegend=False, hoverinfo="skip",
    ), row=4, col=1)

    fig.add_trace(go.Scatter(
        x=rs_line.index, y=rs_line.values,
        mode="lines", name="RS Line",
        line=dict(color=rs_line_color, width=2),
        fill="tonexty",
        fillcolor=(
            "rgba(217,43,43,0.12)" if rs_line.iloc[-1] >= 100
            else "rgba(26,94,204,0.12)"
        ),
        hovertemplate="RS: %{y:.2f}<extra></extra>",
        showlegend=False,
    ), row=4, col=1)

    fig.add_annotation(
        x=rs_line.index[-1], y=rs_line.iloc[-1],
        text=f"<b>{rs_line.iloc[-1]:.2f}</b>",
        showarrow=False, xanchor="left", xshift=6,
        font=dict(color=rs_line_color, size=12),
        row=4, col=1,
    )

    # ── 타이틀 ────────────────────────────────────
    cur_val   = group_idx.iloc[-1]
    prev_val  = group_idx.iloc[-2] if len(group_idx) >= 2 else cur_val
    chg_pct   = (cur_val / prev_val - 1) * 100 if prev_val else 0
    chg_color = "#FF3333" if chg_pct >= 0 else "#3399FF"
    chg_sign  = "+" if chg_pct >= 0 else ""
    price_tag = (
        f"  <span style='font-size:15px;color:{chg_color}'>"
        f"{cur_val:.2f} ({chg_sign}{chg_pct:.2f}%)</span>"
    )
    title_text = (
        f"<b style='font-size:18px;color:{C['text']}'>{group_name} 그룹지수</b>{price_tag}"
        f"  <span style='color:{C['subtext']};font-size:13px'>"
        f"vs {benchmark_name}  |  {date_str}</span><br>"
        f"<span style='font-size:12px; color:{rs_color}'>"
        f"RS Score: <b>{rs_score:+.1f}</b>  {rs_label}"
        f"</span>"
        f"<span style='font-size:12px; color:{C['subtext']}'>"
        f"  &nbsp;|&nbsp; 그룹 {group_ret:+.2f}%"
        f"  &nbsp;|&nbsp; {benchmark_name} {bench_ret:+.2f}%"
        f"</span>"
    )

    # ── 기간 버튼 ─────────────────────────────────
    last_date      = group_idx.index[-1]
    range_end_disp = last_date + pd.Timedelta(days=3)
    x_end_str      = range_end_disp.strftime("%Y-%m-%d")

    def _period_relayout(cutoff):
        g_p  = group_idx[group_idx.index >= cutoff] if cutoff is not None else group_idx
        rs_p = rs_line[rs_line.index >= cutoff]     if cutoff is not None else rs_line
        if g_p.empty:
            g_p, rs_p = group_idx, rs_line
        g_lo, g_hi = float(g_p.min()), float(g_p.max())
        g_pad = (g_hi - g_lo) * 0.05
        rs_sp  = max(float(rs_p.max() - rs_p.min()), 0.5)
        rs_pv  = rs_sp * 0.35
        x_start = g_p.index[0].strftime("%Y-%m-%d")
        return {
            "xaxis.range[0]":  x_start,
            "xaxis.range[1]":  x_end_str,
            "yaxis3.range[0]": g_lo - g_pad,
            "yaxis3.range[1]": g_hi + g_pad,
            "yaxis4.range[0]": float(rs_p.min()) - rs_pv,
            "yaxis4.range[1]": float(rs_p.max()) + rs_pv,
        }

    _period_defs = [
        ("1개월", last_date - pd.DateOffset(months=1)),
        ("3개월", last_date - pd.DateOffset(months=3)),
        ("6개월", last_date - pd.DateOffset(months=6)),
        ("1년",   last_date - pd.DateOffset(years=1)),
        ("전체",  None),
    ]
    _menu_buttons = [
        dict(method="relayout", label=lbl, args=[_period_relayout(co)])
        for lbl, co in _period_defs
    ]

    # ── x축 rangebreaks ───────────────────────────
    trading_dates = set(idx.date() for idx in group_idx.index)
    all_weekdays  = pd.bdate_range(group_idx.index[0].date(), group_idx.index[-1].date())
    holiday_strs  = [d.strftime("%Y-%m-%d") for d in all_weekdays if d.date() not in trading_dates]
    rangebreaks   = [dict(bounds=["sat", "mon"])]
    if holiday_strs:
        rangebreaks.append(dict(values=holiday_strs))

    range_start = group_idx.index[-min(252, len(group_idx))]

    xaxis_common = dict(
        showgrid=True, gridcolor=C["grid"], linecolor="#CCCCCC",
        tickfont=dict(size=11, color=C["text"]),
        tickformat="%Y.%m.%d",
        tickangle=-30,
        rangebreaks=rangebreaks,
        range=[range_start, range_end_disp],
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikecolor="#AAAAAA",
        spikethickness=1,
        spikedash="dot",
    )

    axis_base = dict(
        showgrid=True, gridcolor=C["grid"], gridwidth=1,
        linecolor="#CCCCCC", tickfont=dict(size=11, color=C["text"]),
        title_font=dict(size=11, color="#222222"), zeroline=False,
    )

    fig.update_layout(
        title=dict(text=title_text, x=0.01, xanchor="left"),
        plot_bgcolor=C["bg"],
        paper_bgcolor=C["paper"],
        font=dict(color=C["text"], family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
        height=800,
        margin=dict(l=80, r=160, t=130, b=60),
        legend=dict(
            orientation="v",
            x=1.02, y=1,
            xanchor="left", yanchor="top",
            bgcolor="#FFFFFF",
            bordercolor="#999999", borderwidth=1,
            font=dict(size=11, color="#222222"),
        ),
        hovermode="closest",
        hoverdistance=10,
        spikedistance=-1,
        hoverlabel=dict(
            bgcolor="rgba(30,30,30,0.55)",
            bordercolor="rgba(120,120,120,0.6)",
            font=dict(color="#FFFFFF", size=12),
        ),
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False,
        updatemenus=[dict(
            type="buttons",
            direction="right",
            showactive=True,
            active=4,
            x=1.0, y=1.0,
            xanchor="right", yanchor="bottom",
            bgcolor="#F0F0F0",
            bordercolor="#CCCCCC",
            borderwidth=1,
            pad=dict(t=2, b=2, l=2, r=2),
            font=dict(size=10, color="#222222"),
            buttons=_menu_buttons,
        )],
    )

    fig.update_xaxes(**xaxis_common, showticklabels=False, row=1, col=1)
    fig.update_xaxes(**xaxis_common, showticklabels=False, row=2, col=1)
    fig.update_xaxes(**xaxis_common, showticklabels=False, row=3, col=1)
    fig.update_xaxes(
        **xaxis_common,
        showticklabels=True,
        rangeslider=dict(
            visible=True,
            thickness=0.05,
            bgcolor="#F0F0F0",
            bordercolor="#CCCCCC",
            borderwidth=1,
        ),
        row=4, col=1,
    )

    fig.update_yaxes(
        **axis_base,
        title_text="그룹지수 (기준=100)", tickformat=".2f",
        row=3, col=1,
    )
    fig.update_yaxes(
        **axis_base,
        title_text="RS", tickformat=".2f", range=rs_yrange,
        row=4, col=1,
    )

    return fig


# ─────────────────────────────────────────────
# 그룹 RS 랭킹 캐시
# ─────────────────────────────────────────────

def _group_rs_fingerprint(groups: dict) -> str:
    """그룹 구성(종목 목록)이 바뀌면 다른 값을 반환 → 캐시 무효화 감지"""
    parts = []
    for gname in sorted(groups.keys()):
        tickers = sorted(groups[gname])
        parts.append(f"{gname}:{','.join(tickers)}")
    return "|".join(parts)


def _group_rs_cache_path(market: str) -> Path:
    today = datetime.now().strftime("%Y%m%d")
    return _CACHE_DIR / f"group_rs_{market}_{today}.json"


def load_group_rs_cache(market: str, groups: dict):
    """당일 캐시가 있고 그룹 구성이 동일하면 rows 반환, 아니면 None"""
    path = _group_rs_cache_path(market)
    if not path.exists():
        return None
    try:
        data = json.load(open(path, encoding="utf-8"))
        if data.get("fingerprint") != _group_rs_fingerprint(groups):
            return None          # 그룹 구성 변경 → 캐시 무효
        return data["rows"]
    except Exception:
        return None


def save_group_rs_cache(market: str, groups: dict, rows: list):
    path = _group_rs_cache_path(market)
    try:
        payload = {
            "saved_at":   datetime.now().isoformat(),
            "fingerprint": _group_rs_fingerprint(groups),
            "rows":        rows,
        }
        json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────
# 관심종목 (진입 대기)
# ─────────────────────────────────────────────

def load_watchlist_stocks() -> dict:
    """{\"KR\": [{ticker, name, reason, condition, added_date}, ...], \"US\": [...]}"""
    if _is_cloud():
        return _load_watchlist_stocks_supabase()
    if not WATCHLIST_STOCKS_FILE.exists():
        return {"KR": [], "US": []}
    try:
        data = json.load(open(WATCHLIST_STOCKS_FILE, encoding="utf-8"))
        data.setdefault("KR", [])
        data.setdefault("US", [])
        return data
    except Exception:
        return {"KR": [], "US": []}


def save_watchlist_stocks(data: dict):
    if _is_cloud():
        _save_watchlist_stocks_supabase(data)
        return
    json.dump(data, open(WATCHLIST_STOCKS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def _load_watchlist_stocks_supabase() -> dict:
    sb, uid = _get_supabase(), _get_user_id()
    if not sb or not uid:
        return {"KR": [], "US": []}
    try:
        res = sb.table("watchlist_stocks").select("*").eq("user_id", uid).execute()
        result = {"KR": [], "US": []}
        for row in (res.data or []):
            market = row.get("market", "KR")
            result.setdefault(market, [])
            result[market].append({
                "ticker": row["ticker"],
                "name": row.get("name", ""),
                "reason": row.get("wait_reason", ""),
                "condition": row.get("entry_condition", ""),
                "added_date": row.get("added_date", ""),
            })
        return result
    except Exception:
        return {"KR": [], "US": []}


def _save_watchlist_stocks_supabase(data: dict):
    sb, uid = _get_supabase(), _get_user_id()
    if not sb or not uid:
        return
    try:
        sb.table("watchlist_stocks").delete().eq("user_id", uid).execute()
        for market, stocks in data.items():
            for s in stocks:
                sb.table("watchlist_stocks").upsert({
                    "user_id": uid,
                    "ticker": s["ticker"],
                    "name": s.get("name", ""),
                    "market": market,
                    "wait_reason": s.get("reason", ""),
                    "entry_condition": s.get("condition", ""),
                    "added_date": s.get("added_date", ""),
                }).execute()
    except Exception as e:
        print(f"[Supabase watchlist_stocks 저장 실패] {e}")


def add_watchlist_stock(market: str, ticker: str, name: str = "",
                        reason: str = "", condition: str = ""):
    data = load_watchlist_stocks()
    if any(s["ticker"] == ticker for s in data[market]):
        return
    data[market].append({
        "ticker":     ticker,
        "name":       name,
        "reason":     reason,
        "condition":  condition,
        "added_date": datetime.now().strftime("%Y-%m-%d"),
    })
    save_watchlist_stocks(data)


def remove_watchlist_stock(market: str, ticker: str):
    data = load_watchlist_stocks()
    data[market] = [s for s in data[market] if s["ticker"] != ticker]
    save_watchlist_stocks(data)


def update_watchlist_stock(market: str, ticker: str, reason: str, condition: str):
    data = load_watchlist_stocks()
    for s in data[market]:
        if s["ticker"] == ticker:
            s["reason"]    = reason
            s["condition"] = condition
            break
    save_watchlist_stocks(data)
