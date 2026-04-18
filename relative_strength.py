#!/usr/bin/env python3
"""
IBD 스타일 상대강도(Relative Strength) 분석기
한국(KOSPI/KOSDAQ) 및 미국 주식 지원

사용법:
  python relative_strength.py 005930          # 삼성전자 (20일 기본)
  python relative_strength.py AAPL            # 애플 (20일 기본)
  python relative_strength.py 005930 -p 60    # 삼성전자 60일
  python relative_strength.py TSLA -b QQQ     # 나스닥 대비
  python relative_strength.py 005930 --save samsung_rs.html
"""

import argparse
import sys
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ─────────────────────────────────────────────
# 색상 팔레트 (삼성증권 스타일)
# ─────────────────────────────────────────────
C = {
    "bg":         "#FFFFFF",
    "paper":      "#F5F5F5",
    "grid":       "#E8E8E8",
    "up":         "#D92B2B",
    "down":       "#1A5ECC",
    "up_light":   "#FFAAAA",
    "down_light": "#AAC4FF",
    "ma5":        "#FF6D00",
    "ma20":       "#8A2BE2",
    "ma60":       "#008000",
    "wma100":     "#FFFFFF",
    "ma120":      "#008B8B",
    "ma200":      "#C0392B",
    "index_line": "#2ECC71",
    "rs_up":      "#D92B2B",
    "rs_down":    "#1A5ECC",
    "rs_zero":    "#888888",
    "text":       "#222222",
    "subtext":    "#555555",
}


# ─────────────────────────────────────────────
# 1. 시장 감지 & 종목명 조회
# ─────────────────────────────────────────────

def detect_market(ticker: str) -> str:
    """한국(KR) / 미국(US) 시장 자동 감지"""
    return "KR" if ticker.isdigit() else "US"


def _is_kosdaq(ticker: str) -> bool:
    """코스닥 상장 종목 여부 확인"""
    try:
        import FinanceDataReader as _fdr
        listing = _fdr.StockListing("KOSDAQ")
        return ticker in listing["Code"].values
    except Exception:
        return False


def get_benchmark(ticker: str, market: str = None):
    """기본 벤치마크 반환 (code, display_name)"""
    if market is None:
        market = detect_market(ticker)
    if market != "KR":
        return ("^GSPC", "S&P 500")
    if _is_kosdaq(ticker):
        return ("KQ11", "KOSDAQ")
    return ("KS11", "KOSPI")


_US_NAME_CACHE: dict = {}  # ticker → name 메모리 캐시

def get_stock_name(ticker: str, market: str) -> str:
    """종목명 조회 (실패 시 ticker 반환)"""
    if market == "KR":
        try:
            listing = fdr.StockListing("KRX")
            match = listing[listing["Code"] == ticker]
            if not match.empty:
                return match.iloc[0]["Name"]
        except Exception:
            pass
    else:
        if ticker in _US_NAME_CACHE:
            return _US_NAME_CACHE[ticker]
        for exchange in ("NASDAQ", "NYSE"):
            try:
                listing = fdr.StockListing(exchange)
                listing.columns = [c.strip() for c in listing.columns]
                code_col = next((c for c in listing.columns if c in ("Symbol", "Code")), None)
                name_col = next((c for c in listing.columns if c in ("Name", "종목명")), None)
                if code_col and name_col:
                    match = listing[listing[code_col] == ticker]
                    if not match.empty:
                        name = str(match.iloc[0][name_col])
                        _US_NAME_CACHE[ticker] = name
                        return name
            except Exception:
                continue
    return ticker


# ─────────────────────────────────────────────
# 2. 데이터 수집
# ─────────────────────────────────────────────

def fetch_data(ticker: str, benchmark_code: str, period: int):
    """
    MA200 계산을 위해 period + 넉넉한 버퍼(350 거래일분) 데이터 수집.
    """
    # MA200 계산 위해 최소 200 거래일 + 여유분 확보
    fetch_days = max(max(period, 200) * 2 + 150, 1100)  # 최소 3년(1100 캘린더일)
    end_date   = datetime.now()
    start_date = end_date - timedelta(days=fetch_days)

    print(f"  [{ticker}] 데이터 수집 중...")
    stock_df = fdr.DataReader(ticker, start_date, end_date)
    stock_df = stock_df[~stock_df.index.duplicated(keep='last')]
    stock_df = stock_df.dropna(subset=["Close"])  # 장중 NaN 제거

    print(f"  [{benchmark_code}] 벤치마크 수집 중...")
    index_df = fdr.DataReader(benchmark_code, start_date, end_date)
    index_df = index_df[~index_df.index.duplicated(keep='last')]
    index_df = index_df.dropna(subset=["Close"])  # 장중 NaN 제거

    if stock_df.empty:
        raise ValueError(f"종목 데이터를 찾을 수 없습니다: {ticker}")
    if index_df.empty:
        raise ValueError(f"벤치마크 데이터를 찾을 수 없습니다: {benchmark_code}")

    return stock_df, index_df


def align_data(stock_df: pd.DataFrame, index_df: pd.DataFrame):
    """공통 거래일만 추출 (전체 데이터 유지, 이동평균 계산용)"""
    # 중복 인덱스 제거 후 교집합
    stock_df = stock_df[~stock_df.index.duplicated(keep='last')]
    index_df = index_df[~index_df.index.duplicated(keep='last')]
    common = stock_df.index.intersection(index_df.index)
    return stock_df.loc[common].sort_index(), index_df.loc[common].sort_index()


def trim_to_period(stock_df, index_df, mas: dict, period: int):
    """차트 표시 기간으로 자르기 (MA는 이미 계산된 값 trim)"""
    s = stock_df.tail(period)
    i = index_df.tail(period)
    m = {k: v.tail(period) for k, v in mas.items()}
    return s, i, m


# ─────────────────────────────────────────────
# 3. 이동평균 계산
# ─────────────────────────────────────────────

def _wma(series: pd.Series, window: int) -> pd.Series:
    """선형 가중이동평균 (WMA): 최근 데이터에 높은 가중치"""
    def _apply(x):
        w = np.arange(1, len(x) + 1, dtype=float)
        return np.dot(x, w) / w.sum()
    return series.rolling(window=window, min_periods=1).apply(_apply, raw=True)


def calculate_mas(close: pd.Series) -> dict:
    """
    전체 시계열 기준으로 이동평균 계산.
    (trim 전에 호출해야 MA값이 정확함)
    """
    return {
        "ma5":    close.rolling(5,   min_periods=1).mean(),
        "ma20":   close.rolling(20,  min_periods=1).mean(),
        "ma60":   close.rolling(60,  min_periods=1).mean(),
        "wma100": _wma(close, 100),
        "ma120":  close.rolling(120, min_periods=1).mean(),
        "ma200":  close.rolling(200, min_periods=1).mean(),
    }


# ─────────────────────────────────────────────
# 4. IBD 스타일 RS 계산
# ─────────────────────────────────────────────

def calculate_ibd_rs(stock_df: pd.DataFrame, index_df: pd.DataFrame):
    """
    IBD RS 계산:
    - 기간을 4등분, 최근 1/4 구간에 2배 가중
    - RS Score = 종목 가중수익률 - 지수 가중수익률
    - RS Line  = 정규화된 (종목가격 / 지수가격) × 100
    """
    n = len(stock_df)
    if n < 4:
        raise ValueError("RS 계산에 필요한 데이터가 부족합니다 (최소 4일).")

    close_s = stock_df["Close"]
    close_i = index_df["Close"]

    rs_line = (close_s / close_i) / (close_s.iloc[0] / close_i.iloc[0]) * 100

    quarter = max(1, n // 4)
    stock_recent = (close_s.iloc[-1]       / close_s.iloc[-quarter] - 1) * 100
    index_recent = (close_i.iloc[-1]       / close_i.iloc[-quarter] - 1) * 100
    stock_older  = (close_s.iloc[-quarter] / close_s.iloc[0]        - 1) * 100
    index_older  = (close_i.iloc[-quarter] / close_i.iloc[0]        - 1) * 100

    rs_score  = (2 * stock_recent + stock_older) - (2 * index_recent + index_older)
    stock_ret = (close_s.iloc[-1] / close_s.iloc[0] - 1) * 100
    index_ret = (close_i.iloc[-1] / close_i.iloc[0] - 1) * 100

    return rs_line, rs_score, stock_ret, index_ret


# ─────────────────────────────────────────────
# 5. 진입신호 계산
# ─────────────────────────────────────────────

def calc_entry_signal(stock_df: pd.DataFrame, window: int = 3, vol_period: int = 60) -> pd.Series:
    """
    가격수축 + 거래량수축 합산 점수 (0=최적, 1=최악)
    - 가격수축: 최근 window일 고저범위 / 이전 window일 고저범위
    - 거래량수축: 최근 5일 평균 / vol_period일 평균
    """
    # 가격 수축
    roll_range  = stock_df["High"].rolling(window).max() - stock_df["Low"].rolling(window).min()
    price_ratio = roll_range / roll_range.shift(window)
    price_score = ((price_ratio - 0.3) / (1.5 - 0.3)).clip(0, 1)

    # 거래량 수축
    vol_ma_long  = stock_df["Volume"].rolling(vol_period).mean()
    vol_ma_short = stock_df["Volume"].rolling(5).mean()
    vol_ratio    = vol_ma_short / vol_ma_long
    vol_score    = ((vol_ratio - 0.3) / (1.5 - 0.3)).clip(0, 1)

    return ((price_score + vol_score) / 2).fillna(0.5)


def calc_sell_signal(stock_df: pd.DataFrame, vol_period: int = 60) -> pd.Series:
    """
    매도신호 강도 (0=조용함/녹색, 1+=과열/빨간색)
    - 고저폭 강도: (High - Low) / 전일종가 ÷ 0.10  (10%가 기준=1.0)
    - 거래량 강도: 당일 Volume / 60일 평균           (1배=기준)
    두 강도를 평균 → 0~1 클립 후 색상 반영
      0.0~0.33 → 녹색 (기준 이하)
      0.33~0.66 → 노란색 (주의)
      0.66~1.0  → 빨간색 (강한 신호)
    """
    prev_close  = stock_df["Close"].shift(1).replace(0, 1e-9)
    range_pct   = (stock_df["High"] - stock_df["Low"]) / prev_close
    range_score = (range_pct / 0.05).clip(0, 1)          # 5%면 1.0

    avg_vol   = stock_df["Volume"].rolling(vol_period).mean().replace(0, 1e-9)
    vol_ratio = stock_df["Volume"] / avg_vol
    vol_score = ((vol_ratio - 0.7) / 0.8).clip(0, 1)     # 0.7배 시작, 1.5배면 1.0

    # 종가 위치 계수: 50~70% 선형 감소, 70% 이상이면 신호 완전 제거
    hl           = (stock_df["High"] - stock_df["Low"]).replace(0, 1e-9)
    close_pos    = (stock_df["Close"] - stock_df["Low"]) / hl
    close_factor = 1 - ((close_pos - 0.5) / 0.2).clip(0, 1)

    return (((range_score + vol_score) / 2) * close_factor).clip(0, 1).fillna(0)


def calc_sell_pressure(stock_df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    매도압력 점수 (0=압력 낮음/매수우세, 1=압력 높음/매도우세)
    CMF(Chaikin Money Flow) 기반:
      MFM = ((Close - Low) - (High - Close)) / (High - Low)  → 종가 위치 (-1~+1)
      MFV = MFM * Volume
      CMF = Sum(MFV, period) / Sum(Volume, period)
    CMF 양수 → 매수압력, 음수 → 매도압력
    → 0~1 정규화: 0=매수압력 강함(녹색), 1=매도압력 강함(빨간색)
    """
    hl = stock_df["High"] - stock_df["Low"]
    hl = hl.replace(0, 1e-9)
    mfm = ((stock_df["Close"] - stock_df["Low"]) - (stock_df["High"] - stock_df["Close"])) / hl
    mfv = mfm * stock_df["Volume"]
    cmf = mfv.rolling(period).sum() / stock_df["Volume"].rolling(period).sum()
    # CMF 범위 -1~+1 → 0(매수강함)~1(매도강함)으로 변환
    pressure = ((-cmf + 1) / 2).clip(0, 1)
    return pressure.fillna(0.5)


def _signal_colors(scores: pd.Series) -> list:
    """점수(0=녹색, 1=빨간색)를 색상 리스트로 변환"""
    colors = []
    for s in scores:
        if s <= 0.33:
            colors.append("rgba(39,174,96,0.85)")   # 녹색
        elif s <= 0.66:
            colors.append("rgba(243,156,18,0.85)")  # 노란색
        else:
            colors.append("rgba(192,57,43,0.85)")   # 빨간색
    return colors


# ─────────────────────────────────────────────
# 6. 차트 생성
# ─────────────────────────────────────────────

def build_chart(
    ticker: str,
    stock_name: str,
    benchmark_name: str,
    market: str,
    period: int,
    stock_df: pd.DataFrame,
    index_df: pd.DataFrame,
    mas: dict,
    rs_line: pd.Series,
    rs_score: float,
    stock_ret: float,
    index_ret: float,
    trades: list = None,
) -> go.Figure:
    """
    삼성증권 스타일 3패널 차트
      Row 1 (58%): 캔들스틱 + MA5/20/60/WMA100/120/200 + 지수비교선
      Row 2 (12%): 거래량
      Row 3 (30%): RS Line
    """
    rs_color  = C["rs_up"]  if rs_score >= 0 else C["rs_down"]
    rs_label  = "강세 ▲"   if rs_score >= 0 else "약세 ▼"
    date_str  = stock_df.index[-1].strftime("%Y.%m.%d")

    # y축 단위
    is_kr      = (market == "KR")
    price_sfx  = "원" if is_kr else ""
    price_pfx  = ""  if is_kr else "$"
    price_fmt  = ","  if is_kr else ",.2f"

    # 지수 비교선: 주가 시작점 기준 정규화
    idx_norm = index_df["Close"] / index_df["Close"].iloc[0] * stock_df["Close"].iloc[0]

    # RS y축 tight range
    rs_spread = max(rs_line.max() - rs_line.min(), 0.5)
    rs_pad    = rs_spread * 0.35
    rs_yrange = [rs_line.min() - rs_pad, rs_line.max() + rs_pad]

    # ── 서브플롯 ─────────────────────────────
    signal      = calc_entry_signal(stock_df)
    sell_signal = calc_sell_signal(stock_df)

    fig = make_subplots(
        rows=5, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.018,
        row_heights=[0.04, 0.04, 0.48, 0.12, 0.28],
    )

    # ════════════════════════════════
    # Row 1: 진입신호 바
    # ════════════════════════════════
    fig.add_trace(go.Bar(
        x=stock_df.index,
        y=[1] * len(stock_df),
        marker_color=_signal_colors(signal),
        marker_line_width=0,
        width=24 * 3600 * 1000,
        showlegend=False,
        hovertemplate="진입신호: %{customdata:.2f}<extra></extra>",
        customdata=signal.values,
    ), row=1, col=1)

    fig.update_yaxes(
        showticklabels=False, showgrid=False, zeroline=False,
        row=1, col=1,
    )
    fig.add_annotation(
        x=0, y=0.5, xref="x domain", yref="y domain",
        text="진입신호", showarrow=False,
        xanchor="right", xshift=-6, textangle=0,
        font=dict(size=10, color="#222222"),
        row=1, col=1,
    )

    # ════════════════════════════════
    # Row 2: 분배신호 바
    # ════════════════════════════════
    fig.add_trace(go.Bar(
        x=stock_df.index,
        y=[1] * len(stock_df),
        marker_color=_signal_colors(sell_signal),
        marker_line_width=0,
        width=24 * 3600 * 1000,
        showlegend=False,
        hovertemplate="분배신호: %{customdata:.2f}<extra></extra>",
        customdata=sell_signal.values,
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

    # ════════════════════════════════
    # Row 3: 가격 패널
    # ════════════════════════════════

    # 지수 비교선
    fig.add_trace(go.Scatter(
        x=index_df.index, y=idx_norm,
        mode="lines", name=benchmark_name,
        line=dict(color=C["index_line"], width=1.2, dash="dot"),
        opacity=0.75,
        hoverinfo="skip",
    ), row=3, col=1)

    # 캔들스틱
    # 호버용 customdata: [High, Low, Close, MA5, MA20, MA60, WMA100, DailyChg%]
    daily_chg = stock_df["Close"].pct_change().fillna(0) * 100
    customdata = np.column_stack([
        stock_df["High"].values,
        stock_df["Low"].values,
        stock_df["Close"].values,
        mas["ma5"].values,
        mas["ma20"].values,
        mas["ma60"].values,
        mas["wma100"].values,
        daily_chg.values,
    ])

    if is_kr:
        hover_fmt = (
            "<b>%{x|%Y.%m.%d}</b><br>"
            "──────────────<br>"
            "종가:    <b>%{customdata[2]:,.0f}원</b> (%{customdata[7]:+.2f}%)<br>"
            "고가:    %{customdata[0]:,.0f}원<br>"
            "저가:    %{customdata[1]:,.0f}원<br>"
            "──────────────<br>"
            "MA5:     %{customdata[3]:,.0f}원<br>"
            "MA20:    %{customdata[4]:,.0f}원<br>"
            "MA60:    %{customdata[5]:,.0f}원<br>"
            "WMA100:  %{customdata[6]:,.0f}원<br>"
            "<extra></extra>"
        )
    else:
        hover_fmt = (
            "<b>%{x|%Y.%m.%d}</b><br>"
            "──────────────<br>"
            "종가:    <b>$%{customdata[2]:,.2f}</b> (%{customdata[7]:+.2f}%)<br>"
            "고가:    $%{customdata[0]:,.2f}<br>"
            "저가:    $%{customdata[1]:,.2f}<br>"
            "──────────────<br>"
            "MA5:     $%{customdata[3]:,.2f}<br>"
            "MA20:    $%{customdata[4]:,.2f}<br>"
            "MA60:    $%{customdata[5]:,.2f}<br>"
            "WMA100:  $%{customdata[6]:,.2f}<br>"
            "<extra></extra>"
        )

    # 커스텀 호버용 투명 scatter (High / Low 두 곳에 배치 → 캔들 어디서 호버해도 캔들 정보 우선)
    for _y in [stock_df["High"], stock_df["Low"]]:
        fig.add_trace(go.Scatter(
            x=stock_df.index,
            y=_y,
            mode="markers",
            marker=dict(opacity=0, size=16),
            customdata=customdata,
            hovertemplate=hover_fmt,
            showlegend=False,
            name="",
        ), row=3, col=1)

    fig.add_trace(go.Candlestick(
        x=stock_df.index,
        open=stock_df["Open"],
        high=stock_df["High"],
        low=stock_df["Low"],
        close=stock_df["Close"],
        name=f"{ticker}",
        increasing=dict(line=dict(color=C["up"],   width=1), fillcolor=C["up"]),
        decreasing=dict(line=dict(color=C["down"], width=1), fillcolor=C["down"]),
        whiskerwidth=0.3,
        hoverinfo="skip",
    ), row=3, col=1)

    # 이동평균선
    ma_lines = [
        ("MA5",    "ma5",    C["ma5"],    1.2),
        ("MA20",   "ma20",   C["ma20"],   1.2),
        ("MA60",   "ma60",   C["ma60"],   1.4),
        ("WMA100", "wma100", C["wma100"], 1.6),
        ("MA120",  "ma120",  C["ma120"],  1.4),
        ("MA200",  "ma200",  C["ma200"],  1.6),
    ]
    for label, key, color, width in ma_lines:
        fig.add_trace(go.Scatter(
            x=stock_df.index,
            y=mas[key],
            mode="lines",
            name=label,
            line=dict(color=color, width=width),
            hoverinfo="none",
        ), row=3, col=1)

    # ════════════════════════════════
    # Row 4: 거래량 패널
    # ════════════════════════════════
    if "Volume" in stock_df.columns:
        vol_colors = [
            C["up"] if c >= o else C["down"]
            for c, o in zip(stock_df["Close"], stock_df["Open"])
        ]
        fig.add_trace(go.Bar(
            x=stock_df.index,
            y=stock_df["Volume"],
            name="거래량",
            marker_color=vol_colors,
            showlegend=False,
            hovertemplate="<b>%{x|%Y.%m.%d}</b><br>거래량: %{y:,.0f}<extra></extra>",
        ), row=4, col=1)

        vol_ma60 = stock_df["Volume"].rolling(60, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=stock_df.index,
            y=vol_ma60,
            name="거래량MA60",
            line=dict(color="#f39c12", width=1.5),
            showlegend=False,
            hovertemplate="MA60: %{y:,.0f}<extra></extra>",
        ), row=4, col=1)

    # ════════════════════════════════
    # Row 5: RS Line 패널
    # ════════════════════════════════
    fig.add_hline(
        y=100,
        line=dict(color=C["rs_zero"], width=1, dash="dash"),
        row=5, col=1,
    )

    rs_line_color = C["rs_up"] if rs_line.iloc[-1] >= 100 else C["rs_down"]

    fig.add_trace(go.Scatter(
        x=rs_line.index, y=[100] * len(rs_line),
        mode="lines", line=dict(color="rgba(0,0,0,0)", width=0),
        showlegend=False, hoverinfo="skip",
    ), row=5, col=1)

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
    ), row=5, col=1)

    fig.add_annotation(
        x=rs_line.index[-1], y=rs_line.iloc[-1],
        text=f"<b>{rs_line.iloc[-1]:.2f}</b>",
        showarrow=False, xanchor="left", xshift=6,
        font=dict(color=rs_color, size=12),
        row=5, col=1,
    )

    # ════════════════════════════════
    # 매매 마커 (가격 패널 오버레이)
    # ════════════════════════════════
    if trades:
        is_kr_fmt = (market == "KR")
        price_unit = "원" if is_kr_fmt else ""
        price_fmt_hover = ",.0f" if is_kr_fmt else ",.2f"

        buys  = [t for t in trades if t["type"] == "buy"]
        sells = [t for t in trades if t["type"] == "sell"]

        # 마커 y축 오프셋: 차트 가격 범위의 3%
        price_range = stock_df["High"].max() - stock_df["Low"].min()
        offset = price_range * 0.03

        if buys:
            raw_buy_dates = pd.to_datetime([t["date"] for t in buys])
            # 주말/공휴일이면 차트에 해당 날짜가 없으므로 가장 가까운 이전 거래일로 snap
            trading_dates = stock_df.index.normalize().unique()
            def _snap_to_trading_day(d):
                d_norm = d.normalize()
                past = trading_dates[trading_dates <= d_norm]
                return past[-1] if len(past) > 0 else d_norm
            buy_dates = pd.DatetimeIndex([_snap_to_trading_day(d) for d in raw_buy_dates])

            buy_y = [
                stock_df.loc[stock_df.index.normalize() == d, "Low"].min() - offset * 2
                if len(stock_df[stock_df.index.normalize() == d]) > 0
                else t["price"] - offset * 2
                for d, t in zip(buy_dates, buys)
            ]

            fig.add_trace(go.Scatter(
                x=buy_dates,
                y=buy_y,
                mode="markers",
                marker=dict(
                    symbol="triangle-up",
                    size=10,
                    color="rgba(39,174,96,0.9)",
                    line=dict(color="rgba(20,120,50,1)", width=1),
                ),
                name="매수",
                customdata=[[t["price"], t["quantity"], t["label"]] for t in buys],
                hovertemplate=(
                    f"<b>매수</b><br>"
                    f"단가: %{{customdata[0]:{price_fmt_hover}}}{price_unit}<br>"
                    "수량: %{customdata[1]}주<br>"
                    "근거: %{customdata[2]}<extra></extra>"
                ),
                showlegend=True,
            ), row=3, col=1)

            # 평균매수가 수평선 (현재 오픈 포지션의 매수만)
            open_buys = [t for t in buys if t.get("position_status") == "open"]
            open_sells = [t for t in sells if t.get("position_status") == "open"]
            if not open_buys:
                open_buys = buys
                open_sells = sells
            total_cost = sum(t["price"] * t["quantity"] for t in open_buys)
            total_qty  = sum(t["quantity"] for t in open_buys)
            sold_qty   = sum(t["quantity"] for t in open_sells)
            remaining  = total_qty - sold_qty
            if remaining > 0 and total_qty > 0:
                avg_buy_price = total_cost / total_qty
                fmt = ",.0f" if is_kr_fmt else ",.2f"
                fig.add_hline(
                    y=avg_buy_price,
                    line=dict(color="rgba(39,174,96,0.75)", width=2, dash="dash"),
                    row=3, col=1,
                )
                fig.add_annotation(
                    x=1, y=avg_buy_price,
                    xref="x3 domain", yref="y3",
                    text=f"<b>{avg_buy_price:{fmt}}</b>",
                    showarrow=False,
                    xanchor="left",
                    xshift=8,
                    font=dict(size=10, color="rgba(39,174,96,0.9)"),
                )

        if sells:
            raw_sell_dates = pd.to_datetime([t["date"] for t in sells])
            sell_dates = pd.DatetimeIndex([_snap_to_trading_day(d) for d in raw_sell_dates])

            sell_y = [
                stock_df.loc[stock_df.index.normalize() == d, "High"].max() + offset * 2
                if len(stock_df[stock_df.index.normalize() == d]) > 0
                else t["price"] + offset * 2
                for d, t in zip(sell_dates, sells)
            ]

            fig.add_trace(go.Scatter(
                x=sell_dates,
                y=sell_y,
                mode="markers",
                marker=dict(
                    symbol="triangle-down",
                    size=10,
                    color="rgba(192,57,43,0.9)",
                    line=dict(color="rgba(130,20,10,1)", width=1),
                ),
                name="매도",
                customdata=[[t["price"], t["quantity"], t["label"]] for t in sells],
                hovertemplate=(
                    f"<b>매도</b><br>"
                    f"단가: %{{customdata[0]:{price_fmt_hover}}}{price_unit}<br>"
                    "수량: %{customdata[1]}주<br>"
                    "사유: %{customdata[2]}<extra></extra>"
                ),
                showlegend=True,
            ), row=3, col=1)

    # ════════════════════════════════
    # 타이틀 (종목명 + 코드 강조)
    # ════════════════════════════════
    # 당일 가격 및 전일대비 등락률
    cur_price  = stock_df["Close"].iloc[-1]
    prev_price = stock_df["Close"].iloc[-2] if len(stock_df) >= 2 else cur_price
    chg_pct    = (cur_price / prev_price - 1) * 100 if prev_price else 0
    chg_color  = "#FF3333" if chg_pct >= 0 else "#3399FF"
    chg_sign   = "+" if chg_pct >= 0 else ""
    if is_kr:
        price_str = f"{cur_price:,.0f}원"
    else:
        price_str = f"${cur_price:,.2f}"
    price_tag = (
        f"  <span style='font-size:15px;color:{chg_color}'>"
        f"{price_str} ({chg_sign}{chg_pct:.2f}%)</span>"
    )

    if stock_name != ticker:
        title_stock = f"<b style='font-size:18px;color:{C['text']}'>{stock_name}</b>  <span style='color:{C['subtext']};font-size:14px'>({ticker})</span>{price_tag}"
    else:
        title_stock = f"<b style='font-size:18px;color:{C['text']}'>{ticker}</b>{price_tag}"

    # ── 초기 x축 범위: 마지막 period 거래일 ─────
    range_start    = stock_df.index[-min(period, len(stock_df))]
    range_end_disp = stock_df.index[-1] + pd.Timedelta(days=3)

    # ── 기간별 y축 범위 사전 계산 (updatemenus method="relayout" 용) ──
    last_date = stock_df.index[-1]
    x_end_str = range_end_disp.strftime("%Y-%m-%d")

    def _period_relayout(cutoff):
        df_p = stock_df[stock_df.index >= cutoff] if cutoff is not None else stock_df
        rs_p = rs_line[rs_line.index >= cutoff] if cutoff is not None else rs_line
        if df_p.empty:
            df_p, rs_p = stock_df, rs_line
        p_lo, p_hi = float(df_p["Low"].min()), float(df_p["High"].max())
        p_pad = (p_hi - p_lo) * 0.05
        has_vol = "Volume" in df_p.columns and df_p["Volume"].notna().any()
        v_max = float(df_p["Volume"].max()) if has_vol else 1.0
        rs_spread = max(float(rs_p.max() - rs_p.min()), 0.5)
        rs_pad_v  = rs_spread * 0.35
        x_start = df_p.index[0].strftime("%Y-%m-%d")
        return {
            "xaxis.range[0]":  x_start,
            "xaxis.range[1]":  x_end_str,
            "yaxis3.range[0]": p_lo - p_pad,
            "yaxis3.range[1]": p_hi + p_pad,
            "yaxis4.range[0]": 0,
            "yaxis4.range[1]": v_max * 1.2,
            "yaxis5.range[0]": float(rs_p.min()) - rs_pad_v,
            "yaxis5.range[1]": float(rs_p.max()) + rs_pad_v,
        }

    _period_defs = [
        ("1개월", last_date - pd.DateOffset(months=1)),
        ("3개월", last_date - pd.DateOffset(months=3)),
        ("6개월", last_date - pd.DateOffset(months=6)),
        ("1년",   last_date - pd.DateOffset(years=1)),
        ("전체",  None),
    ]

    # 초기 활성 버튼 인덱스 결정
    _active_idx = 4  # 기본: 전체
    for _i, (_, _co) in enumerate(_period_defs):
        if _co is not None and range_start >= _co:
            _active_idx = _i
            break

    _menu_buttons = [
        dict(method="relayout", label=lbl, args=[_period_relayout(co)])
        for lbl, co in _period_defs
    ]

    fig.update_layout(
        title=dict(
            text=(
                f"{title_stock}"
                f"  <span style='color:{C['subtext']};font-size:13px'>"
                f"vs {benchmark_name}  |  기준 {period}일  |  {date_str}</span><br>"
                f"<span style='font-size:12px; color:{rs_color}'>"
                f"RS Score: <b>{rs_score:+.2f}</b>  {rs_label}"
                f"</span>"
                f"<span style='font-size:12px; color:{C['subtext']}'>"
                f"  &nbsp;|&nbsp; 종목 {stock_ret:+.2f}%"
                f"  &nbsp;|&nbsp; {benchmark_name} {index_ret:+.2f}%"
                f"</span>"
            ),
            x=0.01, xanchor="left",
        ),
        plot_bgcolor=C["bg"],
        paper_bgcolor=C["paper"],
        font=dict(color=C["text"], family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
        height=860,
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
        xaxis4_rangeslider_visible=False,
        updatemenus=[dict(
            type="buttons",
            direction="right",
            showactive=True,
            active=_active_idx,
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

    # ── y축 설정 ─────────────────────────────
    axis_base = dict(
        showgrid=True, gridcolor=C["grid"], gridwidth=1,
        linecolor="#CCCCCC", tickfont=dict(size=11, color=C["text"]),
        title_font=dict(size=11, color="#222222"), zeroline=False,
    )
    fig.update_yaxes(
        **axis_base,
        title_text=f"주가 ({'원' if is_kr else 'USD'})",
        tickformat=price_fmt, tickprefix=price_pfx,
        mirror="allticks",
        showspikes=True,
        spikemode="across+toaxis",
        spikesnap="cursor",
        spikecolor="#AAAAAA",
        spikethickness=1,
        spikedash="dot",
        row=3, col=1,
    )
    fig.update_yaxes(
        **axis_base,
        title_text="거래량", tickformat=".3s",
        autorange=True,
        row=4, col=1,
    )
    fig.update_yaxes(
        **axis_base,
        title_text="RS", tickformat=".2f", range=rs_yrange,
        row=5, col=1,
    )

    # ── x축 설정 ─────────────────────────────
    # 주말 + 공휴일(데이터 없는 평일) 모두 제거 (타임존 무관하게 date 비교)
    trading_dates = set(idx.date() for idx in stock_df.index)
    all_weekdays  = pd.bdate_range(stock_df.index[0].date(), stock_df.index[-1].date())
    holiday_strs  = [d.strftime("%Y-%m-%d") for d in all_weekdays if d.date() not in trading_dates]
    rangebreaks   = [dict(bounds=["sat", "mon"])]
    if holiday_strs:
        rangebreaks.append(dict(values=holiday_strs))

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

    # row1~2(신호 바): 날짜 레이블 숨김
    fig.update_xaxes(**xaxis_common, showticklabels=False, row=1, col=1)
    fig.update_xaxes(**xaxis_common, showticklabels=False, row=2, col=1)

    # row3~4: 날짜 레이블 숨김
    fig.update_xaxes(**xaxis_common, showticklabels=False, row=3, col=1)
    fig.update_xaxes(**xaxis_common, showticklabels=False, row=4, col=1)

    # row5(하단): 날짜 표시 + rangeslider
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
        row=5, col=1,
    )

    return fig


# ─────────────────────────────────────────────
# 5b. ECharts 차트 (신버전)
# ─────────────────────────────────────────────

def build_chart_echarts(
    ticker: str,
    stock_name: str,
    benchmark_name: str,
    market: str,
    period: int,
    stock_df: pd.DataFrame,
    index_df: pd.DataFrame,
    mas: dict,
    rs_line: pd.Series,
    rs_score: float,
    stock_ret: float,
    index_ret: float,
    trades: list = None,
    stop_loss_price: float = None,
    take_profit_price: float = None,
):
    """
    Apache ECharts 기반 5패널 차트 (단일 차트 인스턴스 → x축 완벽 정렬).
    Row 0: 진입신호 (3%)  |  Row 1: 분배신호 (3%)
    Row 2: 주가+MA (52%)  |  Row 3: 거래량 (12%)  |  Row 4: RS Line (22%)
    + dataZoom 하단 슬라이더 (8%)
    """
    from streamlit_echarts import st_echarts
    import streamlit as st

    is_kr = (market == "KR")

    # ── 중복 제거 + 정렬 ──
    stock_df = stock_df[~stock_df.index.duplicated(keep='last')].sort_index()
    index_df = index_df[~index_df.index.duplicated(keep='last')].sort_index()

    # ── 신호 계산 ──
    signal      = calc_entry_signal(stock_df)
    sell_signal = calc_sell_signal(stock_df)

    dates = [d.strftime("%Y-%m-%d") for d in stock_df.index]
    N = len(dates)

    # ── 신호 색상 ──
    def _sig_color(v):
        if v < 0.33:   return "rgba(39,174,96,0.6)"
        elif v < 0.66: return "rgba(243,156,18,0.6)"
        else:          return "rgba(217,43,43,0.6)"

    entry_colors = [_sig_color(float(signal.iloc[i])) for i in range(N)]
    expand_colors = [_sig_color(float(sell_signal.iloc[i])) for i in range(N)]

    # ── OHLC 데이터 (ECharts candlestick: [open, close, low, high]) ──
    ohlc = [[float(stock_df["Open"].iloc[i]), float(stock_df["Close"].iloc[i]),
             float(stock_df["Low"].iloc[i]),  float(stock_df["High"].iloc[i])]
            for i in range(N)]

    # ── OHLC별 전일종가대비 등락률 (tooltip용 문자열) ──
    prev_closes = stock_df["Close"].shift(1).values
    ohlc_tooltip = {}
    for label, col in [("시가", "Open"), ("종가", "Close"), ("저가", "Low"), ("고가", "High")]:
        formatted = []
        for i in range(N):
            price = float(stock_df[col].iloc[i])
            if i > 0 and not (prev_closes[i] != prev_closes[i]):  # not NaN
                pc = float(prev_closes[i])
                pct = (price - pc) / pc * 100
                sign = "+" if pct >= 0 else ""
                if is_kr:
                    formatted.append(f"{price:,.0f} ({sign}{pct:.2f}%)")
                else:
                    formatted.append(f"{price:,.2f} ({sign}{pct:.2f}%)")
            else:
                formatted.append(f"{price:,.0f}" if is_kr else f"{price:,.2f}")
        ohlc_tooltip[label] = formatted

    # ── 벤치마크 정규화 ──
    idx_aligned = index_df["Close"].reindex(stock_df.index).ffill().bfill()
    idx_norm = idx_aligned / idx_aligned.iloc[0] * stock_df["Close"].iloc[0]
    idx_data = [round(float(v), 2) for v in idx_norm.values]

    # ── MA 데이터 ──
    ma_configs = [
        ("MA5",    "ma5",    "#FF6D00", 1),
        ("MA20",   "ma20",   "#8A2BE2", 1),
        ("MA60",   "ma60",   "#008000", 1.5),
        ("WMA100", "wma100", "#FFFFFF", 2),
        ("MA120",  "ma120",  "#008B8B", 1.5),
        ("MA200",  "ma200",  "#C0392B", 1.5),
    ]
    ma_series_list = []
    for label, key, color, width in ma_configs:
        vals = mas[key].reindex(stock_df.index)
        data = [round(float(v), 2) if not np.isnan(v) else None for v in vals]
        ma_series_list.append({
            "type": "line", "name": label, "data": data,
            "xAxisIndex": 2, "yAxisIndex": 2,
            "lineStyle": {"color": color, "width": width},
            "itemStyle": {"color": color},
            "symbol": "none", "smooth": False,
            "connectNulls": False,
        })

    # ── 거래량 ──
    vol_data = []
    for i in range(N):
        c, o = float(stock_df["Close"].iloc[i]), float(stock_df["Open"].iloc[i])
        color = "#D92B2B" if c >= o else "#1A5ECC"
        vol_data.append({"value": float(stock_df["Volume"].iloc[i]),
                         "itemStyle": {"color": color}})
    vol_ma5 = stock_df["Volume"].rolling(5, min_periods=1).mean()
    vol_ma5_data = [round(float(v), 0) if not np.isnan(v) else None for v in vol_ma5]
    vol_ma60 = stock_df["Volume"].rolling(60, min_periods=1).mean()
    vol_ma_data = [round(float(v), 0) if not np.isnan(v) else None for v in vol_ma60]

    # ── RS Line ──
    rs_aligned = rs_line.reindex(stock_df.index).ffill().bfill()
    rs_data = [round(float(v), 2) for v in rs_aligned.values]

    # ── ATR(20) ──
    _high = stock_df["High"] if "High" in stock_df.columns else stock_df["Close"]
    _low = stock_df["Low"] if "Low" in stock_df.columns else stock_df["Close"]
    _prev_close = stock_df["Close"].shift(1)
    _tr = pd.concat([
        _high - _low,
        (_high - _prev_close).abs(),
        (_low - _prev_close).abs(),
    ], axis=1).max(axis=1)
    _atr20 = _tr.rolling(20, min_periods=1).mean()
    _atr_pct = _atr20 / stock_df["Close"] * 100
    atr_data = [round(float(v), 2) if not np.isnan(v) else None for v in _atr_pct.values]

    # ── 매매 마커 ──
    buy_scatter, sell_scatter = [], []
    avg_buy_price = None
    _sl_from_param = stop_loss_price  # 파라미터로 전달된 손절가 보존
    _tp_from_param = take_profit_price  # 파라미터로 전달된 익절가 보존
    stop_loss_price = None
    take_profit_price = None
    if trades:
        buys  = [t for t in trades if t["type"] == "buy"]
        sells = [t for t in trades if t["type"] == "sell"]
        trading_dates = stock_df.index.normalize().unique()

        def _snap(d):
            dn = pd.Timestamp(d).normalize()
            past = trading_dates[trading_dates <= dn]
            return past[-1].strftime("%Y-%m-%d") if len(past) else dn.strftime("%Y-%m-%d")

        price_range = stock_df["High"].max() - stock_df["Low"].min()
        offset = float(price_range * 0.03)

        for t in buys:
            td = _snap(t["date"])
            if td in dates:
                idx = dates.index(td)
                y_val = float(stock_df["Low"].iloc[idx]) - offset * 2
                price_s = f"{t['price']:,.0f}원" if is_kr else f"${t['price']:,.2f}"
                reason = t.get("label") or ""
                buy_scatter.append({
                    "value": [td, y_val],
                    "tip": f"매수 {price_s}" + (f"\n{reason}" if reason else ""),
                })
        for t in sells:
            td = _snap(t["date"])
            if td in dates:
                idx = dates.index(td)
                y_val = float(stock_df["High"].iloc[idx]) + offset * 2
                price_s = f"{t['price']:,.0f}원" if is_kr else f"${t['price']:,.2f}"
                reason = t.get("reason") or ""
                sell_scatter.append({
                    "value": [td, y_val],
                    "tip": f"매도 {price_s}" + (f"\n{reason}" if reason else ""),
                })

        if buys:
            # 현재 오픈 포지션의 매수만으로 평균매수가 계산
            open_buys = [t for t in buys if t.get("position_status") == "open"]
            open_sells = [t for t in sells if t.get("position_status") == "open"]
            if not open_buys:
                open_buys = buys  # position_status 없는 경우 폴백
                open_sells = sells
            total_cost = sum(t["price"] * t["quantity"] for t in open_buys)
            total_qty  = sum(t["quantity"] for t in open_buys)
            sold_qty   = sum(t["quantity"] for t in open_sells)
            if (total_qty - sold_qty) > 0 and total_qty > 0:
                avg_buy_price = total_cost / total_qty
                # 손절가: 파라미터 우선, 없으면 마지막 매수의 stop_loss
                if _sl_from_param and float(_sl_from_param) > 0:
                    stop_loss_price = float(_sl_from_param)
                else:
                    last_sl = buys[-1].get("stop_loss", 0)
                    if last_sl and last_sl > 0:
                        stop_loss_price = last_sl
                # 1차 익절가: 파라미터 우선, 없으면 마지막 매수의 take_profit
                if _tp_from_param and float(_tp_from_param) > 0:
                    take_profit_price = float(_tp_from_param)
                else:
                    last_tp = buys[-1].get("take_profit", 0)
                    if last_tp and last_tp > 0:
                        take_profit_price = last_tp

    # ── 초기 표시 범위 (period 기준) ──
    zoom_start = max(0, (1 - period / N) * 100) if N > 0 else 80

    # ════════════════════════════════════════════
    # ECharts 옵션 조립
    # ════════════════════════════════════════════

    # 그리드 레이아웃 (% 기반)
    LEFT, RIGHT = "8%", "8%"
    option = {
        "animation": False,
        "backgroundColor": "#1a1a2e",
        "title": [
            {"text": "진입신호", "left": "1%", "top": "10%",
             "textAlign": "left", "textVerticalAlign": "middle",
             "textStyle": {"fontSize": 11, "color": "#CCC", "fontWeight": "bold"}},
            {"text": "분배신호", "left": "1%", "top": "13%",
             "textAlign": "left", "textVerticalAlign": "middle",
             "textStyle": {"fontSize": 11, "color": "#CCC", "fontWeight": "bold"}},
            {"text": "주가", "left": "1%", "top": "32%",
             "textAlign": "left", "textVerticalAlign": "middle",
             "textStyle": {"fontSize": 11, "color": "#CCC", "fontWeight": "bold"}},
            {"text": "거래량", "left": "1%", "top": "55%",
             "textAlign": "left", "textVerticalAlign": "middle",
             "textStyle": {"fontSize": 11, "color": "#CCC", "fontWeight": "bold"}},
            {"text": "RS", "left": "1%", "top": "67%",
             "textAlign": "left", "textVerticalAlign": "middle",
             "textStyle": {"fontSize": 11, "color": "#CCC", "fontWeight": "bold"}},
            {"text": "ATR", "left": "1%", "top": "79%",
             "textAlign": "left", "textVerticalAlign": "middle",
             "textStyle": {"fontSize": 11, "color": "#CCC", "fontWeight": "bold"}},
        ],
        "grid": [
            # tooltip 순서 제어를 위해 gridIndex 재배치
            {"left": LEFT, "right": RIGHT, "top": "12%", "height": "3%"},   # 0: 분배신호
            {"left": LEFT, "right": RIGHT, "top": "9%",  "height": "3%"},   # 1: 진입신호
            {"left": LEFT, "right": RIGHT, "top": "16%", "height": "33%"},  # 2: 주가
            {"left": LEFT, "right": RIGHT, "top": "62%", "height": "11%"},  # 3: RS
            {"left": LEFT, "right": RIGHT, "top": "50%", "height": "11%"},  # 4: 거래량
            {"left": LEFT, "right": RIGHT, "top": "74%", "height": "11%"},  # 5: ATR
        ],
        "xAxis": [
            # 0: 분배신호 — 라벨 숨김
            {"type": "category", "data": dates, "gridIndex": 0,
             "axisLabel": {"show": False}, "axisTick": {"show": False},
             "axisLine": {"show": False}, "splitLine": {"show": False},
             "axisPointer": {"label": {"show": False}}},
            # 1: 진입신호 — 라벨 숨김
            {"type": "category", "data": dates, "gridIndex": 1,
             "axisLabel": {"show": False}, "axisTick": {"show": False},
             "axisLine": {"show": False}, "splitLine": {"show": False},
             "axisPointer": {"label": {"show": False}}},
            # 2: 주가 패널 하단 날짜
            {"type": "category", "data": dates, "gridIndex": 2,
             "axisLabel": {"show": True, "fontSize": 10, "color": "#AAA",
                           "formatter": "{value}"},
             "axisTick": {"show": True},
             "axisLine": {"lineStyle": {"color": "rgba(255,255,255,0.2)"}},
             "splitLine": {"show": False},
             "axisPointer": {"label": {"show": False}}},
            # 3: RS — 라벨 숨김
            {"type": "category", "data": dates, "gridIndex": 3,
             "axisLabel": {"show": False}, "axisTick": {"show": False},
             "axisLine": {"show": False}, "splitLine": {"show": False},
             "axisPointer": {"label": {"show": False}}},

            # 4: 거래량 — 라벨 숨김
            {"type": "category", "data": dates, "gridIndex": 4,
             "axisLabel": {"show": False}, "axisTick": {"show": False},
             "axisLine": {"show": False}, "splitLine": {"show": False},
             "axisPointer": {"label": {"show": False}}},
            # 5: ATR 패널 하단 날짜 (최하단)
            {"type": "category", "data": dates, "gridIndex": 5,
             "axisLabel": {"show": True, "fontSize": 10, "color": "#AAA",
                           "formatter": "{value}"},
             "axisTick": {"show": True},
             "axisLine": {"lineStyle": {"color": "rgba(255,255,255,0.2)"}},
             "splitLine": {"show": False}},
        ],
        "yAxis": [
            # 0: 분배신호 (숨김)
            {"type": "value", "gridIndex": 0, "show": False, "min": 0, "max": 1,
             "axisPointer": {"show": False}},
            # 1: 진입신호 (숨김)
            {"type": "value", "gridIndex": 1, "show": False, "min": 0, "max": 1,
             "axisPointer": {"show": False}},
            # 2: 주가
            {"type": "value", "gridIndex": 2, "scale": True, "splitNumber": 6,
             "axisLabel": {"fontSize": 10, "color": "#AAA"},
             "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.08)", "type": "dotted"}},
             "axisLine": {"show": False},
             "position": "right",
             "axisPointer": {"show": True, "snap": False,
                             "label": {"show": True, "precision": 0 if is_kr else 2}},
             "name": f"주가 ({'원' if is_kr else 'USD'})", "nameLocation": "end",
             "nameTextStyle": {"fontSize": 10, "color": "#888"}},
            # 3: RS
            {"type": "value", "gridIndex": 3, "scale": True, "splitNumber": 3,
             "axisLabel": {"fontSize": 10, "color": "#AAA"},
             "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.08)", "type": "dotted"}},
             "axisLine": {"show": False},
             "position": "right",
             "axisPointer": {"show": True, "snap": False,
                             "label": {"show": True, "precision": 2}},
             "name": "RS", "nameLocation": "end",
             "nameTextStyle": {"fontSize": 10, "color": "#888"}},
            # 4: 거래량
            {"type": "value", "gridIndex": 4, "scale": True, "splitNumber": 2,
             "axisLabel": {"fontSize": 10, "color": "#AAA"},
             "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.08)", "type": "dotted"}},
             "axisLine": {"show": False},
             "position": "right",
             "axisPointer": {"show": True, "snap": False,
                             "label": {"show": True, "precision": 0}},
             "name": "거래량", "nameLocation": "end",
             "nameTextStyle": {"fontSize": 10, "color": "#888"}},
            # 5: 등락률 (숨김, 주가 grid에 겹침 — 호버 전용)
            {"type": "value", "gridIndex": 2, "show": False,
             "axisPointer": {"show": False}},
            # 6: ATR(%)
            {"type": "value", "gridIndex": 5, "scale": True, "splitNumber": 2,
             "axisLabel": {"fontSize": 10, "color": "#AAA", "formatter": "{value}%"},
             "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.08)", "type": "dotted"}},
             "axisLine": {"show": False},
             "position": "right",
             "axisPointer": {"show": True, "snap": False,
                             "label": {"show": True, "precision": 0}},
             "name": "ATR(%)", "nameLocation": "end",
             "nameTextStyle": {"fontSize": 10, "color": "#888"}},
        ],
        "dataZoom": [
            {"type": "inside", "xAxisIndex": list(range(6)),
             "start": zoom_start, "end": 100},
        ],
        "toolbox": {"show": False},
        "legend": [
            {
                "show": True,
                "data": ["MA5", "MA20", "MA60", "WMA100", "MA120", "MA200"],
                "left": 20,
                "top": 50,
                "textStyle": {"color": "#BBB", "fontSize": 10},
                "itemWidth": 18,
                "itemHeight": 2,
                "itemGap": 12,
                "inactiveColor": "#555",
                "selector": False,
            },
        ],
        "axisPointer": {
            "link": [{"xAxisIndex": "all"}],
            "lineStyle": {"color": "rgba(255,255,255,0.4)", "width": 1},
        },
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "cross"},
            "backgroundColor": "rgba(30,30,30,0.85)",
            "borderColor": "rgba(120,120,120,0.5)",
            "textStyle": {"color": "#FFF", "fontSize": 11},
            "confine": True,
            "order": "seriesDesc",
        },
        "series": [],
    }

    # ── Series 추가 ──
    # tooltip 표시 순서: 주가 → 거래량 → RS → 진입신호 → 분배신호

    # 벤치마크 비교선
    option["series"].append({
        "type": "line", "name": benchmark_name, "xAxisIndex": 2, "yAxisIndex": 2,
        "data": idx_data,
        "lineStyle": {"color": "#2ECC71", "width": 1, "type": "dashed"},
        "itemStyle": {"color": "#2ECC71"},
        "symbol": "none", "smooth": False,
        "tooltip": {"show": False},
    })

    # 캔들스틱 (tooltip 숨김 — OHLC는 별도 시리즈로 등락률 포함 표시)
    option["series"].append({
        "type": "candlestick", "xAxisIndex": 2, "yAxisIndex": 2,
        "data": ohlc,
        "itemStyle": {
            "color": "#D92B2B", "color0": "#1A5ECC",
            "borderColor": "#D92B2B", "borderColor0": "#1A5ECC",
        },
        "tooltip": {"show": False},
    })

    # OHLC + 전일종가대비 등락률 (호버 표시용, 투명 라인)
    _ohlc_colors = {"종가": "#D92B2B", "시가": "#FF9800", "저가": "#1A5ECC", "고가": "#E91E63"}
    for label in ["종가", "시가", "저가", "고가"]:
        option["series"].append({
            "type": "line", "name": label, "xAxisIndex": 2, "yAxisIndex": 5,
            "data": ohlc_tooltip[label],
            "symbol": "none", "lineStyle": {"width": 0, "color": "transparent"},
            "itemStyle": {"color": _ohlc_colors[label]},
        })

    # 이동평균선
    option["series"].extend(ma_series_list)

    # 매수 마커
    if buy_scatter:
        option["series"].append({
            "type": "scatter", "name": "매수", "xAxisIndex": 2, "yAxisIndex": 2,
            "data": [
                {"value": s["value"],
                 "tooltip": {"formatter": s["tip"].replace("\n", "<br>")}}
                for s in buy_scatter
            ],
            "symbol": "triangle", "symbolSize": 14, "symbolRotate": 0,
            "itemStyle": {"color": "rgba(39,174,96,0.9)"},
            "label": {"show": False},
            "tooltip": {"trigger": "item"},
        })

    # 매도 마커
    if sell_scatter:
        option["series"].append({
            "type": "scatter", "name": "매도", "xAxisIndex": 2, "yAxisIndex": 2,
            "data": [
                {"value": s["value"],
                 "tooltip": {"formatter": s["tip"].replace("\n", "<br>")}}
                for s in sell_scatter
            ],
            "symbol": "triangle", "symbolSize": 14, "symbolRotate": 180,
            "itemStyle": {"color": "rgba(192,57,43,0.9)"},
            "label": {"show": False},
            "tooltip": {"trigger": "item"},
        })

    # 평균매수가 수평선
    if avg_buy_price is not None:
        option["series"].append({
            "type": "line", "name": "평균매수가", "xAxisIndex": 2, "yAxisIndex": 2,
            "data": [],
            "markLine": {
                "silent": True,
                "symbol": "none",
                "lineStyle": {"color": "rgba(39,174,96,0.75)", "width": 2, "type": "dashed"},
                "data": [{"yAxis": avg_buy_price, "label": {
                    "show": True, "position": "end", "fontSize": 10,
                    "color": "rgba(39,174,96,0.9)",
                    "formatter": f"매수평균가 {avg_buy_price:,.0f}원" if is_kr else f"Avg Buy ${avg_buy_price:,.2f}",
                }}],
            },
        })

    # 손절가 수평선
    if stop_loss_price is not None and float(stop_loss_price) > 0:
        _sl = float(stop_loss_price)
        option["series"].append({
            "type": "line", "name": "손절가", "xAxisIndex": 2, "yAxisIndex": 2,
            "data": [],
            "markLine": {
                "silent": True,
                "symbol": "none",
                "lineStyle": {"color": "rgba(192,57,43,0.75)", "width": 2, "type": "dashed"},
                "data": [{"yAxis": _sl, "label": {
                    "show": True, "position": "end", "fontSize": 10,
                    "color": "rgba(192,57,43,0.9)",
                    "formatter": f"손절가 {_sl:,.0f}원" if is_kr else f"Stop ${_sl:,.2f}",
                }}],
            },
        })

    # 1차 익절가 수평선 + 계획 RR비
    if take_profit_price is not None and float(take_profit_price) > 0:
        _tp = float(take_profit_price)
        # 계획 RR비: (익절가 - 평균매수가) / (평균매수가 - 손절가)
        rr_text = ""
        if avg_buy_price and stop_loss_price and float(stop_loss_price) > 0:
            risk = avg_buy_price - float(stop_loss_price)
            reward = _tp - avg_buy_price
            if risk > 0:
                rr = reward / risk
                rr_text = f"  (RR {rr:.1f})"
        if is_kr:
            label_text = f"1차익절 {_tp:,.0f}원{rr_text}"
        else:
            label_text = f"TP1 ${_tp:,.2f}{rr_text}"
        option["series"].append({
            "type": "line", "name": "1차익절가", "xAxisIndex": 2, "yAxisIndex": 2,
            "data": [],
            "markLine": {
                "silent": True,
                "symbol": "none",
                "lineStyle": {"color": "rgba(241,196,15,0.75)", "width": 2, "type": "dashed"},
                "data": [{"yAxis": _tp, "label": {
                    "show": True, "position": "end", "fontSize": 10,
                    "color": "rgba(241,196,15,0.9)",
                    "formatter": label_text,
                }}],
            },
        })

    # 거래량 바
    option["series"].append({
        "type": "bar", "xAxisIndex": 4, "yAxisIndex": 4,
        "data": vol_data, "barWidth": "60%",
    })

    # 거래량 MA5
    option["series"].append({
        "type": "line", "name": "Vol MA5", "xAxisIndex": 4, "yAxisIndex": 4,
        "data": vol_ma5_data,
        "lineStyle": {"color": "#29B6F6", "width": 1},
        "itemStyle": {"color": "#29B6F6"},
        "symbol": "none",
    })

    # 거래량 MA60
    option["series"].append({
        "type": "line", "name": "Vol MA60", "xAxisIndex": 4, "yAxisIndex": 4,
        "data": vol_ma_data,
        "lineStyle": {"color": "#F39C12", "width": 1},
        "itemStyle": {"color": "#F39C12"},
        "symbol": "none",
    })

    # RS Line
    option["series"].append({
        "type": "line", "xAxisIndex": 3, "yAxisIndex": 3,
        "data": rs_data,
        "lineStyle": {"color": "#D92B2B", "width": 2},
        "symbol": "none",
        "areaStyle": {"color": "rgba(217,43,43,0.15)"},
    })

    # RS 기준선 (100)
    option["series"].append({
        "type": "line", "xAxisIndex": 3, "yAxisIndex": 3,
        "data": [],
        "markLine": {
            "silent": True, "symbol": "none",
            "lineStyle": {"color": "#999", "width": 1, "type": "dashed"},
            "data": [{"yAxis": 100}],
            "label": {"show": False},
        },
    })

    # ATR(20) Line
    option["series"].append({
        "type": "line", "name": "ATR(%)", "xAxisIndex": 5, "yAxisIndex": 6,
        "data": atr_data,
        "lineStyle": {"color": "#FF9800", "width": 1.5},
        "itemStyle": {"color": "#FF9800"},
        "symbol": "none",
        "areaStyle": {"color": "rgba(255,152,0,0.1)"},
    })

    # 진입신호 (단칸 색상 블록, 호버로 수치 확인)
    entry_vals = [round(float(signal.iloc[i]), 2) for i in range(N)]
    option["series"].append({
        "type": "bar", "xAxisIndex": 1, "yAxisIndex": 1,
        "data": [{"value": 1, "itemStyle": {"color": entry_colors[i]}}
                 for i in range(N)],
        "barWidth": "100%", "barGap": "0%", "barCategoryGap": "0%",
        "animation": False,
    })
    # 진입신호 수치 (투명, 호버 전용)
    option["series"].append({
        "type": "bar", "xAxisIndex": 1, "yAxisIndex": 1,
        "data": entry_vals,
        "barWidth": "0%", "itemStyle": {"color": "transparent"},
        "animation": False,
    })

    # 분배신호 (단칸 색상 블록, 호버로 수치 확인)
    expand_vals = [round(float(sell_signal.iloc[i]), 2) for i in range(N)]
    option["series"].append({
        "type": "bar", "xAxisIndex": 0, "yAxisIndex": 0,
        "data": [{"value": 1, "itemStyle": {"color": expand_colors[i]}}
                 for i in range(N)],
        "barWidth": "100%", "barGap": "0%", "barCategoryGap": "0%",
        "animation": False,
    })
    # 분배신호 수치 (투명, 호버 전용)
    option["series"].append({
        "type": "bar", "xAxisIndex": 0, "yAxisIndex": 0,
        "data": expand_vals,
        "barWidth": "0%", "itemStyle": {"color": "transparent"},
        "animation": False,
    })

    # ════════════════════════════════════════════
    # 차트 내부 헤더 (graphic rich text)
    # ════════════════════════════════════════════
    cur_price  = stock_df["Close"].iloc[-1]
    prev_price = stock_df["Close"].iloc[-2] if len(stock_df) >= 2 else cur_price
    chg_pct    = (cur_price / prev_price - 1) * 100 if prev_price else 0
    chg_sign   = "+" if chg_pct >= 0 else ""
    chg_color  = "#D92B2B" if chg_pct >= 0 else "#1A5ECC"
    price_str  = f"{cur_price:,.0f}원" if is_kr else f"${cur_price:,.2f}"
    last_date  = stock_df.index[-1].strftime("%Y.%m.%d")
    rs_arrow   = "강세 ▲" if rs_score >= 0 else "약세 ▼"

    # 1행: 종목명 (코드)  종가 (등락률)  vs 벤치마크 | 기준 N일 | 날짜
    line1 = (
        f"{{name|{stock_name}}}  {{code|({ticker})}}  "
        f"{{price|{price_str} ({chg_sign}{chg_pct:.2f}%)}}  "
        f"{{info|vs {benchmark_name}  |  기준 {period}일  |  {last_date}}}"
    )
    # 2행: RS Score  | 종목 수익률 | 벤치마크 수익률
    line2 = (
        f"{{rs|RS Score: {rs_score:+.2f} {rs_arrow}}}  "
        f"{{info||  종목 {stock_ret:+.2f}%  |  {benchmark_name} {index_ret:+.2f}%}}"
    )
    # legend에 벤치마크 추가
    option["legend"][0]["data"].append(benchmark_name)

    option["graphic"] = [
        {
            "type": "text",
            "left": 20,
            "top": 10,
            "style": {
                "text": line1,
                "rich": {
                    "name":  {"fontSize": 16, "fontWeight": "bold", "fill": "#EEE"},
                    "code":  {"fontSize": 13, "fill": "#999"},
                    "price": {"fontSize": 14, "fontWeight": "bold", "fill": chg_color},
                    "info":  {"fontSize": 12, "fill": "#999"},
                },
            },
        },
        {
            "type": "text",
            "left": 20,
            "top": 32,
            "style": {
                "text": line2,
                "rich": {
                    "rs":   {"fontSize": 12, "fontWeight": "bold",
                             "fill": "#D92B2B" if rs_score >= 0 else "#1A5ECC"},
                    "info": {"fontSize": 12, "fill": "#999"},
                },
            },
        },
    ]

    # ════════════════════════════════════════════
    # 렌더링
    # ════════════════════════════════════════════
    st_echarts(options=option, height="1100px", key=f"ec2_{ticker}_{period}")


# ─────────────────────────────────────────────
# 6. 메인
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="IBD 스타일 상대강도 분석기 (한국/미국 주식)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python relative_strength.py 005930            삼성전자 (기본 20일)
  python relative_strength.py AAPL -p 60        애플 60일
  python relative_strength.py 035720 -b KQ11    카카오 vs KOSDAQ
  python relative_strength.py TSLA -b QQQ       테슬라 vs QQQ
  python relative_strength.py 005930 --save samsung.html
        """,
    )
    parser.add_argument("ticker", help="종목 코드 (한국: 6자리 숫자 / 미국: 영문 티커)")
    parser.add_argument("--period", "-p", type=int, default=20, help="분석 기간(거래일), 기본값: 20")
    parser.add_argument("--benchmark", "-b", default=None, help="벤치마크 코드")
    parser.add_argument("--save", "-s", default=None, help="HTML 파일로 저장")

    args    = parser.parse_args()
    ticker  = args.ticker if args.ticker.isdigit() else args.ticker.upper()
    period  = args.period
    market  = detect_market(ticker)

    if args.benchmark:
        benchmark_code = args.benchmark.upper() if not args.benchmark.isdigit() else args.benchmark
        benchmark_name = benchmark_code
    else:
        benchmark_code, benchmark_name = get_benchmark(ticker, market)

    print(f"\n{'─'*52}")
    print(f"  종목       : {ticker}  ({'한국' if market == 'KR' else '미국'} 주식)")
    print(f"  벤치마크   : {benchmark_name}  ({benchmark_code})")
    print(f"  분석 기간  : {period}일")
    print(f"{'─'*52}")

    try:
        stock_df, index_df = fetch_data(ticker, benchmark_code, period)
    except Exception as e:
        print(f"\n[오류] 데이터 수집 실패: {e}")
        sys.exit(1)

    # 종목명 조회
    stock_name = get_stock_name(ticker, market)
    print(f"  종목명     : {stock_name}")

    # 정렬 → MA 계산 (전체 데이터)
    stock_full, index_full = align_data(stock_df, index_df)
    mas_full               = calculate_mas(stock_full["Close"])

    # RS Score는 trimmed 기간 기준 계산
    s_trim, i_trim, _ = trim_to_period(stock_full, index_full, mas_full, period)

    print(f"  데이터 기간: {stock_full.index[0].date()} ~ {stock_full.index[-1].date()}")
    print(f"  표시 기간  : 최근 {period}일 (스크롤로 전체 조회 가능)\n")

    if len(s_trim) < 4:
        print("[오류] 데이터가 너무 적습니다. 기간을 늘려주세요.")
        sys.exit(1)

    # RS 지표: trimmed 기간 기준
    rs_line_trim, rs_score, stock_ret, index_ret = calculate_ibd_rs(s_trim, i_trim)
    # RS Line 표시: 전체 데이터 기준
    rs_line_full, _, _, _ = calculate_ibd_rs(stock_full, index_full)

    strength = "강세 ▲" if rs_score >= 0 else "약세 ▼"
    print(f"  ┌─ 분석 결과 ({period}일 기준) ───────────┐")
    print(f"  │  RS Score   : {rs_score:+.2f}  ({strength})")
    print(f"  │  RS Line    : {rs_line_trim.iloc[-1]:.2f}  (기준 100)")
    print(f"  │  종목 수익률: {stock_ret:+.2f}%")
    print(f"  │  지수 수익률: {index_ret:+.2f}%")
    print(f"  └─────────────────────────────────────┘\n")

    fig = build_chart(
        ticker, stock_name, benchmark_name, market, period,
        stock_full, index_full, mas_full,       # 전체 데이터로 차트 그리기
        rs_line_full, rs_score, stock_ret, index_ret,
    )

    if args.save:
        filename = args.save if args.save.endswith(".html") else args.save + ".html"
        fig.write_html(filename)
        print(f"  차트 저장 완료: {filename}")
    else:
        fig.show()


if __name__ == "__main__":
    main()
