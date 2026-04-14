#!/usr/bin/env python3
"""
SEPA Scanner - 메인 앱
Streamlit 기반 웹 UI
"""

import warnings
warnings.filterwarnings("ignore")

import json
import streamlit as st
import streamlit.components.v1 as _stc
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

from relative_strength import (
    detect_market,
    get_benchmark,
    get_stock_name,
    fetch_data,
    align_data,
    calculate_mas,
    trim_to_period,
    calculate_ibd_rs,
    build_chart,
    build_chart_echarts,
    calc_entry_signal,
)
from market_ranking import calc_market_ranking, get_cache_info, _cache_path, refresh_52w_high, apply_vcp_filter, apply_stage2_filter, get_filter_cache_info, scan_vcp_patterns, get_vcp_pattern_cache_info, scan_short_candidates, get_short_cache_info, INVERSE_ETF_MAP
from backtest import run_intraday_reversal_backtest, get_backtest_cache_info, run_signal_backtest, get_signal_cache_info
from portfolio import add_buy, add_sell, get_open_positions, get_trade_log, calculate_performance, update_stop_loss, get_stop_loss_history, get_realized_pnl, get_position_pnl, get_total_capital, set_initial_capital, add_capital_flow, get_capital_flows, delete_capital_flow, delete_trade, update_trade, get_equity_curve, get_monthly_performance, get_trades_by_ticker, set_portfolio_file, update_take_profit, get_monthly_review
from watchlist import (load_watchlists, save_watchlists, add_group, delete_group,
                       add_ticker, remove_ticker, calc_group_rs,
                       calc_group_index, build_group_chart,
                       load_watchlist_stocks, add_watchlist_stock,
                       remove_watchlist_stock, update_watchlist_stock,
                       load_group_rs_cache, save_group_rs_cache)
import FinanceDataReader as fdr
import altair as alt

@st.cache_data(ttl=86400)
def load_krx_listing():
    """KRX 전체 종목 + ETF 목록 (하루 캐시)"""
    try:
        df = fdr.StockListing("KRX")[["Code", "Name", "Market"]].dropna()
        df = df[df["Code"].str.len() == 6].reset_index(drop=True)
        try:
            etf = fdr.StockListing("ETF/KR")[["Symbol", "Name"]].dropna()
            etf.columns = ["Code", "Name"]
            etf["Market"] = "ETF"
            df = pd.concat([df, etf], ignore_index=True).drop_duplicates(subset="Code")
        except Exception:
            pass
        return df
    except Exception:
        return pd.DataFrame(columns=["Code", "Name", "Market"])


@st.cache_data(ttl=86400)
def load_us_listing():
    """미국(NASDAQ+NYSE+ETF) 전체 종목 목록 (하루 캐시)"""
    try:
        nasdaq = fdr.StockListing("NASDAQ")[["Symbol", "Name"]].dropna()
        nyse = fdr.StockListing("NYSE")[["Symbol", "Name"]].dropna()
        try:
            etf = fdr.StockListing("ETF/US")[["Symbol", "Name"]].dropna()
        except Exception:
            etf = pd.DataFrame(columns=["Symbol", "Name"])
        df = pd.concat([nasdaq, nyse, etf], ignore_index=True).drop_duplicates(subset="Symbol")
        df.columns = ["Code", "Name"]
        return df
    except Exception:
        return pd.DataFrame(columns=["Code", "Name"])


@st.cache_data(ttl=86400)
def _build_ticker_options():
    """사이드바 종목 검색용 옵션 리스트 (한국+미국)"""
    options = [""]
    krx = load_krx_listing()
    for _, row in krx.iterrows():
        options.append(f"{row['Name']}  ({row['Code']})")
    us = load_us_listing()
    for _, row in us.iterrows():
        options.append(f"{row['Name']}  ({row['Code']})")
    return options

def _aggrid(df, key, height=400, click_nav=False, fit_columns=False, color_map=None, price_cols=None, pct_cols=None, col_widths=None, hide_cols=None, price_decimals=0):
    """
    공통 AgGrid 래퍼.
    color_map      : {"컬럼명": "red_positive"} - red_positive면 양수빨강/음수파랑
    price_cols     : 천단위 콤마 포맷 적용할 컬럼 목록 (예: ["평균매수가", "현재가"])
    pct_cols       : 숫자 뒤에 % 붙이는 컬럼 목록 (예: ["수익률(%)"])
    col_widths     : {"컬럼명": px너비} 명시적 너비 지정
    price_decimals : 가격 컬럼 소수점 자리수 (기본 0=정수, 2=달러용)
    """
    price_cols = set(price_cols or [])
    pct_cols   = set(pct_cols or [])
    col_widths  = col_widths or {}
    hide_cols   = set(hide_cols or [])

    # 종목코드는 기본 숨김 (데이터는 유지, 화면에서만 숨김)
    hide_cols.add("종목코드")

    # 컬럼명으로 가격 컬럼 자동 감지
    _price_keywords = ("가", "금액", "매출", "이익", "손실", "단가", "원", "원)", "피벗")
    for col in df.columns:
        if any(col.endswith(k) for k in _price_keywords):
            price_cols.add(col)

    # 컬럼별 기본 너비 추정
    _narrow = {"순위", "No", "번호", "건수", "수량", "경과일"}
    _medium = {"종목코드", "날짜", "RS Score", "RS Line", "거래량구간", "진입근거", "매매타입"}
    _wide   = {"종목명"}

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, sortable=True, filter=True, min_width=60)
    gb.configure_grid_options(domLayout='normal')

    if click_nav:
        gb.configure_selection(selection_mode="single", use_checkbox=False)

    for col in df.columns:
        kwargs = {}

        # 너비
        if col in col_widths:
            kwargs["width"] = col_widths[col]
        elif col in _narrow:
            kwargs["width"] = 70
        elif col in _medium:
            kwargs["width"] = 110
        elif col in _wide:
            kwargs["width"] = 160
        else:
            # 한글 기준 글자당 ~22px, 최소 100px
            kwargs["width"] = max(100, len(col) * 22)

        # 숫자 포맷
        if col in price_cols:
            kwargs["type"] = ["numericColumn"]
            if price_decimals > 0:
                kwargs["valueFormatter"] = JsCode(
                    f"function(p){{if(p.value==null||isNaN(p.value))return '-';"
                    f"return p.value.toLocaleString('en-US',{{minimumFractionDigits:{price_decimals},maximumFractionDigits:{price_decimals}}});}}"
                )
            else:
                kwargs["valueFormatter"] = JsCode(
                    "function(p){if(p.value==null||isNaN(p.value))return '-';"
                    "return Math.round(p.value).toLocaleString('ko-KR');}"
                )
        elif col in pct_cols:
            kwargs["type"] = ["numericColumn"]
            kwargs["valueFormatter"] = JsCode(
                "function(p){if(p.value==null||isNaN(p.value))return '-';"
                "return p.value.toFixed(2)+'%';}"
            )
        elif df[col].dtype in ('float64', 'float32'):
            kwargs["type"] = ["numericColumn"]
            kwargs["valueFormatter"] = JsCode(
                "function(p){if(p.value==null||isNaN(p.value))return '-';"
                "return p.value.toFixed(2);}"
            )

        if col in hide_cols:
            kwargs["hide"] = True
        gb.configure_column(col, **kwargs)

    # 색상 매핑
    if color_map:
        for col, mode in color_map.items():
            if col not in df.columns:
                continue
            if mode == "red_positive":
                cell_style = JsCode(
                    "function(p){if(p.value>0)return{'color':'#c0392b','fontWeight':'bold'};"
                    "if(p.value<0)return{'color':'#1a5ecc','fontWeight':'bold'};return {};}"
                )
            else:
                cell_style = JsCode(
                    "function(p){if(p.value>0)return{'color':'#1a5ecc','fontWeight':'bold'};"
                    "if(p.value<0)return{'color':'#c0392b','fontWeight':'bold'};return {};}"
                )
            gb.configure_column(col, cellStyle=cell_style)

    go = gb.build()
    update_on = ["selectionChanged"] if click_nav else []

    result = AgGrid(
        df,
        gridOptions=go,
        height=height,
        update_on=update_on,
        fit_columns_on_grid_load=fit_columns,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        theme="streamlit",
        key=key,
    )
    return result


def resolve_korean_name(text: str) -> str:
    """한글 종목명이면 코드로 변환, 아니면 그대로 반환"""
    if text and not text.isdigit() and any(ord(c) > 127 for c in text):
        krx_df = load_krx_listing()
        match = krx_df[krx_df["Name"] == text]
        if not match.empty:
            return match.iloc[0]["Code"]
    return text

# ══════════════════════════════════════════════════════════
# 페이지 설정 + 인증
# ══════════════════════════════════════════════════════════
from auth import login_page, logout, get_user_id, is_local_mode, try_restore_session

_CLOUD_MODE = not is_local_mode()

# 클라우드 모드: 쿠키로 세션 복원 시도 (login_page 호출 전에 먼저)
if _CLOUD_MODE and not st.session_state.get("authenticated"):
    try_restore_session()

if _CLOUD_MODE and not st.session_state.get("authenticated"):
    # 복원 실패 → 로그인 화면
    if not login_page():
        st.stop()
else:
    # 로컬 모드 또는 인증됨: 메인 앱 레이아웃
    st.set_page_config(
        page_title="SEPA - Specific Entry Point Analysis",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

# ══════════════════════════════════════════════════════════
# 사이드바
# ══════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ 분석 설정")

    ticker_input = st.text_input(
        "종목 코드",
        placeholder="예: 005930  /  AAPL  /  IAU",
        help="한국 6자리 숫자, 미국 영문 티커, ETF 모두 가능",
        value=st.session_state.get("sidebar_ticker", ""),
    ).strip()

    if st.session_state.get("view") == "group_chart":
        period = st.slider(
            "분석 기간 (거래일)",
            min_value=20, max_value=250, value=st.session_state.get("wl_chart_period", 60), step=5,
            key="gc_period",
        )
        st.session_state["wl_chart_period"] = period
    else:
        period = st.slider(
            "분석 기간 (거래일)",
            min_value=10, max_value=250, value=60, step=5,
            help="기본 60일. 길수록 중장기 추세가 보입니다.",
        )

    benchmark_mode = st.radio("벤치마크", ["자동 선택", "직접 입력"], horizontal=True)
    if benchmark_mode == "직접 입력":
        custom_benchmark = st.text_input(
            "벤치마크 코드", placeholder="예: KQ11 / QQQ / ^GSPC"
        ).strip()
    else:
        custom_benchmark = None

    run = st.button("📊 차트 보기", type="primary", use_container_width=True)

    st.divider()
    if st.button("🏠 Main", use_container_width=True):
        st.session_state.view = "dashboard"
        st.session_state.sidebar_ticker = ""
        st.rerun()

    if st.button("🔍 SEPA Scanner", use_container_width=True):
        st.session_state.view = "pattern_scanner"
        st.rerun()

    if st.button("📊 RS Scanner", use_container_width=True):
        st.session_state.view = "rs_scanner"
        st.rerun()

    if st.button("🔻 Short Scanner", use_container_width=True):
        st.session_state.view = "short_scanner"
        st.rerun()

    if st.button("💼 포트폴리오", use_container_width=True):
        st.session_state.view = "portfolio"
        st.rerun()

    if st.button("🌍 시장 지표", use_container_width=True):
        st.session_state.view = "market_indicators"
        st.rerun()

    if st.button("📂 그룹 분석", use_container_width=True):
        st.session_state.view = "watchlist"
        st.rerun()

    if st.button("👀 관심종목", use_container_width=True):
        st.session_state.view = "watchlist_stocks"
        st.rerun()

    # 로그아웃 (클라우드 모드)
    if _CLOUD_MODE and st.session_state.get("authenticated"):
        st.divider()
        _user_email = st.session_state.get("user_email", "")
        st.caption(f"👤 {_user_email}")
        if st.button("🚪 로그아웃", use_container_width=True):
            logout()

    # 뒤로 가기 (차트 보는 중일 때)
    if st.session_state.get("view") == "chart":
        return_to = st.session_state.get("return_to_view", "rs_scanner")
        _back_labels = {
            "rs_scanner": "← RS Scanner로",
            "pattern_scanner": "← SEPA Scanner로",
            "short_scanner": "← Short Scanner로",
            "portfolio": "← 포트폴리오로",
            "watchlist":        "← 그룹 분석으로",
            "group_chart":      "← 그룹 분석으로",
            "watchlist_stocks": "← 관심종목으로",
        }
        back_label = _back_labels.get(return_to, "← 뒤로")
        if st.button(back_label, use_container_width=True):
            st.session_state.view = return_to
            st.session_state.sidebar_ticker = ""
            st.rerun()

    st.divider()
    st.markdown("""
**코드 예시**
| 종목 | 코드 |
|------|------|
| 삼성전자 | 005930 |
| SK하이닉스 | 000660 |
| 카카오 | 035720 |
| Apple | AAPL |
| Tesla | TSLA |
| NVIDIA | NVDA |

**벤치마크 코드**
| 지수 | 코드 |
|------|------|
| KOSPI | KS11 |
| KOSDAQ | KQ11 |
| S&P 500 | ^GSPC |
| NASDAQ | QQQ |
""")


# ══════════════════════════════════════════════════════════
# 탭 자동 선택 (차트에서 돌아올 때)
# ══════════════════════════════════════════════════════════

def _jump_to_tab(tab_index: int):
    """JavaScript로 특정 탭 버튼을 클릭"""
    _stc.html(f"""
    <script>
    (function() {{
        function clickTab() {{
            const tabs = window.parent.document.querySelectorAll('[role="tab"]');
            if (tabs.length > {tab_index}) {{
                tabs[{tab_index}].click();
            }}
        }}
        setTimeout(clickTab, 150);
    }})();
    </script>
    """, height=0)


# ══════════════════════════════════════════════════════════
# 세션 초기화
# ══════════════════════════════════════════════════════════
if "view" not in st.session_state:
    st.session_state.view = "dashboard"
if "chart_ticker" not in st.session_state:
    st.session_state.chart_ticker = ""
if "chart_name" not in st.session_state:
    st.session_state.chart_name = ""
if "chart_period" not in st.session_state:
    st.session_state.chart_period = 20
if "confirmed_rank_period" not in st.session_state:
    st.session_state.confirmed_rank_period = 60
if "return_tab_index" not in st.session_state:
    st.session_state.return_tab_index = 0
if "return_to_view" not in st.session_state:
    st.session_state.return_to_view = "rs_scanner"
if "return_top_tab" not in st.session_state:
    st.session_state.return_top_tab = 0  # 0=한국, 1=미국

# 종목코드 입력 후 엔터 or 버튼 클릭 시 차트 이동
_ticker_changed = ticker_input and ticker_input != st.session_state.get("sidebar_ticker", "")
if (run or _ticker_changed) and ticker_input:
    st.session_state.view         = "chart"
    st.session_state.chart_ticker = ticker_input
    st.session_state.chart_period = period
    st.session_state.sidebar_ticker = ticker_input
    st.rerun()


# ══════════════════════════════════════════════════════════
# 차트 렌더링 함수
# ══════════════════════════════════════════════════════════
def show_chart(ticker_raw: str, period: int, custom_benchmark=None):
    ticker_raw = resolve_korean_name(ticker_raw)
    ticker = ticker_raw if ticker_raw.isdigit() else ticker_raw.upper()
    market = detect_market(ticker)

    if custom_benchmark:
        benchmark_code = custom_benchmark.upper() if not custom_benchmark.isdigit() else custom_benchmark
        benchmark_name = benchmark_code
    else:
        benchmark_code, benchmark_name = get_benchmark(ticker, market)

    # 기간 버튼 / 종목·벤치마크·기간 메트릭은 차트 내부 헤더로 이동하여 숨김
    # _period_presets = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "2Y": 504}
    # _p_override_key = f"period_override_{ticker}"
    # if _p_override_key in st.session_state:
    #     period = st.session_state[_p_override_key]
    # _btn_cols = st.columns([1]*len(_period_presets) + [6])
    # for i, (lbl, days) in enumerate(_period_presets.items()):
    #     _active = (period == days)
    #     if _btn_cols[i].button(lbl, key=f"pb_{ticker}_{lbl}",
    #                            type="primary" if _active else "secondary",
    #                            use_container_width=True):
    #         st.session_state[_p_override_key] = days
    #         st.session_state.chart_period = days
    #         st.rerun()
    # col1, col2, col3 = st.columns(3)
    # col1.metric("종목", ticker, f"{'한국' if market == 'KR' else '미국'} 주식")
    # col2.metric("벤치마크", benchmark_name)
    # col3.metric("분석 기간", f"{period}일")
    # st.divider()

    with st.spinner("데이터 수집 중..."):
        try:
            stock_df, index_df = fetch_data(ticker, benchmark_code, period)
        except Exception as e:
            st.error(f"데이터 수집 실패: {e}")
            return

    _preset_name = st.session_state.pop("chart_name", "") or ""
    stock_name   = _preset_name if _preset_name and _preset_name != ticker else get_stock_name(ticker, market)
    stock_full, index_full = align_data(stock_df, index_df)
    mas_full               = calculate_mas(stock_full["Close"])

    # RS Score: trimmed 기간 기준
    s_trim, i_trim, _ = trim_to_period(stock_full, index_full, mas_full, period)

    if len(s_trim) < 4:
        st.error("데이터가 너무 적습니다. 기간을 늘려주세요.")
        return

    rs_line_trim, rs_score, stock_ret, index_ret = calculate_ibd_rs(s_trim, i_trim)
    rs_line_full, _, _, _ = calculate_ibd_rs(stock_full, index_full)

    # 차트 RS Line: 설정 기간 시작점=100으로 재정규화 → 수치 박스와 일치
    trim_start = s_trim.index[0]
    if trim_start in rs_line_full.index:
        anchor = rs_line_full[trim_start]
    else:
        pos = rs_line_full.index.searchsorted(trim_start)
        anchor = rs_line_full.iloc[min(pos, len(rs_line_full) - 1)]
    rs_line_display = rs_line_full / anchor * 100

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("RS Score", f"{rs_score:+.2f}",
                delta="강세" if rs_score >= 0 else "약세",
                delta_color="normal" if rs_score >= 0 else "inverse")
    col2.metric("RS Line",       f"{rs_line_trim.iloc[-1]:.2f}", delta="기준: 100")
    col3.metric("종목 수익률",   f"{stock_ret:+.2f}%")
    col4.metric(f"{benchmark_name} 수익률", f"{index_ret:+.2f}%")

    st.caption(
        f"데이터 기간: {stock_df.index[0].date()} ~ {stock_df.index[-1].date()} "
        f"({len(stock_df)}거래일)  ·  업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    set_portfolio_file("portfolio.json" if market == "KR" else "portfolio_us.json")
    trades = get_trades_by_ticker(ticker)

    # 현재 손절가/1차익절가 추출 (보유 중인 포지션)
    _stop_loss = None
    _take_profit = None
    if trades:
        _open_pos = get_open_positions()
        if _open_pos is not None and not _open_pos.empty:
            _pos_row = _open_pos[_open_pos["종목코드"] == ticker] if "종목코드" in _open_pos.columns else None
            if _pos_row is not None and not _pos_row.empty:
                if "손절가" in _pos_row.columns:
                    _sl_val = _pos_row.iloc[0]["손절가"]
                    if _sl_val and float(_sl_val) > 0:
                        _stop_loss = float(_sl_val)
                if "1차익절가" in _pos_row.columns:
                    _tp_val = _pos_row.iloc[0]["1차익절가"]
                    if _tp_val and float(_tp_val) > 0:
                        _take_profit = float(_tp_val)

    # 구버전(Plotly)은 코드 유지하되 UI에서 숨김
    # chart_ver = st.radio(
    #     "차트 버전", ["신버전 (ECharts)", "구버전 (Plotly)"],
    #     horizontal=True, index=0, label_visibility="collapsed",
    #     key=f"chart_ver_{ticker}",
    # )
    build_chart_echarts(
        ticker, stock_name, benchmark_name, market, period,
        stock_full, index_full, mas_full,
        rs_line_display, rs_score, stock_ret, index_ret,
        trades=trades or None,
        stop_loss_price=_stop_loss,
        take_profit_price=_take_profit,
    )

    # ── 재무 데이터 (차트 하단) ───────────────────────────
    _show_financials(ticker, market)


def _color_growth(val):
    try:
        v = float(str(val).replace("%", "").replace("+", ""))
        return "color: #c0392b" if v > 0 else ("color: #1a5ecc" if v < 0 else "")
    except Exception:
        return ""


_CUSTOM_DESC_FILE = Path(__file__).parent / "company_desc.json"

def _load_custom_descs() -> dict:
    if not _CUSTOM_DESC_FILE.exists():
        return {}
    try:
        return json.load(open(_CUSTOM_DESC_FILE, encoding="utf-8"))
    except Exception:
        return {}

def _save_custom_desc(ticker: str, fields: dict):
    data = _load_custom_descs()
    data[ticker] = fields
    json.dump(data, open(_CUSTOM_DESC_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def _show_financials(ticker: str, market: str):
    """매출액·영업이익 연간/분기 테이블 (차트 하단)"""
    try:
        import yfinance as yf
    except Exception:
        return  # yfinance 미설치

    is_kr      = (market == "KR")
    unit_label = "억원" if is_kr else "백만$"
    unit_div   = 1e8   if is_kr else 1e6

    yf_sym = ticker + ".KS" if is_kr else ticker

    # 세션 캐시 (성공한 데이터만 캐시, 실패 시 매번 재시도)
    cache_key = f"fin2_{yf_sym}"
    if cache_key not in st.session_state:
        try:
            with st.spinner("재무 데이터 로딩..."):
                t       = yf.Ticker(yf_sym)
                annual  = t.financials
                quarter = t.quarterly_financials
                if is_kr and (annual is None or annual.empty):
                    t2      = yf.Ticker(ticker + ".KQ")
                    annual  = t2.financials
                    quarter = t2.quarterly_financials
            # 데이터가 있을 때만 캐시
            if annual is not None and not annual.empty:
                st.session_state[cache_key] = (annual, quarter)
            else:
                return  # 데이터 없으면 섹션 숨김
        except Exception:
            return

    try:
        annual_raw, quarter_raw = st.session_state[cache_key]
    except Exception:
        return

    def _build_df(raw, yoy_periods=1):
        try:
            if raw is None or raw.empty:
                return None
            needed = [r for r in ["Total Revenue", "Operating Income"] if r in raw.index]
            if not needed:
                return None
            # rows=dates, cols=items (중간 계산용)
            df = raw.loc[needed].T.dropna(how="all").copy()
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            rev_col = f"매출액({unit_label})"
            opr_col = f"영업이익({unit_label})"
            df.rename(columns={"Total Revenue": rev_col, "Operating Income": opr_col}, inplace=True)
            for col in [rev_col, opr_col]:
                if col in df.columns:
                    df[col] = (pd.to_numeric(df[col], errors="coerce") / unit_div).round(1)
            if rev_col in df.columns:
                df["매출증가율(%)"] = (df[rev_col].pct_change(yoy_periods) * 100).round(1)
            if opr_col in df.columns:
                df["영업이익증가율(%)"] = (df[opr_col].pct_change(yoy_periods) * 100).round(1)
            df.index = df.index.strftime("%Y-%m")
            df = df.iloc[::-1]   # 최신순
            return df.T          # 행=재무항목, 열=날짜
        except Exception:
            return None

    def _render_df(df, key_suffix: str):
        if df is None or df.empty:
            st.caption("데이터 없음")
            return
        try:
            # 행=재무항목, 열=시간단위 (날짜)
            df_t = df.reset_index()
            df_t = df_t.rename(columns={"index": "항목"})
            # 날짜 컬럼을 "YYYY-MM" 형식으로 포맷
            date_cols = [c for c in df_t.columns if c != "항목"]
            rename_map = {}
            for c in date_cols:
                try:
                    rename_map[c] = str(c)[:7]
                except Exception:
                    pass
            df_t = df_t.rename(columns=rename_map)
            growth_cols = [c for c in df_t.columns if "증가율" in str(c)]
            _aggrid(df_t, key=f"fin_{key_suffix}", height=200, click_nav=False,
                    color_map={c: "red_positive" for c in growth_cols},
                    col_widths={"항목": 160})
        except Exception as e:
            st.caption(f"표시 오류: {e}")

    df_a = _build_df(annual_raw, yoy_periods=1)   # 연간: 전년대비
    df_q = _build_df(quarter_raw, yoy_periods=4)  # 분기: 전년동기대비

    if df_a is None and df_q is None:
        return  # 표시할 데이터 없으면 섹션 숨김

    # ── 회사 설명 ────────────────────────────────────────────
    try:
        auto_key = f"auto_desc_{ticker}"
        edit_key     = f"desc_edit_{ticker}"
        expander_key = f"desc_expander_{ticker}"

        # 자동 조회 캐시 (섹터/산업/설명 텍스트)
        if auto_key not in st.session_state:
            _auto = {"sector": "", "industry": "", "desc": ""}
            try:
                _info = yf.Ticker(yf_sym).info
                if not _info.get("longBusinessSummary") and is_kr:
                    _info = yf.Ticker(ticker + ".KQ").info
                _auto["sector"]   = _info.get("sector", "")
                _auto["industry"] = _info.get("industry", "")
                _auto["desc"]     = _info.get("longBusinessSummary", "")
            except Exception:
                pass
            # 네이버 fallback (설명만)
            if not _auto["desc"] and is_kr:
                try:
                    import requests as _req
                    from bs4 import BeautifulSoup as _BS
                    _nr = _req.get(f"https://finance.naver.com/item/coinfo.naver?code={ticker}",
                                   headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
                    _paras = [p.get_text(strip=True)
                              for p in _BS(_nr.text, "html.parser").select(".wrap_company p")
                              if p.get_text(strip=True)]
                    _auto["desc"] = " ".join(_paras)
                except Exception:
                    pass
            st.session_state[auto_key] = _auto
        auto = st.session_state[auto_key]

        # 사용자 저장값
        custom_descs = _load_custom_descs()
        saved = custom_descs.get(ticker, {})

        with st.expander("🏢 Company", expanded=st.session_state.get(expander_key, bool(saved))):
            if st.session_state.get(edit_key, False):
                # ── 편집 모드 ──
                c1, c2 = st.columns(2)
                new_sector   = c1.text_input("섹터",     value=saved.get("sector",   auto.get("sector", "")),   key=f"di_sector_{ticker}")
                new_industry = c2.text_input("산업",     value=saved.get("industry", auto.get("industry", "")), key=f"di_industry_{ticker}")
                new_products = st.text_area("주요제품/서비스", value=saved.get("products", ""), height=100, key=f"di_products_{ticker}")
                new_memo     = st.text_area("메모 (산업 추세, 투자 근거 등)", value=saved.get("memo", ""),
                                            height=120, key=f"di_memo_{ticker}")
                b1, b2, _ = st.columns([1, 1, 4])
                if b1.button("💾 저장", key=f"di_save_{ticker}", type="primary"):
                    _save_custom_desc(ticker, {
                        "sector":   new_sector.strip(),
                        "industry": new_industry.strip(),
                        "products": new_products.strip(),
                        "memo":     new_memo.strip(),
                    })
                    st.session_state[edit_key]     = False
                    st.session_state[expander_key] = True
                    st.rerun()
                if b2.button("취소", key=f"di_cancel_{ticker}"):
                    st.session_state[edit_key]     = False
                    st.session_state[expander_key] = True
                    st.rerun()
            else:
                # ── 표시 모드 ──
                if saved:
                    c1, c2 = st.columns(2)
                    c1.markdown(f"**섹터** {saved.get('sector', '-')}")
                    c2.markdown(f"**산업** {saved.get('industry', '-')}")
                    if saved.get("products"):
                        st.markdown(f"**주요제품/서비스**")
                        st.caption(saved["products"])
                    if saved.get("memo"):
                        st.markdown("**메모**")
                        st.caption(saved["memo"])
                    st.divider()
                if auto.get("desc"):
                    st.caption(auto["desc"])
                _badge = " 📝" if saved else ""
                if st.button(f"✏️ 편집{_badge}", key=f"di_edit_btn_{ticker}"):
                    st.session_state[edit_key]     = True
                    st.session_state[expander_key] = True
                    st.rerun()
    except Exception:
        pass

    st.markdown("##### 📊 재무 요약")
    tab_annual, tab_quarter = st.tabs(["연간", "분기"])
    with tab_annual:
        _render_df(df_a, f"annual_{ticker}")
    with tab_quarter:
        _render_df(df_q, f"quarter_{ticker}")


# ══════════════════════════════════════════════════════════
# 랭킹 테이블 렌더링 함수
# ══════════════════════════════════════════════════════════
def _style_rs(val):
    try:
        color = "#c0392b" if float(val) >= 0 else "#1a5ecc"
        return f"color: {color}; font-weight: bold"
    except Exception:
        return ""


def show_ranking_table(market: str, rank_period: int, auto_calc: bool = True):
    """순위 테이블 렌더링. 행 클릭 시 해당 종목 차트로 이동."""
    # 차트에서 돌아온 경우 직전 탭으로 자동 이동
    ret_idx = st.session_state.get("return_tab_index", 0)
    if ret_idx > 0:
        _jump_to_tab(ret_idx)
        st.session_state.return_tab_index = 0

    _is_us   = market in ("NASDAQ", "NYSE")
    _min_price = 10.0 if _is_us else 0

    cache_key = f"ranking_{market}_{rank_period}"

    # 강제 재계산 플래그
    _force_all = st.session_state.get("_force_rs_all", False)

    # 강제 재계산: 캐시 무시하고 새로 계산
    if _force_all:
        n_cands = {"KOSPI": "약 951종목", "KOSDAQ": "약 1820종목", "NASDAQ": "약 3500종목", "NYSE": "약 2000종목"}.get(market, "")
        status = st.empty()
        bar = st.progress(0)
        status.info(f"⏳ {market} 강제 재계산 중... ({n_cands})")

        def _cb_force_rs(done, total):
            pct = int(done / total * 100)
            bar.progress(pct)
            status.info(f"⏳ {market} 재계산 중... {done}/{total}종목 ({pct}%)")

        try:
            df = calc_market_ranking(market=market, period=rank_period,
                                     top_n=100, min_price=_min_price, progress_cb=_cb_force_rs, use_cache=False)
            st.session_state[cache_key] = df
        except Exception as e:
            status.error(f"{market} 재계산 실패: {e}")
            bar.empty()
            return
        finally:
            bar.empty()
            status.empty()

    # 세션 캐시 없으면 파일 캐시 or 신규 계산
    if cache_key not in st.session_state:
        cache_time = get_cache_info(market, rank_period)

        if cache_time:
            # 파일 캐시 있음 → 조용히 로드
            df = calc_market_ranking(market=market, period=rank_period, top_n=100, min_price=_min_price)
            st.session_state[cache_key] = df
        elif not auto_calc:
            # 자동 계산 비활성 → 버튼으로만 시작
            total_msg = {
                "NASDAQ": "약 3500종목 (20~30분 소요)",
                "NYSE":   "약 2000종목 (15~20분 소요)",
            }.get(market, "")
            st.info(f"{market} 랭킹이 아직 계산되지 않았습니다. {total_msg}")
            if st.button(f"🚀 {market} 랭킹 계산 시작", key=f"calc_btn_{market}_{rank_period}"):
                status = st.empty()
                bar    = st.progress(0)
                status.info(f"⏳ {market} 계산 시작...")
                def progress_cb(done, total):
                    pct = int(done / total * 100)
                    bar.progress(pct)
                    status.info(f"⏳ {market} 분석 중... {done}/{total}종목 ({pct}%)")
                try:
                    df = calc_market_ranking(market=market, period=rank_period,
                                             top_n=100, min_price=_min_price, progress_cb=progress_cb)
                    st.session_state[cache_key] = df
                except Exception as e:
                    status.error(f"{market} 랭킹 계산 실패: {e}")
                    return
                finally:
                    bar.empty()
                    status.empty()
                st.rerun()
            return
        else:
            # 자동 계산 활성 → 전체 계산, 프로그레스바 표시
            status = st.empty()
            bar    = st.progress(0)
            total_msg = {
                "KOSPI":  "KOSPI 약 951종목",
                "KOSDAQ": "KOSDAQ 약 1820종목",
            }.get(market, market)
            status.info(f"⏳ {market} 전체 계산 중... ({total_msg}, 첫 실행 시 수 분 소요)")

            def progress_cb(done, total):
                pct = int(done / total * 100)
                bar.progress(pct)
                status.info(f"⏳ {market} 분석 중... {done}/{total}종목 ({pct}%)")

            try:
                df = calc_market_ranking(market=market, period=rank_period,
                                         top_n=100, min_price=_min_price, progress_cb=progress_cb)
                st.session_state[cache_key] = df
            except Exception as e:
                status.error(f"{market} 랭킹 계산 실패: {e}")
                bar.empty()
                return
            finally:
                bar.empty()
                status.empty()

    # 강제 재계산 플래그 정리
    st.session_state.pop("_force_rs_all", None)

    df = st.session_state[cache_key]
    if df is None or df.empty:
        st.warning(f"{market} 데이터를 불러오지 못했습니다.")
        return

    # 52주 신고가 컬럼 있을 때만 그룹 분리
    has_high = "고가대비(%)" in df.columns

    if has_high:
        df_low_base  = df[(df["고가대비(%)"] <= -20) & (df["고가대비(%)"] >= -40)].copy()
        df_high_base = df[(df["고가대비(%)"] >  -20) & (df["고가대비(%)"] <   -5)].copy()
        df_breakout  = df[df["고가대비(%)"] >= -5].copy()
        vcp_cache_key = f"vcp_{market}_{rank_period}"
        s2_cache_key  = f"stage2_{market}_{rank_period}"
        tab_all, tab_low, tab_high, tab_bo = st.tabs([
            f"전체 RS ({len(df)})",
            f"낮은 베이스 -20~-40% ({len(df_low_base)})",
            f"높은 베이스 -5~-20% ({len(df_high_base)})",
            f"신고가 -5% 이내 ({len(df_breakout)})",
        ])
        tab_vcp = None
        tab_s2  = None
        tabs = [
            (tab_all,  df,           "all",       0),
            (tab_low,  df_low_base,  "low_base",  1),
            (tab_high, df_high_base, "high_base", 2),
            (tab_bo,   df_breakout,  "bo",        3),
        ]
    else:
        tab_all = st.tabs(["전체 RS"])[0]
        tabs = [(tab_all, df, "all", 0)]
        tab_vcp = None
        tab_s2  = None
        vcp_cache_key = None
        s2_cache_key  = None

    fmt = {
        "현재가":      "${:,.2f}" if _is_us else "{:,.0f}",
        "RS Score":    "{:+.2f}",
        "RS Line":     "{:.2f}",
        "종목수익률":  "{:+.2f}%",
        "지수수익률":  "{:+.2f}%",
        "고가대비(%)": "{:+.2f}%",
    }

    for tab, data, key_suffix, tab_idx in tabs:
        with tab:
            if data.empty:
                st.info("해당 조건의 종목이 없습니다.")
                continue

            # 표시 컬럼 순서
            show_cols = ["종목코드", "종목명", "현재가", "RS Score", "RS Line", "종목수익률", "지수수익률"]
            if has_high:
                show_cols += ["고가대비(%)"]
            show_cols += ["ATR(20)", "ATR(%)"]
            show_cols = [c for c in show_cols if c in data.columns]
            display_df = data[show_cols].reset_index(drop=True)
            display_df.index += 1
            display_df.index.name = "순위"

            _rs_color_map = {"RS Score": "red_positive", "RS Line": "red_positive", "종목수익률": "red_positive"}
            if has_high:
                _rs_color_map["고가대비(%)"] = "red_positive"
            _n_rows = len(display_df)
            _height = 250 if _n_rows <= 5 else (350 if _n_rows <= 10 else 450)
            result = _aggrid(
                display_df.reset_index(),
                key=f"table_{market}_{rank_period}_{key_suffix}",
                height=_height,
                click_nav=True,
                color_map=_rs_color_map,
            )
            selected = result["selected_rows"]
            if selected is not None and len(selected) > 0:
                row = selected[0]
                st.session_state.view             = "chart"
                st.session_state.chart_ticker     = row["종목코드"]
                st.session_state.chart_name       = row.get("종목명", "")
                st.session_state.chart_period     = rank_period
                st.session_state.sidebar_ticker   = row["종목코드"]
                st.session_state.return_tab_index = tab_idx
                st.session_state.return_to_view   = "rs_scanner"
                st.session_state.return_top_tab   = 1 if _is_us else 0
                st.rerun()

    # ── VCP / 2단계 탭 공통 렌더러 ────────────────────────
    filter_show_cols = ["종목코드", "종목명", "현재가", "RS Score", "RS Line", "종목수익률", "지수수익률", "고가대비(%)", "ATR(20)", "ATR(%)"]

    def _render_filter_table(data, key: str, tab_idx: int = 0):
        if data.empty:
            st.info("해당 조건의 종목이 없습니다.")
            return
        disp = data.copy()
        for c in filter_show_cols:
            if c not in disp.columns:
                disp[c] = None
        disp = disp[[c for c in filter_show_cols if c in disp.columns]].reset_index(drop=True)
        _n_rows = len(disp)
        _height = 250 if _n_rows <= 5 else (350 if _n_rows <= 10 else 450)
        _filter_color_map = {
            "RS Score": "red_positive", "RS Line": "red_positive",
            "종목수익률": "red_positive", "고가대비(%)": "red_positive",
        }
        result = _aggrid(disp, key=key, height=_height, click_nav=True, color_map=_filter_color_map)
        selected = result["selected_rows"]
        if selected is not None and len(selected) > 0:
            row = selected[0]
            st.session_state.view             = "chart"
            st.session_state.chart_ticker     = row["종목코드"]
            st.session_state.chart_name       = row.get("종목명", "")
            st.session_state.chart_period     = rank_period
            st.session_state.sidebar_ticker   = row["종목코드"]
            st.session_state.return_tab_index = tab_idx
            st.session_state.return_to_view   = "rs_scanner"
            st.session_state.return_top_tab   = 1 if _is_us else 0
            st.rerun()

    # ── VCP 필터 ────────────────────────────────────────────
    if has_high:
        st.markdown("### 📉 VCP 후보 필터")
        vcp_file_time = get_filter_cache_info("vcp", market, rank_period)
        _vcp_force_key = f"_force_vcp_{market}_{rank_period}"
        _vcp_force = st.session_state.pop(_vcp_force_key, False) or st.session_state.get("_force_rs_all", False)

        if _vcp_force:
            with st.spinner("VCP 재계산 중..."):
                st.session_state[vcp_cache_key] = apply_vcp_filter(df, market=market, period=rank_period, use_cache=False)

        if vcp_cache_key not in st.session_state:
            if vcp_file_time:
                with st.spinner("VCP 캐시 로드 중..."):
                    st.session_state[vcp_cache_key] = apply_vcp_filter(df, market=market, period=rank_period)
                st.rerun()
            else:
                if st.button("🔍 VCP 조건 계산", key=f"vcp_btn_{market}_{rank_period}"):
                    with st.spinner("VCP 조건 확인 중... (상위 100종목)"):
                        st.session_state[vcp_cache_key] = apply_vcp_filter(df, market=market, period=rank_period)
                    st.rerun()
                st.caption("버튼을 클릭하면 상위 100종목의 VCP 조건을 계산합니다. (하루 1회 캐시 저장)")

        if vcp_cache_key in st.session_state:
            df_vcp           = st.session_state[vcp_cache_key]
            df_vcp_low_base  = df_vcp[(df_vcp["고가대비(%)"] <= -20) & (df_vcp["고가대비(%)"] >= -40)]
            df_vcp_high_base = df_vcp[(df_vcp["고가대비(%)"] >  -20) & (df_vcp["고가대비(%)"] <   -5)]
            df_vcp_bo        = df_vcp[df_vcp["고가대비(%)"] >= -5]
            st.markdown(f"**전체 VCP 후보 ({len(df_vcp)})**")
            _render_filter_table(df_vcp, f"tbl_{market}_{rank_period}_vcp_all", tab_idx=0)
            st.divider()
            st.markdown(f"**낮은 베이스 -20%~-40% ({len(df_vcp_low_base)})**")
            _render_filter_table(df_vcp_low_base, f"tbl_{market}_{rank_period}_vcp_low_base", tab_idx=0)
            st.divider()
            st.markdown(f"**높은 베이스 -5%~-20% ({len(df_vcp_high_base)})**")
            _render_filter_table(df_vcp_high_base, f"tbl_{market}_{rank_period}_vcp_high_base", tab_idx=0)
            st.divider()
            st.markdown(f"**신고가 -5% 이내 ({len(df_vcp_bo)})**")
            _render_filter_table(df_vcp_bo, f"tbl_{market}_{rank_period}_vcp_bo", tab_idx=0)
            t = vcp_file_time or "세션 계산"
            st.caption(f"3일 평균 거래량 < 60일 평균 × 80%  ·  3일 고저폭 ≤ 5%  ·  캐시: {t}")
            if st.button("🔄 재계산", key=f"vcp_recalc_{market}_{rank_period}"):
                st.session_state[_vcp_force_key] = True
                st.rerun()

    # ── 2단계 필터 ──────────────────────────────────────────
    if has_high:
        st.markdown("### 📈 2단계 시작 필터")
        s2_file_time = get_filter_cache_info("stage2", market, rank_period)
        _s2_force_key = f"_force_s2_{market}_{rank_period}"
        _s2_force = st.session_state.pop(_s2_force_key, False) or st.session_state.get("_force_rs_all", False)

        if _s2_force:
            with st.spinner("2단계 재계산 중..."):
                st.session_state[s2_cache_key] = apply_stage2_filter(df, market=market, period=rank_period, use_cache=False)

        if s2_cache_key not in st.session_state:
            if s2_file_time:
                with st.spinner("2단계 캐시 로드 중..."):
                    st.session_state[s2_cache_key] = apply_stage2_filter(df, market=market, period=rank_period)
                st.rerun()
            else:
                if st.button("🔍 2단계 조건 계산", key=f"s2_btn_{market}_{rank_period}"):
                    with st.spinner("2단계 조건 확인 중... (상위 100종목)"):
                        st.session_state[s2_cache_key] = apply_stage2_filter(df, market=market, period=rank_period)
                    st.rerun()
                st.caption("버튼을 클릭하면 상위 100종목의 2단계 시작 조건을 계산합니다. (하루 1회 캐시 저장)")

        if s2_cache_key in st.session_state:
            df_s2           = st.session_state[s2_cache_key]
            df_s2_low_base  = df_s2[(df_s2["고가대비(%)"] <= -20) & (df_s2["고가대비(%)"] >= -40)]
            df_s2_high_base = df_s2[(df_s2["고가대비(%)"] >  -20) & (df_s2["고가대비(%)"] <   -5)]
            df_s2_bo        = df_s2[df_s2["고가대비(%)"] >= -5]
            st.markdown(f"**전체 2단계 후보 ({len(df_s2)})**")
            _render_filter_table(df_s2, f"tbl_{market}_{rank_period}_s2_all", tab_idx=0)
            st.divider()
            st.markdown(f"**낮은 베이스 -20%~-40% ({len(df_s2_low_base)})**")
            _render_filter_table(df_s2_low_base, f"tbl_{market}_{rank_period}_s2_low_base", tab_idx=0)
            st.divider()
            st.markdown(f"**높은 베이스 -5%~-20% ({len(df_s2_high_base)})**")
            _render_filter_table(df_s2_high_base, f"tbl_{market}_{rank_period}_s2_high_base", tab_idx=0)
            st.divider()
            st.markdown(f"**신고가 -5% 이내 ({len(df_s2_bo)})**")
            _render_filter_table(df_s2_bo, f"tbl_{market}_{rank_period}_s2_bo", tab_idx=0)
            t = s2_file_time or "세션 계산"
            st.caption(f"종가 > MA20 > MA60  ·  MA20 기울기 양수  ·  MA60 기울기 ≥ 0  ·  캐시: {t}")
            if st.button("🔄 재계산", key=f"s2_recalc_{market}_{rank_period}"):
                st.session_state[_s2_force_key] = True
                st.rerun()

    cache_time = get_cache_info(market, rank_period)
    st.caption(
        f"📅 저장: {cache_time or '방금 계산'}  ·  기간: {rank_period}일  ·  행 클릭 시 차트로 이동"
    )


# ══════════════════════════════════════════════════════════
# 대시보드 (메인 화면)
# ══════════════════════════════════════════════════════════

@st.cache_data(ttl=300)   # 5분 캐시
def _fetch_market_snapshot():
    """주요 시장 지표 스냅샷 (대시보드용) — 병렬 조회"""
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor
    end = datetime.now()
    start = end - timedelta(days=7)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    items = {
        "코스피":   "KS11",
        "코스닥":   "KQ11",
        "S&P500":  "^GSPC",
        "나스닥":   "^IXIC",
        "USD/KRW": "USD/KRW",
        "달러인덱스": "DX-Y.NYB",
        "미국10년물": "^TNX",
        "WTI":     "CL=F",
        "금":      "GC=F",
    }

    def _fetch_one(item):
        label, code = item
        try:
            df = fdr.DataReader(code, s, e)
            if df is not None and not df.empty:
                df = df.dropna(subset=["Close"])
            if df is not None and len(df) >= 2:
                cur  = float(df.iloc[-1]["Close"])
                prev = float(df.iloc[-2]["Close"])
                chg  = cur - prev
                chg_pct = (chg / prev * 100) if prev else 0
                return label, {"price": cur, "change": chg, "change_pct": chg_pct}
            elif df is not None and len(df) == 1:
                cur = float(df.iloc[-1]["Close"])
                return label, {"price": cur, "change": 0, "change_pct": 0}
        except Exception:
            pass
        return label, None

    result = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for label, data in pool.map(_fetch_one, items.items()):
            if data:
                result[label] = data
    result["_fetched_at"] = end.strftime("%Y-%m-%d %H:%M")
    return result


def _metric_delta(val, pct, is_currency=False, decimal=2):
    """metric 표시용 delta 문자열"""
    sign = "+" if val >= 0 else ""
    if is_currency:
        return f"{sign}{val:,.{decimal}f} ({sign}{pct:.2f}%)"
    return f"{sign}{val:,.{decimal}f} ({sign}{pct:.2f}%)"


def show_dashboard():
    st.title("📈 SEPA Dashboard")
    st.caption("Specific Entry Point Analysis  ·  Market Index & 포트폴리오 요약")

    # ── 1) 시장 지수 요약 ──────────────────────────────────
    snap = _fetch_market_snapshot()
    _fetched = snap.get("_fetched_at", "")
    st.markdown(f"### Market Index &nbsp; <small style='color:#888; font-weight:normal;'>{_fetched}</small>", unsafe_allow_html=True)

    # 주요 지수 4개
    idx_cols = st.columns(4)
    idx_items = [
        ("코스피", 0, ",.2f"),
        ("코스닥", 0, ",.2f"),
        ("S&P500", 0, ",.2f"),
        ("나스닥", 0, ",.2f"),
    ]
    for col, (label, _, fmt) in zip(idx_cols, idx_items):
        d = snap.get(label)
        if d:
            delta_str = f"{d['change']:+,.2f} ({d['change_pct']:+.2f}%)"
            col.metric(label, f"{d['price']:,.2f}", delta_str,
                       delta_color="normal")
        else:
            col.metric(label, "—", "데이터 없음")

    # 매크로 지표 5개
    macro_cols = st.columns(5)
    macro_items = [
        ("USD/KRW",   "원/달러",    2),
        ("달러인덱스",  "DXY",       2),
        ("미국10년물",  "US 10Y",    4),
        ("WTI",       "WTI $/bbl",  2),
        ("금",        "Gold $/oz",  2),
    ]
    for col, (key, label, dec) in zip(macro_cols, macro_items):
        d = snap.get(key)
        if d:
            delta_str = f"{d['change']:+,.{dec}f} ({d['change_pct']:+.2f}%)"
            col.metric(label, f"{d['price']:,.{dec}f}", delta_str,
                       delta_color="off")
        else:
            col.metric(label, "—", "")

    if st.button("🌍 시장 지표 상세 보기 →", key="dash_to_mkt_ind"):
        st.session_state.view = "market_indicators"
        st.rerun()

    st.divider()

    # ── 2) 포트폴리오 요약 ──────────────────────────────────
    dash_left, dash_right = st.columns([3, 2])

    with dash_left:
        st.subheader("보유 포트폴리오")

        # 한국 포트폴리오
        set_portfolio_file("portfolio.json")
        kr_open = get_open_positions()
        # 미국 포트폴리오
        set_portfolio_file("portfolio_us.json")
        us_open = get_open_positions()
        # 원복
        set_portfolio_file("portfolio.json")

        if kr_open.empty and us_open.empty:
            st.info("보유 중인 종목이 없습니다.")
        else:
            # 한국
            kr_total = 0
            if not kr_open.empty:
                st.markdown("**한국**")
                _kr_summary = kr_open[["종목명", "평균매수가", "수량", "손절가", "경과일"]].copy()
                _kr_summary["매수금액"] = _kr_summary["평균매수가"] * _kr_summary["수량"]
                kr_total = _kr_summary["매수금액"].sum()
                # 합계 행
                _kr_total_row = pd.DataFrame([{
                    "종목명": "합계",
                    "평균매수가": None, "수량": None, "손절가": None, "경과일": None,
                    "매수금액": kr_total,
                }])
                _kr_summary = pd.concat([_kr_summary, _kr_total_row], ignore_index=True)
                st.dataframe(
                    _kr_summary.style.format({
                        "평균매수가": lambda v: f"{v:,.0f}" if pd.notna(v) else "",
                        "수량": lambda v: f"{v:,.0f}" if pd.notna(v) else "",
                        "손절가": lambda v: f"{v:,.0f}" if pd.notna(v) else "",
                        "경과일": lambda v: f"{v:.0f}" if pd.notna(v) else "",
                        "매수금액": "{:,.0f}",
                    }),
                    use_container_width=True, hide_index=True,
                )

            # 미국
            us_total = 0
            if not us_open.empty:
                st.markdown("**미국**")
                _us_summary = us_open[["종목명", "평균매수가", "수량", "손절가", "경과일"]].copy()
                _us_summary["매수금액"] = _us_summary["평균매수가"] * _us_summary["수량"]
                us_total = _us_summary["매수금액"].sum()
                # 합계 행
                _us_total_row = pd.DataFrame([{
                    "종목명": "합계",
                    "평균매수가": None, "수량": None, "손절가": None, "경과일": None,
                    "매수금액": us_total,
                }])
                _us_summary = pd.concat([_us_summary, _us_total_row], ignore_index=True)
                st.dataframe(
                    _us_summary.style.format({
                        "평균매수가": lambda v: f"{v:,.2f}" if pd.notna(v) else "",
                        "수량": lambda v: f"{v:,.0f}" if pd.notna(v) else "",
                        "손절가": lambda v: f"{v:,.2f}" if pd.notna(v) else "",
                        "경과일": lambda v: f"{v:.0f}" if pd.notna(v) else "",
                        "매수금액": lambda v: f"${v:,.2f}" if pd.notna(v) else "",
                    }),
                    use_container_width=True, hide_index=True,
                )

    with dash_right:
        # ── 3) 손절선 근접 알림 ──────────────────────────────
        st.subheader("손절선 근접 종목")

        # 현재가 일괄 병렬 조회
        _price_targets = []
        for df_pos, market_label, is_us in [(kr_open, "KR", False), (us_open, "US", True)]:
            if df_pos.empty:
                continue
            for _, row in df_pos.iterrows():
                if row["손절가"] > 0:
                    _price_targets.append((row["종목코드"], row["종목명"], row["손절가"], market_label))

        _prices = {}
        if _price_targets:
            from concurrent.futures import ThreadPoolExecutor
            _tickers = list({t[0] for t in _price_targets})
            with ThreadPoolExecutor(max_workers=8) as pool:
                _results = list(pool.map(_fetch_current_price, _tickers))
            _prices = dict(zip(_tickers, _results))

        alerts = []
        for ticker, name, stop, mkt in _price_targets:
            cur = _prices.get(ticker, 0)
            if cur > 0:
                dist_pct = (cur - stop) / cur * 100
            else:
                dist_pct = None
            alerts.append({
                "시장": mkt,
                "종목명": name,
                "현재가": cur if cur > 0 else None,
                "손절가": stop,
                "손절거리(%)": round(dist_pct, 2) if dist_pct is not None else None,
            })

        if alerts:
            df_alerts = pd.DataFrame(alerts).sort_values("손절거리(%)")
            def _alert_color(val):
                if pd.isna(val):
                    return ""
                if val <= 3:
                    return "background-color: rgba(255,0,0,0.3)"
                elif val <= 5:
                    return "background-color: rgba(255,165,0,0.2)"
                return ""
            st.dataframe(
                df_alerts.style.map(_alert_color, subset=["손절거리(%)"]).format({
                    "현재가": lambda v: f"{v:,.2f}" if pd.notna(v) else "—",
                    "손절가": "{:,.2f}",
                    "손절거리(%)": lambda v: f"{v:.2f}%" if pd.notna(v) else "—",
                }),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("손절가가 설정된 보유 종목이 없습니다.")

        # 총자산 (원금 + 누적실현손익)
        st.divider()
        set_portfolio_file("portfolio.json")
        kr_capital = get_total_capital()
        kr_pnl_df = get_realized_pnl()
        _kr_pnl_col = [c for c in kr_pnl_df.columns if "실현손익" in c]
        kr_cum_pnl = kr_pnl_df[_kr_pnl_col[0]].sum() if _kr_pnl_col and not kr_pnl_df.empty else 0

        set_portfolio_file("portfolio_us.json")
        us_capital = get_total_capital()
        us_pnl_df = get_realized_pnl()
        _us_pnl_col = [c for c in us_pnl_df.columns if "실현손익" in c]
        us_cum_pnl = us_pnl_df[_us_pnl_col[0]].sum() if _us_pnl_col and not us_pnl_df.empty else 0
        set_portfolio_file("portfolio.json")

        if kr_capital > 0:
            kr_total_asset = kr_capital + kr_cum_pnl
            st.metric("한국 총자산", f"{kr_total_asset:,.0f} 원",
                      f"실현손익 {kr_cum_pnl:+,.0f} 원", delta_color="normal")
        if us_capital > 0:
            us_total_asset = us_capital + us_cum_pnl
            st.metric("미국 총자산", f"${us_total_asset:,.2f}",
                      f"실현손익 ${us_cum_pnl:+,.2f}", delta_color="normal")

    st.divider()

    # ── 4) 빠른 이동 ──────────────────────────────────
    st.subheader("빠른 이동")
    qc1, qc2, qc3, qc4 = st.columns(4)

    with qc1:
        if st.button("📊 RS Scanner →", type="primary", use_container_width=True, key="dash_rs_btn"):
            st.session_state.view = "rs_scanner"
            st.rerun()
    with qc2:
        if st.button("🔍 SEPA Scanner →", type="primary", use_container_width=True, key="dash_pattern_btn"):
            st.session_state.view = "pattern_scanner"
            st.rerun()
    with qc3:
        if st.button("💼 포트폴리오 →", type="primary", use_container_width=True, key="dash_portfolio_btn"):
            st.session_state.view = "portfolio"
            st.rerun()
    with qc4:
        if st.button("🧪 백테스트 →", type="primary", use_container_width=True, key="dash_backtest_btn"):
            st.session_state.view = "backtest"
            st.rerun()


# ══════════════════════════════════════════════════════════
# 시장 지표
# ══════════════════════════════════════════════════════════

def _fetch_fred_csv(series_id: str, start: str, end: str) -> pd.DataFrame:
    """FRED에서 CSV 직접 다운로드 (API 키 불필요)"""
    try:
        import requests
        from io import StringIO
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        df = pd.read_csv(StringIO(r.text), parse_dates=["observation_date"], index_col="observation_date")
        df.columns = ["Close"]
        df = df.dropna(subset=["Close"])
        df.index.name = "Date"
        return df
    except Exception:
        return pd.DataFrame()


def _fetch_ecos_key100(stat_id: str) -> pd.DataFrame:
    """ECOS 100대 지표 내부 API로 시계열 조회 (M1 등 공식 API에 없는 지표용)"""
    try:
        import requests
        url = "https://ecos.bok.or.kr/serviceEndpoint/httpService/request.json"
        payload = {
            "header": {
                "guidSeq": 1, "trxCd": "OSUSC04R01", "scrId": "IECOSPCM04",
                "sysCd": "03", "fstChnCd": "WEB", "langDvsnCd": "KO",
                "envDvsnCd": "D", "sndRspnDvsnCd": "S",
                "sndDtm": datetime.now().strftime("%Y%m%d"),
                "ipAddr": "", "usrId": "IECOSPC", "pageNum": 1, "pageCnt": 1000,
            },
            "data": {"key100statId": stat_id},
        }
        headers = {
            "Content-Type": "application/json",
            "Origin": "https://ecos.bok.or.kr",
            "Referer": "https://ecos.bok.or.kr/",
        }
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        rows = r.json()["data"]["dataDtlList"]
        records = []
        for row in rows:
            t = row["key100statDataTime"]
            v = row["key100statDataVal"]
            if not v:
                continue
            dt = pd.to_datetime(t + "01", format="%Y%m%d")
            records.append({"Date": dt, "Close": float(v)})
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records).set_index("Date").sort_index()
    except Exception:
        return pd.DataFrame()


def _fetch_ecos(stat_code: str, item_code: str, cycle: str, start: str, end: str) -> pd.DataFrame:
    """ECOS API로 시계열 데이터 조회."""
    import os
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    api_key = os.getenv("ECOS_API_KEY", "")
    # Streamlit secrets에서도 시도
    if not api_key:
        try:
            api_key = st.secrets["app"]["ECOS_API_KEY"]
        except Exception:
            pass
    if not api_key:
        return pd.DataFrame()
    try:
        import requests
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/1000/{stat_code}/{cycle}/{start}/{end}/{item_code}"
        r = requests.get(url, timeout=15)
        data = r.json()
        if "StatisticSearch" not in data:
            return pd.DataFrame()
        rows = data["StatisticSearch"]["row"]
        records = []
        for row in rows:
            t = row["TIME"]
            v = row["DATA_VALUE"]
            if not v or v == "-":
                continue
            if cycle == "D":
                dt = pd.to_datetime(t, format="%Y%m%d")
            elif cycle == "M":
                dt = pd.to_datetime(t + "01", format="%Y%m%d")
            else:
                dt = pd.to_datetime(t, format="%Y")
            records.append({"Date": dt, "Close": float(v)})
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records).set_index("Date").sort_index()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def _fetch_all_indicators(days: int = 90):
    """모든 시장 지표를 한 번에 가져와 캐싱 (개별 호출 대비 속도 대폭 개선)"""
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor
    end = datetime.now()
    start = end - timedelta(days=days)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    codes = {
        "USD/KRW": "USD/KRW", "DXY": "DX-Y.NYB",
        "US10Y": "^TNX", "US2Y": "2YY=F", "VIX": "^VIX",
        "WTI": "CL=F", "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F", "NatGas": "NG=F",
        "코스피": "KS11", "코스닥": "KQ11",
        "S&P500": "^GSPC", "나스닥": "^IXIC",
    }

    def _fetch_one(item):
        label, code = item
        try:
            df = fdr.DataReader(code, s, e)
            if df is not None and len(df) > 0:
                return label, df[["Close"]].copy()
        except Exception:
            pass
        return label, pd.DataFrame()

    result = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for label, df in pool.map(_fetch_one, codes.items()):
            result[label] = df

    # ECOS API: 한국 거시지표 (병렬)
    ecos_start_d = start.strftime("%Y%m%d")
    ecos_end_d = end.strftime("%Y%m%d")
    ecos_start_m = start.strftime("%Y%m")
    ecos_end_m = end.strftime("%Y%m")

    ecos_items = {
        "KR10Y": ("817Y002", "010210000", "D", ecos_start_d, ecos_end_d),    # 국고채 10년물
        "KR2Y": ("817Y002", "010195000", "D", ecos_start_d, ecos_end_d),     # 국고채 2년물
        "외국인(유가)": ("802Y001", "0030000", "D", ecos_start_d, ecos_end_d), # 외국인 순매수 유가증권
        "외국인(코스닥)": ("802Y001", "0113000", "D", ecos_start_d, ecos_end_d), # 외국인 순매수 코스닥
        "CPI": ("901Y009", "0", "M", (start - timedelta(days=400)).strftime("%Y%m"), ecos_end_m),  # 소비자물가지수 (YoY용 13개월+)
    }

    def _fetch_ecos_one(item):
        label, args = item
        return label, _fetch_ecos(*args)

    with ThreadPoolExecutor(max_workers=5) as pool:
        for label, df in pool.map(_fetch_ecos_one, ecos_items.items()):
            result[label] = df

    # FRED: 미국 CPI (YoY 계산용으로 13개월+ 확보)
    fred_start = (start - timedelta(days=400)).strftime("%Y-%m-%d")
    fred_end = end.strftime("%Y-%m-%d")
    result["US_CPI"] = _fetch_fred_csv("CPIAUCSL", fred_start, fred_end)

    # ECOS 100대 지표 내부 API: M1
    result["M1"] = _fetch_ecos_key100("K002")

    # 장단기 금리차 (10Y - 2Y) 계산
    for prefix, k10, k2 in [("KR", "KR10Y", "KR2Y"), ("US", "US10Y", "US2Y")]:
        df10 = result.get(k10, pd.DataFrame())
        df2 = result.get(k2, pd.DataFrame())
        if not df10.empty and not df2.empty:
            spread = df10[["Close"]].join(df2[["Close"]], lsuffix="_10", rsuffix="_2", how="inner")
            spread["Close"] = spread["Close_10"] - spread["Close_2"]
            result[f"{prefix}_spread"] = spread[["Close"]]

    # 외국인 순매수 누적
    for key in ["외국인(유가)", "외국인(코스닥)"]:
        df = result.get(key, pd.DataFrame())
        if not df.empty:
            result[f"{key}_cum"] = pd.DataFrame({"Close": df["Close"].cumsum()}, index=df.index)

    return result


def _echarts_indicator(df, title: str, height: int = 280, decimal: int = 2, unit: str = "", key: str = ""):
    """ECharts 기반 시장 지표 라인 차트 (주가 차트 스타일)"""
    from streamlit_echarts import st_echarts

    if df.empty:
        st.info(f"{title} 데이터를 불러올 수 없습니다.")
        return

    _df = df.reset_index()
    _df.columns = ["날짜", "값"]
    _df = _df.dropna(subset=["값"])
    if _df.empty:
        st.info(f"{title} 데이터를 불러올 수 없습니다.")
        return
    dates = [d.strftime("%Y-%m-%d") for d in _df["날짜"]]
    values = [round(float(v), decimal) for v in _df["값"]]

    _last = values[-1]
    _first = values[0]
    _chg_pct = (_last / _first - 1) * 100 if _first else 0

    # y축 범위: min~max에 5% 여유
    y_min = min(values)
    y_max = max(values)
    margin = (y_max - y_min) * 0.05 if y_max != y_min else abs(y_max) * 0.02
    y_lo = round(y_min - margin, decimal)
    y_hi = round(y_max + margin, decimal)

    # 상승/하락 색상
    is_up = _last >= _first
    line_color = "#ef5350" if is_up else "#42a5f5"       # 빨강=상승, 파랑=하락
    area_top   = "rgba(239,83,80,0.15)" if is_up else "rgba(66,165,245,0.15)"

    option = {
        "animation": False,
        "title": {
            "text": title,
            "subtext": f"현재 {unit}{_last:,.{decimal}f}  |  변동 {_chg_pct:+.2f}%",
            "left": "center",
            "textStyle": {"color": "#ccc", "fontSize": 14, "fontWeight": "bold"},
            "subtextStyle": {"color": "#888", "fontSize": 11},
        },
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": "rgba(20,20,30,0.9)",
            "borderColor": "#555",
            "textStyle": {"color": "#eee", "fontSize": 12},
            "formatter": None,  # 기본 포맷 사용
        },
        "grid": {
            "left": "12%", "right": "5%", "top": "22%", "bottom": "15%",
        },
        "xAxis": {
            "type": "category",
            "data": dates,
            "axisLine": {"lineStyle": {"color": "#444"}},
            "axisLabel": {"color": "#888", "fontSize": 10},
            "axisTick": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "min": y_lo,
            "max": y_hi,
            "splitNumber": 5,
            "axisLine": {"show": False},
            "axisLabel": {"color": "#888", "fontSize": 10},
            "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.06)"}},
        },
        "dataZoom": [
            {
                "type": "inside",
                "start": 0, "end": 100,
            },
        ],
        "series": [
            {
                "type": "line",
                "data": values,
                "symbol": "none",
                "lineStyle": {"color": line_color, "width": 2},
                "areaStyle": {
                    "color": {
                        "type": "linear",
                        "x": 0, "y": 0, "x2": 0, "y2": 1,
                        "colorStops": [
                            {"offset": 0, "color": area_top},
                            {"offset": 1, "color": "rgba(0,0,0,0)"},
                        ],
                    },
                },
                "markLine": {
                    "silent": True,
                    "symbol": "none",
                    "data": [
                        {
                            "yAxis": _last,
                            "lineStyle": {"color": line_color, "type": "dashed", "width": 1},
                            "label": {
                                "show": True,
                                "position": "insideEndTop",
                                "formatter": f"{unit}{_last:,.{decimal}f}",
                                "color": line_color,
                                "fontSize": 11,
                            },
                        }
                    ],
                },
            }
        ],
    }

    _key = key or f"mkt_{title.replace(' ', '_')}"
    st_echarts(options=option, height=f"{height}px", key=_key)


def _echarts_cpi(df, title: str, height: int = 320, key: str = ""):
    """CPI 전용 차트: 막대(지수) + 꺾은선(YoY %)"""
    from streamlit_echarts import st_echarts

    if df.empty:
        st.info(f"{title} 데이터를 불러올 수 없습니다.")
        return

    _df = df.reset_index()
    _df.columns = ["날짜", "값"]
    _df = _df.dropna(subset=["값"])
    if len(_df) < 13:
        _echarts_indicator(df, title, height=height, decimal=1, key=key)
        return

    dates = [d.strftime("%Y-%m") for d in _df["날짜"]]
    values = [round(float(v), 1) for v in _df["값"]]

    # YoY 계산 (12개월 전 대비)
    yoy = [None] * 12
    for i in range(12, len(values)):
        prev = values[i - 12]
        if prev and prev != 0:
            yoy.append(round((values[i] / prev - 1) * 100, 2))
        else:
            yoy.append(None)

    _last_val = values[-1]
    _last_yoy = yoy[-1] if yoy[-1] is not None else 0

    # y축 범위
    v_min, v_max = min(values), max(values)
    v_margin = (v_max - v_min) * 0.05
    yoy_valid = [y for y in yoy if y is not None]
    y_min = min(yoy_valid) if yoy_valid else 0
    y_max = max(yoy_valid) if yoy_valid else 5
    y_margin = (y_max - y_min) * 0.1

    option = {
        "animation": False,
        "title": {
            "text": title,
            "subtext": f"지수 {_last_val:.1f}  |  YoY {_last_yoy:+.2f}%",
            "left": "center",
            "textStyle": {"color": "#ccc", "fontSize": 14, "fontWeight": "bold"},
            "subtextStyle": {"color": "#888", "fontSize": 11},
        },
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": "rgba(20,20,30,0.9)",
            "borderColor": "#555",
            "textStyle": {"color": "#eee", "fontSize": 12},
        },
        "legend": {
            "data": ["CPI 지수", "YoY %"],
            "top": "8%",
            "textStyle": {"color": "#888", "fontSize": 10},
        },
        "grid": {
            "left": "10%", "right": "10%", "top": "25%", "bottom": "15%",
        },
        "xAxis": {
            "type": "category",
            "data": dates,
            "axisLine": {"lineStyle": {"color": "#444"}},
            "axisLabel": {"color": "#888", "fontSize": 10},
            "axisTick": {"show": False},
        },
        "yAxis": [
            {
                "type": "value",
                "name": "지수",
                "min": round(v_min - v_margin, 1),
                "max": round(v_max + v_margin, 1),
                "axisLine": {"show": False},
                "axisLabel": {"color": "#888", "fontSize": 10},
                "splitLine": {"lineStyle": {"color": "rgba(255,255,255,0.06)"}},
            },
            {
                "type": "value",
                "name": "YoY %",
                "min": round(y_min - y_margin, 1),
                "max": round(y_max + y_margin, 1),
                "axisLine": {"show": False},
                "axisLabel": {"color": "#ff9800", "fontSize": 10, "formatter": "{value}%"},
                "splitLine": {"show": False},
            },
        ],
        "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
        "series": [
            {
                "name": "CPI 지수",
                "type": "bar",
                "data": values,
                "yAxisIndex": 0,
                "itemStyle": {"color": "rgba(66,165,245,0.5)"},
                "barMaxWidth": 20,
            },
            {
                "name": "YoY %",
                "type": "line",
                "data": yoy,
                "yAxisIndex": 1,
                "symbol": "circle",
                "symbolSize": 4,
                "lineStyle": {"color": "#ff9800", "width": 2},
                "itemStyle": {"color": "#ff9800"},
            },
        ],
    }

    st_echarts(options=option, height=f"{height}px", key=key)


def show_market_indicators():
    st.title("🌍 시장 지표")

    _period = st.select_slider(
        "조회 기간",
        options=[30, 60, 90, 180, 365],
        value=90,
        format_func=lambda x: f"{x}일",
        key="mkt_ind_period",
    )

    # 한 번에 모든 데이터 로드
    with st.spinner("시장 데이터 로딩 중..."):
        data = _fetch_all_indicators(_period)

    _now = datetime.now().strftime("%Y-%m-%d %H:%M")
    st.caption(f"주요 거시경제 지표 추이  ·  조회 {_now}")

    # ── 1. 주요 지수 ──
    st.subheader("주요 지수")
    ix_c1, ix_c2 = st.columns(2)
    with ix_c1:
        _echarts_indicator(data.get("코스피", pd.DataFrame()), "코스피", key=f"mi_kospi_{_period}")
        _echarts_indicator(data.get("코스닥", pd.DataFrame()), "코스닥", key=f"mi_kosdaq_{_period}")
    with ix_c2:
        _echarts_indicator(data.get("S&P500", pd.DataFrame()), "S&P500", key=f"mi_sp500_{_period}")
        _echarts_indicator(data.get("나스닥", pd.DataFrame()), "나스닥", key=f"mi_nasdaq_{_period}")

    st.divider()

    # ── 2. 외국인 수급 ──
    st.subheader("외국인 수급")
    sup_c1, sup_c2 = st.columns(2)
    with sup_c1:
        _echarts_indicator(data.get("외국인(유가)", pd.DataFrame()), "외국인 순매수 - 유가증권 (일별, 억원)", decimal=0, key=f"mi_frgn_kospi_{_period}")
        _echarts_indicator(data.get("외국인(유가)_cum", pd.DataFrame()), "외국인 누적 순매수 - 유가증권 (억원)", decimal=0, key=f"mi_frgn_kospi_cum_{_period}")
    with sup_c2:
        _echarts_indicator(data.get("외국인(코스닥)", pd.DataFrame()), "외국인 순매수 - 코스닥 (일별, 억원)", decimal=0, key=f"mi_frgn_kosdaq_{_period}")
        _echarts_indicator(data.get("외국인(코스닥)_cum", pd.DataFrame()), "외국인 누적 순매수 - 코스닥 (억원)", decimal=0, key=f"mi_frgn_kosdaq_cum_{_period}")

    st.divider()

    # ── 3. 금리 ──
    st.subheader("금리")
    rate_c1, rate_c2 = st.columns(2)
    with rate_c1:
        _echarts_indicator(data.get("KR10Y", pd.DataFrame()), "한국 국고채 10년물", decimal=3, key=f"mi_kr10y_{_period}")
        _echarts_indicator(data.get("KR2Y", pd.DataFrame()), "한국 국고채 2년물", decimal=3, key=f"mi_kr2y_{_period}")
        df_kr_sp = data.get("KR_spread", pd.DataFrame())
        _echarts_indicator(df_kr_sp, "한국 장단기 금리차 (10Y-2Y)", decimal=3, key=f"mi_kr_spread_{_period}")
        if not df_kr_sp.empty:
            _sp = float(df_kr_sp.iloc[-1]["Close"])
            st.caption(f"{'정상 (양수)' if _sp > 0 else '역전 (경기침체 경고)'}")
    with rate_c2:
        _echarts_indicator(data.get("US10Y", pd.DataFrame()), "미국 국채 10년물", decimal=3, key=f"mi_us10y_{_period}")
        _echarts_indicator(data.get("US2Y", pd.DataFrame()), "미국 국채 2년물", decimal=3, key=f"mi_us2y_{_period}")
        df_us_sp = data.get("US_spread", pd.DataFrame())
        _echarts_indicator(df_us_sp, "미국 장단기 금리차 (10Y-2Y)", decimal=3, key=f"mi_us_spread_{_period}")
        if not df_us_sp.empty:
            _sp = float(df_us_sp.iloc[-1]["Close"])
            st.caption(f"{'정상 (양수)' if _sp > 0 else '역전 (경기침체 경고)'}")

    st.divider()

    # ── 4. 변동성 ──
    st.subheader("변동성")
    vol_c1, vol_c2 = st.columns(2)
    with vol_c1:
        df_vix = data.get("VIX", pd.DataFrame())
        _echarts_indicator(df_vix, "VIX (S&P500 변동성)", key=f"mi_vix_{_period}")
        if not df_vix.empty:
            _v = float(df_vix.iloc[-1]["Close"])
            _level = "극도 공포" if _v > 30 else "공포" if _v > 20 else "보통" if _v > 15 else "탐욕"
            st.caption(f"현재 수준: {_level}")

    st.divider()

    # ── 5. 통화량 ──
    st.subheader("통화량")
    m_c1, m_c2 = st.columns(2)
    with m_c1:
        _echarts_indicator(data.get("M1", pd.DataFrame()), "M1 협의통화 (십억원)", decimal=1, key=f"mi_m1_{_period}")

    st.divider()

    # ── 6. 환율 ──
    st.subheader("환율")
    fx_c1, fx_c2 = st.columns(2)
    with fx_c1:
        _echarts_indicator(data.get("USD/KRW", pd.DataFrame()), "USD/KRW (원/달러)", key=f"mi_usdkrw_{_period}")
    with fx_c2:
        _echarts_indicator(data.get("DXY", pd.DataFrame()), "달러 인덱스 (DXY)", key=f"mi_dxy_{_period}")

    st.divider()

    # ── 7. 물가 ──
    st.subheader("물가")
    cpi_c1, cpi_c2 = st.columns(2)
    with cpi_c1:
        _echarts_cpi(data.get("CPI", pd.DataFrame()), "한국 소비자물가지수 (CPI)", key=f"mi_cpi_{_period}")
    with cpi_c2:
        _echarts_cpi(data.get("US_CPI", pd.DataFrame()), "미국 소비자물가지수 (CPI)", key=f"mi_us_cpi_{_period}")

    st.divider()

    # ── 8. 원자재 ──
    st.subheader("원자재")
    cmd_c1, cmd_c2 = st.columns(2)
    with cmd_c1:
        _echarts_indicator(data.get("WTI", pd.DataFrame()), "WTI 원유 ($/bbl)", unit="$", key=f"mi_wti_{_period}")
        _echarts_indicator(data.get("Gold", pd.DataFrame()), "금 ($/oz)", unit="$", key=f"mi_gold_{_period}")
        _echarts_indicator(data.get("Copper", pd.DataFrame()), "구리 ($/lb)", unit="$", key=f"mi_copper_{_period}")
    with cmd_c2:
        _echarts_indicator(data.get("Silver", pd.DataFrame()), "은 ($/oz)", unit="$", key=f"mi_silver_{_period}")
        _echarts_indicator(data.get("NatGas", pd.DataFrame()), "천연가스 ($/MMBtu)", unit="$", key=f"mi_natgas_{_period}")


# ══════════════════════════════════════════════════════════
# SEPA Scanner 렌더링
# ══════════════════════════════════════════════════════════

_VCP_SHOW_COLS = [
    "종목코드", "종목명", "RS Score", "RS순위(%)",
    "최종피벗", "직전피벗", "현재가", "피벗거리(%)",
    "수축(T)", "수축강도(%)", "베이스기간(일)", "거래량비율(%)",
    "ATR(20)", "ATR(%)",
]
_VCP_FMT = {
    "RS Score":      "{:+.2f}",
    "RS순위(%)":     "{:.1f}%",
    "최종피벗":      "{:,.0f}",
    "직전피벗":      "{:,.0f}",
    "현재가":        "{:,.0f}",
    "피벗거리(%)":   "{:.2f}%",
    "수축강도(%)":   "{:.1f}%",
    "거래량비율(%)": "{:.1f}%",
    "ATR(20)":       "{:,.0f}",
    "ATR(%)":        "{:.2f}%",
}
_PS_PERIOD = 60  # SEPA Scanner 고정 기간


def _show_vcp_table(market: str, auto_calc: bool = True):
    """VCP 패턴 테이블 렌더링"""
    _is_us    = market in ("NASDAQ", "NYSE")
    cache_key = f"vcp_patterns_{market}_{_PS_PERIOD}"
    vcp_file_time = get_vcp_pattern_cache_info(market, _PS_PERIOD)

    _force = st.session_state.get(f"_force_rescan_{market}", False)

    if _force:
        st.session_state.pop(f"_force_rescan_{market}", None)
        # 강제 재스캔: 캐시 무시하고 새로 계산
        n_cands = {"KOSPI": "약 380종목", "KOSDAQ": "약 730종목", "NASDAQ": "약 3500종목", "NYSE": "약 2000종목"}.get(market, "")
        status  = st.empty()
        bar     = st.progress(0)
        status.info(f"⏳ {market} 강제 재스캔 중... ({n_cands})")

        def _cb_force(done, total):
            pct = int(done / total * 100)
            bar.progress(pct)
            status.info(f"⏳ {market} 재스캔 중... {done}/{total}종목 ({pct}%)")

        try:
            df = scan_vcp_patterns(
                market=market, period=_PS_PERIOD,
                use_cache=False, progress_cb=_cb_force,
            )
            st.session_state[cache_key] = df
        except Exception as e:
            status.error(f"{market} 재스캔 실패: {e}")
            bar.empty()
            return
        finally:
            bar.empty()
            status.empty()

    if cache_key not in st.session_state:
        if vcp_file_time:
            df = scan_vcp_patterns(market=market, period=_PS_PERIOD, use_cache=True)
            st.session_state[cache_key] = df
            st.rerun()
        elif not auto_calc:
            total_msg = {
                "NASDAQ": "약 3500종목 (30~50분 소요)",
                "NYSE":   "약 2000종목 (20~30분 소요)",
            }.get(market, "")
            st.info(f"{market} VCP 스캔이 아직 실행되지 않았습니다. {total_msg}")
            if st.button(f"🚀 {market} VCP 스캔 시작", key=f"vcp_calc_btn_{market}"):
                status = st.empty()
                bar    = st.progress(0)
                status.info(f"⏳ {market} VCP 스캔 중...")

                def _cb(done, total):
                    pct = int(done / total * 100)
                    bar.progress(pct)
                    status.info(f"⏳ {market} 스캔 중... {done}/{total}종목 ({pct}%)")

                try:
                    df = scan_vcp_patterns(
                        market=market, period=_PS_PERIOD,
                        use_cache=False, progress_cb=_cb,
                    )
                    st.session_state[cache_key] = df
                except Exception as e:
                    status.error(f"{market} 스캔 실패: {e}")
                    bar.empty()
                    return
                finally:
                    bar.empty()
                    status.empty()
                st.rerun()
            return
        else:
            n_cands = "약 380종목" if market == "KOSPI" else "약 730종목"
            status  = st.empty()
            bar     = st.progress(0)
            status.info(f"⏳ {market} VCP 스캔 중... (RS 상위 40%, {n_cands})")

            def _cb(done, total):
                pct = int(done / total * 100)
                bar.progress(pct)
                status.info(f"⏳ {market} 스캔 중... {done}/{total}종목 ({pct}%)")

            try:
                df = scan_vcp_patterns(
                    market=market, period=_PS_PERIOD,
                    use_cache=False, progress_cb=_cb,
                )
                st.session_state[cache_key] = df
            except Exception as e:
                status.error(f"{market} 스캔 실패: {e}")
                bar.empty()
                return
            finally:
                bar.empty()
                status.empty()
            st.rerun()

    df_vcp = st.session_state.get(cache_key)

    cache_time = get_vcp_pattern_cache_info(market, _PS_PERIOD)
    st.caption(
        f"📅 저장: {cache_time or '방금 계산'}  ·  {len(df_vcp) if df_vcp is not None else 0}개  ·  행 클릭 시 차트로 이동"
    )

    if df_vcp is None or df_vcp.empty:
        st.info("VCP 패턴 조건을 만족하는 종목이 없습니다.")
        return

    # 미국장은 달러 포맷
    vcp_fmt = dict(_VCP_FMT)
    if _is_us:
        vcp_fmt["직전피벗"]  = "${:,.2f}"
        vcp_fmt["현재가"]   = "${:,.2f}"
        vcp_fmt["최종피벗"] = "${:,.2f}"
        vcp_fmt["ATR(20)"]  = "${:,.2f}"

    avail_cols = [c for c in _VCP_SHOW_COLS if c in df_vcp.columns]
    display_df = df_vcp[avail_cols].copy()

    # 미국장: 종목명 다음에 티커 컬럼 추가
    if _is_us and "종목코드" in display_df.columns and "종목명" in display_df.columns:
        display_df.insert(
            display_df.columns.get_loc("종목명") + 1,
            "티커",
            display_df["종목코드"],
        )

    _vcp_n = len(display_df)
    _vcp_height = 250 if _vcp_n <= 5 else (350 if _vcp_n <= 10 else 450)
    _vcp_color_map = {"RS Score": "red_positive", "피벗거리(%)": "red_positive"}
    result = _aggrid(
        display_df,
        key=f"tbl_vcp_{market}_{_PS_PERIOD}",
        height=_vcp_height,
        click_nav=True,
        color_map=_vcp_color_map,
        col_widths={"티커": 90} if _is_us else {},
    )
    selected = result["selected_rows"]
    if selected is not None and len(selected) > 0:
        import pandas as pd
        row = selected.iloc[0] if isinstance(selected, pd.DataFrame) else selected[0]
        ticker = row.get("종목코드", "") if isinstance(row, dict) else row.get("종목코드", "")
        st.session_state.view           = "chart"
        st.session_state.chart_ticker   = ticker
        st.session_state.chart_name     = row.get("종목명", "") if isinstance(row, dict) else row.get("종목명", "")
        st.session_state.chart_period   = _PS_PERIOD
        st.session_state.sidebar_ticker = ticker
        st.session_state.return_to_view = "pattern_scanner"
        st.session_state["ps_return_tab"] = "us" if _is_us else "kr"
        st.rerun()


def show_pattern_scanner():
    st.title("🔍 SEPA Scanner")
    st.caption("Breakout Entry (VCP / BO)  ·  RS 60일 기준 · RS 상위 40% · 2단계 조건 포함")

    st.caption("💡 매일 첫 실행 시 자동 재계산 · 당일은 캐시에서 즉시 로드")

    _ps_return_tab = st.session_state.pop("ps_return_tab", "kr")
    if _ps_return_tab == "us":
        tab_us, tab_kr = st.tabs(["🇺🇸 미국", "🇰🇷 한국"])
    else:
        tab_kr, tab_us = st.tabs(["🇰🇷 한국", "🇺🇸 미국"])

    with tab_kr:
        if st.button("🔄 강제 재스캔", key="rescan_kr", help="한국장 전체 재스캔 (새 캐시로 덮어쓰기)"):
            for m in ("KOSPI", "KOSDAQ"):
                st.session_state[f"_force_rescan_{m}"] = True
                st.session_state.pop(f"vcp_patterns_{m}_{_PS_PERIOD}", None)
            st.rerun()
        st.divider()
        st.markdown("#### 📊 KOSPI")
        _show_vcp_table("KOSPI")
        st.divider()
        st.markdown("#### 📊 KOSDAQ")
        _show_vcp_table("KOSDAQ")

    with tab_us:
        if st.button("🔄 강제 재스캔", key="rescan_us", help="미국장 전체 재스캔 (새 캐시로 덮어쓰기)"):
            for m in ("NASDAQ", "NYSE"):
                st.session_state[f"_force_rescan_{m}"] = True
                st.session_state.pop(f"vcp_patterns_{m}_{_PS_PERIOD}", None)
            st.rerun()
        st.divider()
        st.markdown("#### 📊 NASDAQ")
        _show_vcp_table("NASDAQ", auto_calc=False)
        st.divider()
        st.markdown("#### 📊 NYSE")
        _show_vcp_table("NYSE", auto_calc=False)


# ══════════════════════════════════════════════════════════
# Short Scanner 렌더링
# ══════════════════════════════════════════════════════════

def show_short_scanner():
    st.title("🔻 Short Scanner")
    st.caption("Stage 4 하락 추세 종목 + 인버스 ETF 매핑  ·  200일선 하방 · MA 역배열")

    col_ref, col_info, _ = st.columns([1, 4, 3])
    with col_ref:
        if st.button("🔄 강제 재스캔", key="short_rescan"):
            today = datetime.now().strftime("%Y%m%d")
            for f in (Path(__file__).parent / "cache").glob(f"short_*{today}.json"):
                f.unlink(missing_ok=True)
            for k in [k for k in st.session_state if k.startswith("short_scan_")]:
                del st.session_state[k]
            st.rerun()
    with col_info:
        cache_time = get_short_cache_info()
        if cache_time:
            st.caption(f"캐시: {cache_time}")
        else:
            st.caption("캐시 없음 — 아래에서 스캔 시작")

    st.divider()

    cache_key = "short_scan_result"

    if cache_key not in st.session_state:
        status = st.empty()
        bar = st.progress(0)
        status.info("⏳ Stage 4 종목 스캔 중...")

        def _cb(done, total):
            pct = int(done / total * 100)
            bar.progress(pct)
            status.info(f"⏳ 스캔 중... {done}/{total} ({pct}%)")

        try:
            df = scan_short_candidates(use_cache=True, progress_cb=_cb)
            st.session_state[cache_key] = df
        except Exception as e:
            status.error(f"스캔 실패: {e}")
            bar.empty()
            return
        finally:
            bar.empty()
            status.empty()

    df = st.session_state[cache_key]

    if df is None or df.empty:
        st.success("Stage 4 진입 종목이 없습니다. (모든 대상 종목이 200일선 위)")
        return

    st.markdown(f"**{len(df)}개 종목** Stage 4 감지")

    # 테이블 표시
    show_cols = ["종목코드", "종목명", "상태", "현재가", "200일선대비(%)", "고점대비(%)", "돌파경과(일)", "거래량비율(%)", "인버스ETF"]
    df_show = df[show_cols].copy()

    result = _aggrid(
        df_show,
        key="short_grid",
        height=min(400, 60 + len(df_show) * 35),
        click_nav=True,
        col_widths={"종목명": 120, "인버스ETF": 160, "현재가": 100},
        price_cols=["현재가"],
        pct_cols=["200일선대비(%)", "고점대비(%)", "거래량비율(%)"],
    )

    # 행 클릭 → 원본 종목 차트 이동
    selected = result["selected_rows"] if result else None
    if selected is not None and len(selected) > 0:
        row = selected[0]
        st.session_state.view = "chart"
        st.session_state.chart_ticker = row["종목코드"]
        st.session_state.chart_name = row.get("종목명", "")
        st.session_state.chart_period = 60
        st.session_state.sidebar_ticker = row["종목코드"]
        st.session_state.return_to_view = "short_scanner"
        st.rerun()

    st.divider()

    # 인버스 ETF 전체 매핑 (클릭 시 차트 이동)
    st.subheader("📋 인버스 ETF 매핑")
    st.caption("행 클릭 시 인버스 ETF 차트로 이동")
    ref_rows = []
    for ticker, info in INVERSE_ETF_MAP.items():
        for inv_ticker, inv_name in info["inverse"]:
            ref_rows.append({
                "종목코드": inv_ticker,
                "종목명": inv_name,
                "원본종목": f"{ticker} ({info['name']})",
                "타입": "지수 인버스" if ticker in ("SPY", "QQQ") else "개별 인버스",
            })
    df_ref = pd.DataFrame(ref_rows)
    ref_result = _aggrid(
        df_ref,
        key="short_etf_ref",
        height=min(500, 60 + len(df_ref) * 35),
        click_nav=True,
        col_widths={"종목코드": 100, "종목명": 250, "원본종목": 180, "타입": 120},
    )
    ref_selected = ref_result["selected_rows"] if ref_result else None
    if ref_selected is not None and len(ref_selected) > 0:
        row = ref_selected[0]
        st.session_state.view = "chart"
        st.session_state.chart_ticker = row["종목코드"]
        st.session_state.chart_name = row.get("종목명", "")
        st.session_state.chart_period = 60
        st.session_state.sidebar_ticker = row["종목코드"]
        st.session_state.return_to_view = "short_scanner"
        st.rerun()


# ══════════════════════════════════════════════════════════
# 포트폴리오 렌더링
# ══════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def _fetch_current_price(ticker: str) -> float:
    """현재가 조회 (최근 5일 중 마지막 종가, 5분 캐시)"""
    try:
        from datetime import timedelta
        end   = datetime.now()
        start = end - timedelta(days=10)
        df = fdr.DataReader(ticker, start, end)
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def _color_pnl(val):
    try:
        # 문자열인 경우 첫 번째 숫자만 추출 (예: "-5.20% (목표:-7.00%)")
        import re
        num = float(re.search(r"[+-]?\d+\.?\d*", str(val)).group()) if isinstance(val, str) else float(val)
        return "color: #1a5ecc; font-weight:bold" if num >= 0 else "color: #c0392b; font-weight:bold"
    except Exception:
        return ""


def _render_equity_curve(source_df=None, date_col="날짜"):
    """누적 수익 곡선. source_df 없으면 거래별(get_equity_curve) 사용."""
    import altair as alt

    if source_df is not None:
        # 손익 컬럼 자동 감지
        _pnl_c = "실현손익($)" if "실현손익($)" in source_df.columns else "실현손익(원)"
        if _pnl_c not in source_df.columns:
            st.info("데이터가 없습니다.")
            return
        raw = source_df[[date_col, _pnl_c]].copy()
        raw = raw.groupby(date_col, as_index=False)[_pnl_c].sum()
        raw = raw.sort_values(date_col).reset_index(drop=True)
        raw["누적손익(원)"] = raw[_pnl_c].cumsum()
        first_dt   = pd.to_datetime(raw[date_col].iloc[0])
        start_date = first_dt.replace(day=1).strftime("%Y-%m-%d")
        start_row  = pd.DataFrame([{date_col: start_date, "누적손익(원)": 0}])
        eq_df = pd.concat([start_row, raw[[date_col, "누적손익(원)"]]], ignore_index=True)
        eq_df = eq_df.rename(columns={date_col: "날짜"})
    else:
        eq_df = get_equity_curve()

    if eq_df.empty:
        st.info("데이터가 없습니다.")
        return

    eq_df["날짜_str"] = pd.to_datetime(eq_df["날짜"]).dt.strftime("%Y-%m-%d")
    eq_df["금액표시"] = eq_df["누적손익(원)"].apply(lambda v: f"{v:+,.0f}원")
    color = "#c0392b" if eq_df["누적손익(원)"].iloc[-1] >= 0 else "#1a5ecc"

    base = alt.Chart(eq_df).encode(
        x=alt.X("날짜_str:O", title="날짜", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("누적손익(원):Q", title="누적 실현손익 (원)"),
        tooltip=[
            alt.Tooltip("날짜_str:N", title="날짜"),
            alt.Tooltip("누적손익(원):Q", title="누적손익(원)", format="+,.0f"),
        ],
    )
    line   = base.mark_line(color=color, strokeWidth=2)
    points = base.mark_point(color=color, size=60, filled=True)
    labels = base.mark_text(align="left", dx=6, dy=-8, fontSize=10, color="#e0e0e0").encode(
        text="금액표시:N"
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color="gray", strokeDash=[4, 4]
    ).encode(y="y:Q")
    st.altair_chart(line + points + labels + zero, use_container_width=True)


def _color_monthly_pnl(val):
    try:
        return "color: #c0392b; font-weight:bold" if float(val) >= 0 else "color: #1a5ecc; font-weight:bold"
    except Exception:
        return ""


def _render_monthly_performance(source_df=None, date_col="날짜"):
    """월별 성과표 + 누적 그래프. source_df 없으면 거래별(get_monthly_performance) 사용."""
    import altair as alt

    if source_df is not None:
        _pnl_c2 = "실현손익($)" if "실현손익($)" in source_df.columns else "실현손익(원)"
        raw = source_df[[date_col, _pnl_c2, "수익률(%)"]].copy()
        raw = raw.rename(columns={_pnl_c2: "실현손익(원)"})
        raw["월"] = pd.to_datetime(raw[date_col]).dt.to_period("M").astype(str)
        rows = []
        for month, grp in raw.groupby("월"):
            n    = len(grp)
            wins = (grp["수익률(%)"] > 0).sum()
            rows.append({
                "월":            month,
                "거래수":        n,
                "승률(%)":       round(wins / n * 100, 1),
                "평균수익률(%)":  round(grp["수익률(%)"].mean(), 2),
                "총실현손익(원)": int(grp["실현손익(원)"].sum()),
            })
        month_df = pd.DataFrame(rows).sort_values("월").reset_index(drop=True)
        if not month_df.empty:
            first_year = month_df["월"].iloc[0][:4]
            last_month = month_df["월"].iloc[-1]
            all_months = pd.period_range(f"{first_year}-01", last_month, freq="M").astype(str)
            month_df = (
                pd.DataFrame({"월": all_months})
                .merge(month_df, on="월", how="left")
                .fillna({"거래수": 0, "총실현손익(원)": 0})
            )
            month_df["누적손익(원)"] = month_df["총실현손익(원)"].cumsum().astype(int)
        month_df = month_df.sort_values("월", ascending=False).reset_index(drop=True)
    else:
        month_df = get_monthly_performance()

    if month_df.empty:
        st.info("데이터가 없습니다.")
        return

    # 표 (최신월 순)
    disp_df = month_df.copy()
    month_fmt = {
        "거래수":          "{:.0f}",
        "승률(%)":         "{:.1f}%",
        "평균수익률(%)":    "{:+.2f}%",
        "총실현손익(원)":   "{:+,.0f}",
        "누적손익(원)":     "{:+,.0f}",
    }
    show_cols = [c for c in ["월", "거래수", "승률(%)", "평균수익률(%)", "총실현손익(원)", "누적손익(원)"] if c in disp_df.columns]
    _monthly_color_map = {c: "red_positive" for c in ["총실현손익(원)", "평균수익률(%)", "누적손익(원)"] if c in show_cols}
    _monthly_n = len(disp_df[show_cols])
    _monthly_height = 250 if _monthly_n <= 5 else (350 if _monthly_n <= 10 else 450)
    _aggrid(disp_df[show_cols], key=f"monthly_perf_{id(disp_df)}", height=_monthly_height,
            click_nav=False, color_map=_monthly_color_map)

    # 월별 누적손익 꺾은선 그래프 (오름차순)
    chart_df = month_df.sort_values("월").copy()
    chart_df["금액표시"] = chart_df["누적손익(원)"].apply(lambda v: f"{v:+,.0f}원")
    color = "#c0392b" if chart_df["누적손익(원)"].iloc[-1] >= 0 else "#1a5ecc"

    base = alt.Chart(chart_df).encode(
        x=alt.X("월:O", title="월", axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("누적손익(원):Q", title="누적 실현손익 (원)"),
        tooltip=[
            alt.Tooltip("월:O", title="월"),
            alt.Tooltip("누적손익(원):Q", title="누적손익(원)", format="+,.0f"),
            alt.Tooltip("총실현손익(원):Q", title="당월손익(원)", format="+,.0f"),
        ],
    )
    line   = base.mark_line(color=color, strokeWidth=2)
    points = base.mark_point(color=color, size=60, filled=True)
    labels = base.mark_text(align="left", dx=6, dy=-8, fontSize=10, color="#e0e0e0").encode(
        text="금액표시:N"
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="gray", strokeDash=[4, 4]).encode(y="y:Q")
    st.altair_chart(line + points + labels + zero, use_container_width=True)


def _render_return_distribution(df, label: str, prefix: str):
    """수익률 분포도 — 가로축 수익률(%), 세로축 빈도(점)"""
    if "수익률(%)" not in df.columns or len(df) == 0:
        return
    _ret_vals = df["수익률(%)"].dropna()
    if len(_ret_vals) == 0:
        return

    from streamlit_echarts import st_echarts as _st_ec
    import numpy as _np

    st.divider()
    st.subheader(f"수익률 분포 ({label})")

    # 5% 구간별 히스토그램 — 실제 분포 형태
    import plotly.graph_objects as go
    import numpy as _np
    import math

    _mean = float(_ret_vals.mean())
    _std = float(_ret_vals.std()) if len(_ret_vals) > 1 else 1.0
    _bin_size = 5
    _min_edge = math.floor(_ret_vals.min() / _bin_size) * _bin_size
    _max_edge = math.ceil(_ret_vals.max() / _bin_size) * _bin_size
    _edges = list(range(_min_edge, _max_edge + _bin_size, _bin_size))
    _counts = [0] * (len(_edges) - 1)
    for ret in _ret_vals.values:
        for i in range(len(_edges) - 1):
            if _edges[i] <= ret < _edges[i + 1]:
                _counts[i] += 1
                break
        else:
            _counts[-1] += 1
    _labels = [f"{_edges[i]}~{_edges[i+1]}%" for i in range(len(_counts))]
    _bar_colors = ["#D92B2B" if (_edges[i] + _edges[i+1]) / 2 >= 0 else "#1A5ECC" for i in range(len(_counts))]
    _max_freq = max(_counts) if _counts else 1

    fig = go.Figure()
    # 막대
    fig.add_trace(go.Bar(
        x=_labels, y=_counts,
        marker_color=_bar_colors,
        hovertemplate="%{x}<br>빈도: %{y}건<extra></extra>",
    ))
    # 0% 기준선
    _zero_idx = None
    for i in range(len(_edges) - 1):
        if _edges[i] <= 0 < _edges[i + 1]:
            _zero_idx = i
            break
    # 평균 표시
    fig.add_annotation(
        x=_labels[min(max(0, int((_mean - _min_edge) / _bin_size)), len(_labels) - 1)],
        y=_max_freq + 0.5,
        text=f"평균 {_mean:+.1f}%", showarrow=False,
        font=dict(color="#F39C12", size=11),
    )
    fig.update_layout(
        paper_bgcolor="#1a1a2e", plot_bgcolor="#1a1a2e",
        xaxis=dict(title="수익률(%)", color="#AAA", gridcolor="rgba(255,255,255,0.08)"),
        yaxis=dict(title="빈도", color="#AAA", gridcolor="rgba(255,255,255,0.08)", dtick=1),
        font=dict(color="#AAA"), height=300, margin=dict(l=50, r=20, t=30, b=50),
        showlegend=False, bargap=0.05,
    )
    st.plotly_chart(fig, use_container_width=True)

    _max_ret = float(_ret_vals.max())
    _min_ret = float(_ret_vals.min())
    _c1, _c2, _c3, _c4 = st.columns(4)
    _c1.metric("평균수익률", f"{_mean:+.2f}%")
    _c2.metric("표준편차", f"{_std:.2f}%")
    _c3.metric("최대", f"{_max_ret:+.2f}%")
    _c4.metric("최소", f"{_min_ret:+.2f}%")


def _show_portfolio_us():
    """미국 포트폴리오 UI (달러 기준)"""
    tab_hold, tab_pnl, tab_perf, tab_review, tab_log = st.tabs(
        ["📋 보유 현황", "📊 거래별 성과분석", "📊 종목별 성과분석", "📅 월별 리뷰", "📜 거래 이력"]
    )

    # ── 보유 현황 ─────────────────────────────
    with tab_hold:
        df_pos = get_open_positions()

        if st.button("🔄 현재가 조회", key="us_price_refresh"):
            prices = {}
            with st.spinner("현재가 조회 중..."):
                for _, row in df_pos.iterrows():
                    prices[row["종목코드"]] = _fetch_current_price(row["종목코드"])
            st.session_state["portfolio_prices_us"] = prices

        prices = st.session_state.get("portfolio_prices_us", {})

        if df_pos.empty:
            st.info("보유 중인 종목이 없습니다.")
        else:
            disp = df_pos.copy()
            disp["현재가"]    = disp["종목코드"].map(lambda t: prices.get(t, None) if prices else None)
            disp["수익률(%)"] = disp.apply(
                lambda r: round((r["현재가"] - r["평균매수가"]) / r["평균매수가"] * 100, 2)
                          if pd.notna(r["현재가"]) and r["현재가"] > 0 else None, axis=1
            )
            disp["평가금액"] = disp.apply(
                lambda r: round(r["현재가"] * r["수량"], 2) if pd.notna(r["현재가"]) and r["현재가"] > 0 else None, axis=1
            )
            disp["손절경고"] = disp.apply(
                lambda r: "⚠️ 손절선 이탈" if pd.notna(r["현재가"]) and r["현재가"] > 0 and r["현재가"] <= r["손절가"] else "", axis=1
            )

            if disp["평가금액"].notna().any():
                disp = disp.sort_values("평가금액", ascending=False)
            else:
                disp = disp.assign(_sort=disp["평균매수가"] * disp["수량"])\
                           .sort_values("_sort", ascending=False)\
                           .drop(columns=["_sort"])
            disp.index = range(1, len(disp) + 1)

            show_cols = ["종목코드", "종목명", "진입근거", "평균매수가", "수량", "손절가",
                         "현재가", "수익률(%)", "평가금액", "매수일", "경과일", "손절경고"]
            disp = disp[[c for c in show_cols if c in disp.columns]]

            _hold_n = len(disp)
            _hold_height = 250 if _hold_n <= 5 else (350 if _hold_n <= 10 else 450)

            _hold_result = _aggrid(
                disp.reset_index().rename(columns={"index": "#"}),
                key="us_portfolio_hold_table", height=_hold_height, click_nav=True,
                color_map={"수익률(%)": "blue_positive"}, price_decimals=2,
                col_widths={"#": 55, "진입근거": 90, "수량": 70, "매수일": 100,
                            "경과일": 75, "수익률(%)": 95, "손절경고": 120},
            )
            _hold_selected = _hold_result["selected_rows"]
            if _hold_selected:
                _sel_row = _hold_selected[0]
                _sel_ticker = _sel_row.get("종목코드", "")
                if _sel_ticker:
                    st.session_state["view"] = "chart"
                    st.session_state["chart_ticker"] = _sel_ticker
                    st.session_state["chart_market"] = "US"
                    st.session_state["sidebar_ticker"] = _sel_ticker
                    st.session_state["return_to_view"] = "portfolio"
                    st.rerun()

            if prices and disp["평가금액"].notna().any():
                total_cost = (df_pos["평균매수가"] * df_pos["수량"]).sum()
                total_eval = disp["평가금액"].sum()
                total_pnl_unreal = total_eval - total_cost
                total_ret  = total_pnl_unreal / total_cost * 100 if total_cost > 0 else 0
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("총 투자금액", f"${total_cost:,.2f}")
                c2.metric("총 평가금액", f"${total_eval:,.2f}")
                c3.metric("평가손익", f"${total_pnl_unreal:+,.2f}",
                          delta_color="normal" if total_pnl_unreal >= 0 else "inverse")
                c4.metric("전체 수익률", f"{total_ret:+.2f}%",
                          delta_color="normal" if total_ret >= 0 else "inverse")

        # ── 매수 입력 ──
        with st.expander("➕ 매수 입력", expanded=st.session_state.get("us_buy_expander_open", False)):
            # Ticker + 조회 (폼 외부 — 직접 입력 또는 조회로 Company Name 자동완성)
            def _on_us_ticker_search():
                _sym = st.session_state.get("us_buy_ticker", "").strip().upper()
                if _sym:
                    try:
                        import yfinance as _yf
                        _pinfo = _yf.Ticker(_sym).info
                        _pname = _pinfo.get("longName") or _pinfo.get("shortName") or _sym
                    except Exception:
                        _pname = _sym
                    st.session_state["us_buy_name"] = _pname
                st.session_state["us_buy_expander_open"] = True

            _t_col, _s_col, _n_col = st.columns([2, 1, 3])
            _t_col.text_input("Ticker", key="us_buy_ticker",
                              placeholder="TSLA")
            _s_col.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
            _s_col.button("🔍 조회", on_click=_on_us_ticker_search, key="us_ticker_search_btn",
                          help="Ticker 입력 후 클릭하면 Company Name 자동완성")
            _n_col.text_input("Company Name", key="us_buy_name",
                              placeholder="Tesla, Inc.")

            def _on_us_reason_change():
                st.session_state["us_buy_expander_open"] = True
            _us_r_col, _ = st.columns([1, 2])
            _us_r_col.selectbox("진입근거", ["PB", "HB", "BO"],
                                key="us_buy_reason_type", on_change=_on_us_reason_change)
            _is_us_bo = st.session_state.get("us_buy_reason_type", "PB") == "BO"

            with st.form("us_buy_form", clear_on_submit=False):
                c1, c2 = st.columns(2)
                us_ticker = st.session_state.get("us_buy_ticker", "").strip().upper()
                us_name   = st.session_state.get("us_buy_name", "").strip()
                us_date   = c1.date_input("매수일", value=datetime.now().date(), key="us_buy_date")

                c4, c5, c6, c7 = st.columns(4)
                us_price = c4.number_input("매수가 ($)", min_value=0.0, step=0.01, format="%.2f", key="us_buy_price")
                us_qty   = c5.number_input("수량 (주)", min_value=1, step=1, key="us_buy_qty")
                us_stop  = c6.number_input("손절가 ($)", min_value=0.0, step=0.01, format="%.2f", key="us_buy_stop")
                us_tp    = c7.number_input("1차익절가 ($)", min_value=0.0, step=0.01, format="%.2f", key="us_buy_tp")

                if _is_us_bo:
                    us_memo = st.text_input("메모", key="us_buy_memo")
                    us_ma   = None
                else:
                    c8, c9 = st.columns([1, 2])
                    us_ma   = c8.selectbox("기준 이동평균", [5, 20, 60, 100, 120, 200], index=1, key="us_buy_ma")
                    us_memo = c9.text_input("메모", key="us_buy_memo")

                if st.form_submit_button("✅ 매수 저장", type="primary"):
                    _reason_type  = st.session_state.get("us_buy_reason_type", "PB")
                    _entry_reason = "BO" if _reason_type == "BO" else f"{_reason_type}{us_ma}"
                    if not us_ticker or not us_name or us_price <= 0:
                        st.error("Ticker, Company Name, 매수가를 입력해주세요.")
                    else:
                        add_buy(
                            ticker=us_ticker, name=us_name,
                            date=us_date.strftime("%Y-%m-%d"),
                            price=us_price, quantity=int(us_qty),
                            stop_loss=us_stop, entry_reason=_entry_reason, memo=us_memo,
                            take_profit=us_tp,
                        )
                        st.session_state["portfolio_toast"] = (f"✅ {us_name} 매수 저장 완료!", "success")
                        st.session_state["us_buy_expander_open"] = True
                        # 폼 필드 초기화 (다음 입력 준비)
                        for k in ["us_buy_ticker", "us_buy_name", "us_buy_price", "us_buy_qty", "us_buy_stop", "us_buy_tp", "us_buy_memo"]:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

        # ── 매도 입력 ──
        with st.expander("➖ 매도 입력"):
            df_pos2 = get_open_positions()
            if df_pos2.empty:
                st.info("보유 중인 종목이 없습니다.")
            else:
                _choices2 = {
                    f"{r['종목명']} ({r['종목코드']}) — {r['수량']}주 보유": r["position_id"]
                    for _, r in df_pos2.iterrows()
                }
                with st.form("us_sell_form"):
                    _sel2    = st.selectbox("종목 선택", list(_choices2.keys()))
                    _pos_id2 = _choices2[_sel2]

                    c1, c2, c3 = st.columns(3)
                    _sell_date  = c1.date_input("매도일", value=datetime.now().date())
                    _sell_price = c2.number_input("매도가 ($)", min_value=0.0, step=0.01, format="%.2f")
                    _sell_qty   = c3.number_input("수량 (주)", min_value=1, step=1)

                    _SELL_REASONS_US = ["+20%익절", "일중반전", "전고점전축소", "MA20돌파", "MA60돌파", "손절", "기타"]
                    c4, c5 = st.columns([1, 2])
                    _sell_reason_type = c4.selectbox("매도 사유", _SELL_REASONS_US)
                    _sell_reason_memo = c5.text_input("메모", placeholder="추가 메모 (선택)")
                    _us_sell_submitted = st.form_submit_button("✅ 매도 저장", type="primary")

                if _us_sell_submitted:
                    _sell_reason = f"{_sell_reason_type}" + (f" — {_sell_reason_memo}" if _sell_reason_memo else "")
                    if _sell_price <= 0:
                        st.error("매도가를 입력해주세요.")
                    else:
                        add_sell(
                            position_id=_pos_id2,
                            date=_sell_date.strftime("%Y-%m-%d"),
                            price=_sell_price, quantity=int(_sell_qty),
                            reason=_sell_reason,
                        )
                        st.session_state.pop("portfolio_prices_us", None)
                        st.session_state["portfolio_toast"] = ("✅ 매도 저장 완료!", "success")
                        st.rerun()

        # ── 손절가 수정 ──
        with st.expander("✏️ 손절가 수정"):
            df_pos3 = get_open_positions()
            if df_pos3.empty:
                st.info("보유 중인 종목이 없습니다.")
            else:
                _choices3 = {
                    f"{r['종목명']} ({r['종목코드']}) — 현재 손절가 ${r['손절가']:.2f}": r["position_id"]
                    for _, r in df_pos3.iterrows()
                }
                with st.form("us_sl_form"):
                    _sel3    = st.selectbox("종목 선택", list(_choices3.keys()))
                    _pos_id3 = _choices3[_sel3]

                    c1, c2, c3 = st.columns(3)
                    _sl_date  = c1.date_input("수정일", value=datetime.now().date())
                    _sl_price = c2.number_input("새 손절가 ($)", min_value=0.0, step=0.01, format="%.2f")
                    _sl_note  = c3.text_input("메모", placeholder="예: 1차 상승 후 이동")
                    _us_sl_submitted = st.form_submit_button("✅ 손절가 저장", type="primary")

                if _us_sl_submitted:
                    if _sl_price <= 0:
                        st.error("새 손절가를 입력해주세요.")
                    else:
                        update_stop_loss(_pos_id3, _sl_date.strftime("%Y-%m-%d"), _sl_price, _sl_note)
                        st.session_state["portfolio_toast"] = ("✅ 손절가 수정 완료!", "success")
                        st.rerun()

        # ── 1차 익절가 수정 ──
        with st.expander("✏️ 1차 익절가 수정"):
            df_pos_tp = get_open_positions()
            if df_pos_tp.empty:
                st.info("보유 중인 종목이 없습니다.")
            else:
                _tp_choices = {
                    f"{r['종목명']} ({r['종목코드']}) — 현재 익절가 ${r['1차익절가']:.2f}" if r['1차익절가'] else
                    f"{r['종목명']} ({r['종목코드']}) — 미설정": r["position_id"]
                    for _, r in df_pos_tp.iterrows()
                }
                with st.form("us_tp_form"):
                    _tp_sel = st.selectbox("종목 선택", list(_tp_choices.keys()), key="us_tp_sel")
                    _tp_pos_id = _tp_choices[_tp_sel]
                    _tp_price = st.number_input("1차 익절가 ($)", min_value=0.0, step=0.01, format="%.2f", key="us_tp_price")
                    _us_tp_submitted = st.form_submit_button("✅ 익절가 저장", type="primary")

                if _us_tp_submitted:
                    if _tp_price <= 0:
                        st.error("1차 익절가를 입력해주세요.")
                    else:
                        update_take_profit(_tp_pos_id, _tp_price)
                        st.session_state["portfolio_toast"] = ("✅ 1차 익절가 수정 완료!", "success")
                        st.rerun()

        # ── 거래 내역 수정/삭제 ──
        with st.expander("🔧 거래 내역 수정/삭제"):
            import json as _json_us
            import portfolio as _pf_us_mod
            _us_pf_data = _json_us.loads(_pf_us_mod.PORTFOLIO_FILE.read_text(encoding="utf-8")) if _pf_us_mod.PORTFOLIO_FILE.exists() else {}
            _us_all_pos = _us_pf_data.get("positions", [])

            if not _us_all_pos:
                st.info("포지션이 없습니다.")
            else:
                _us_pos_choices = {
                    f"{p['name']} ({p['ticker']}) [{p['status']}]": p
                    for p in _us_all_pos
                }
                _us_sel_name = st.selectbox("종목 선택", list(_us_pos_choices.keys()), key="us_edit_pos_select")
                _us_sel_pos  = _us_pos_choices[_us_sel_name]
                _us_pos_id   = _us_sel_pos["id"]
                _us_trades   = _us_sel_pos.get("trades", [])

                if not _us_trades:
                    st.info("거래 내역이 없습니다.")
                else:
                    st.markdown("**거래 목록** — 수정하려면 행을 선택하세요")
                    for _tr in _us_trades:
                        _label = (
                            f"{'🟢 매수' if _tr['type']=='buy' else '🔴 매도'}  "
                            f"{_tr['date']}  ${_tr['price']:.2f}  {_tr['quantity']}주"
                            + (f"  [{_tr.get('entry_reason','')}]" if _tr['type']=='buy' else "")
                            + (f"  {_tr.get('memo','') or _tr.get('reason','')}"[:20] if (_tr.get('memo') or _tr.get('reason')) else "")
                        )
                        _col1, _col2 = st.columns([8, 1])
                        _col1.markdown(_label)
                        if _col2.button("🗑️", key=f"us_del_trade_{_tr['id']}", help="삭제"):
                            delete_trade(_us_pos_id, _tr["id"])
                            st.session_state["portfolio_toast"] = ("✅ 거래 내역이 삭제되었습니다.", "success")
                            st.rerun()

                    st.markdown("---")
                    st.markdown("**수정할 거래 선택**")
                    _us_trade_labels = {
                        f"{'매수' if t['type']=='buy' else '매도'} | {t['date']} | ${t['price']:.2f} | {t['quantity']}주": t
                        for t in _us_trades
                    }
                    _us_edit_label = st.selectbox("거래 선택", list(_us_trade_labels.keys()), key="us_edit_trade_select")
                    _us_edit_tr    = _us_trade_labels[_us_edit_label]

                    _ueid = _us_edit_tr["id"]
                    _ec1, _ec2, _ec3 = st.columns(3)
                    _ue_date  = _ec1.date_input("날짜", value=datetime.strptime(_us_edit_tr["date"], "%Y-%m-%d").date(), key=f"us_edit_date_{_ueid}")
                    _ue_price = _ec2.number_input("가격 ($)", value=float(_us_edit_tr["price"]), min_value=0.0, step=0.01, format="%.2f", key=f"us_edit_price_{_ueid}")
                    _ue_qty   = _ec3.number_input("수량 (주)", value=int(_us_edit_tr["quantity"]), min_value=1, step=1, key=f"us_edit_qty_{_ueid}")

                    if _us_edit_tr["type"] == "buy":
                        _ec4, _ec5, _ec6 = st.columns(3)
                        _ue_stop   = _ec4.number_input("손절가 ($)", value=float(_us_edit_tr.get("stop_loss", 0)), min_value=0.0, step=0.01, format="%.2f", key=f"us_edit_stop_{_ueid}")
                        _ue_reason = _ec5.text_input("진입근거", value=_us_edit_tr.get("entry_reason", ""), key=f"us_edit_reason_{_ueid}")
                        _ue_memo   = _ec6.text_input("메모", value=_us_edit_tr.get("memo", ""), key=f"us_edit_memo_{_ueid}")
                    else:
                        _US_SELL_REASONS2 = ["+20%익절", "일중반전", "전고점전축소", "MA20돌파", "MA60돌파", "손절", "기타"]
                        _ue_cur_reason  = _us_edit_tr.get("reason", "")
                        _ue_cur_type    = next((r for r in _US_SELL_REASONS2 if _ue_cur_reason.startswith(r)), "기타")
                        _ue_cur_memo    = _ue_cur_reason.split(" — ", 1)[1] if " — " in _ue_cur_reason else ""
                        _er1, _er2      = st.columns([1, 2])
                        _ue_reason_type = _er1.selectbox("매도 사유", _US_SELL_REASONS2, index=_US_SELL_REASONS2.index(_ue_cur_type), key=f"us_edit_sell_reason_type_{_ueid}")
                        _ue_reason_memo = _er2.text_input("메모", value=_ue_cur_memo, key=f"us_edit_sell_reason_memo_{_ueid}")
                        _ue_reason      = f"{_ue_reason_type}" + (f" — {_ue_reason_memo}" if _ue_reason_memo else "")

                    if st.button("💾 수정 저장", type="primary", key="us_edit_save_btn"):
                        _ue_fields = {
                            "date":     _ue_date.strftime("%Y-%m-%d"),
                            "price":    _ue_price,
                            "quantity": int(_ue_qty),
                        }
                        if _us_edit_tr["type"] == "buy":
                            _ue_fields["stop_loss"]    = _ue_stop
                            _ue_fields["entry_reason"] = _ue_reason
                            _ue_fields["memo"]         = _ue_memo
                        else:
                            _ue_fields["reason"] = _ue_reason
                        update_trade(_us_pos_id, _us_edit_tr["id"], _ue_fields)
                        st.session_state["portfolio_toast"] = ("✅ 거래 내역이 수정되었습니다.", "success")
                        st.rerun()

        # ── 손절가 변경 이력 ──
        with st.expander("📋 손절가 변경 이력"):
            df_pos4 = get_open_positions()
            if not df_pos4.empty:
                _sl_choices4 = {f"{r['종목명']} ({r['종목코드']})": r["position_id"] for _, r in df_pos4.iterrows()}
                _sl_sel4 = st.selectbox("종목 선택", list(_sl_choices4.keys()), key="us_sl_hist_select")
                _sl_pid4 = _sl_choices4[_sl_sel4]
                df_sl_hist = get_stop_loss_history(_sl_pid4)
                if df_sl_hist.empty:
                    st.info("손절가 변경 이력이 없습니다.")
                else:
                    _aggrid(df_sl_hist, key="us_sl_hist_table", height=250, click_nav=False)

        # ── 원금 입출금 관리 ──
        with st.expander("⚙️ 원금 입출금 관리", expanded=(get_total_capital() == 0)):
            c1, c2, c3 = st.columns(3)
            flow_date   = c1.date_input("날짜", value=datetime.now().date(), key="us_flow_date")
            flow_type   = c2.selectbox("구분", ["입금", "출금"], key="us_flow_type")
            flow_amount = c3.number_input("금액 ($)", min_value=0.0, step=100.0, format="%.2f", key="us_flow_amount")
            flow_note   = st.text_input("메모", key="us_flow_note", placeholder="예: 초기 원금 / 추가 투자 / 일부 인출")
            if st.button("✅ 저장", key="us_flow_save"):
                if flow_amount <= 0:
                    st.error("금액을 입력해주세요.")
                else:
                    signed = float(flow_amount) if flow_type == "입금" else -float(flow_amount)
                    add_capital_flow(flow_date.strftime("%Y-%m-%d"), signed, flow_note)
                    st.success("저장 완료!")
                    st.rerun()

            df_flows = get_capital_flows()
            if not df_flows.empty:
                st.caption(f"현재 원금 합계: **${get_total_capital():,.2f}**")
                for _, row in df_flows.iterrows():
                    col_a, col_b, col_c, col_d = st.columns([2, 3, 3, 1])
                    col_a.write(row.get("날짜", ""))
                    amount = row.get("금액(원)", 0)
                    col_b.write(f"${amount:+,.2f}")
                    col_c.write(row.get("메모", ""))
                    flow_id = row.get("id", "")
                    if flow_id and col_d.button("🗑️", key=f"us_del_flow_{flow_id}"):
                        delete_capital_flow(flow_id)
                        st.rerun()

    # ── 거래별 성과분석 ─────────────────────────────
    with tab_pnl:
        df_pnl = get_realized_pnl()
        if df_pnl.empty:
            st.info("실현된 손익이 없습니다. 매도 후 확인하세요.")
        else:
            _rename_us = {c: c.replace("(원)", "($)") for c in df_pnl.columns if "(원)" in c}
            df_pnl = df_pnl.rename(columns=_rename_us)
            _pnl_col = "실현손익($)" if "실현손익($)" in df_pnl.columns else "실현손익(원)"
            _fee_col = "거래비용($)" if "거래비용($)" in df_pnl.columns else "거래비용(원)"
            _net_col = "비용차감손익($)" if "비용차감손익($)" in df_pnl.columns else "비용차감손익(원)"

            df_pnl["_buy_cost"] = df_pnl["평균매수가"] * df_pnl["수량"] if "평균매수가" in df_pnl.columns else 1
            df_pnl["_월"] = pd.to_datetime(df_pnl["날짜"]).dt.to_period("M").astype(str)
            df_pnl["_연도"] = pd.to_datetime(df_pnl["날짜"]).dt.year.astype(str)

            _us_pnl_years = sorted(df_pnl["_연도"].unique(), reverse=True)
            _us_pnl_opts = ["전체"] + _us_pnl_years
            _cur_year = datetime.now().strftime("%Y")
            _us_pnl_year_idx = _us_pnl_opts.index(_cur_year) if _cur_year in _us_pnl_opts else 0
            _us_pnl_sel_year = st.selectbox("기간 선택", _us_pnl_opts, index=_us_pnl_year_idx, key="us_pnl_year")

            if _us_pnl_sel_year == "전체":
                _us_pnl_filtered = df_pnl
                _us_pnl_sel_month = None
            else:
                _us_pnl_year_df = df_pnl[df_pnl["_연도"] == _us_pnl_sel_year]
                _us_pnl_month_opts = ["연간 전체"] + sorted(_us_pnl_year_df["_월"].unique(), reverse=True)
                _cur_month = datetime.now().strftime("%Y-%m")
                _us_pnl_month_idx = _us_pnl_month_opts.index(_cur_month) if _cur_month in _us_pnl_month_opts else 0
                _us_pnl_sel_month = st.selectbox("월 선택", _us_pnl_month_opts, index=_us_pnl_month_idx, key="us_pnl_month")
                if _us_pnl_sel_month == "연간 전체":
                    _us_pnl_filtered = _us_pnl_year_df
                    _us_pnl_sel_month = None
                else:
                    _us_pnl_filtered = _us_pnl_year_df[_us_pnl_year_df["_월"] == _us_pnl_sel_month]

            _us_pnl_label = _us_pnl_sel_year if _us_pnl_sel_year != "전체" else "전체"
            if _us_pnl_sel_month:
                _us_pnl_label = _us_pnl_sel_month

            def _render_trade_kpi_us(df_sub):
                n = len(df_sub)
                if n == 0:
                    st.info("해당 기간에 거래가 없습니다.")
                    return
                wins = df_sub[df_sub["수익률(%)"] > 0]
                losses = df_sub[df_sub["수익률(%)"] <= 0]
                win_rate = len(wins) / n * 100
                total_pnl = df_sub[_pnl_col].sum() if _pnl_col in df_sub.columns else 0
                total_fees = df_sub[_fee_col].sum() if _fee_col in df_sub.columns else 0
                total_net = df_sub[_net_col].sum() if _net_col in df_sub.columns else total_pnl
                total_inv = df_sub["_buy_cost"].sum()
                _w_wins = wins["수익률(%)"].values * wins["_buy_cost"].values if len(wins) > 0 else []
                _w_losses = losses["수익률(%)"].values * losses["_buy_cost"].values if len(losses) > 0 else []
                avg_win = _w_wins.sum() / wins["_buy_cost"].sum() if len(wins) > 0 and wins["_buy_cost"].sum() > 0 else 0
                avg_loss = _w_losses.sum() / losses["_buy_cost"].sum() if len(losses) > 0 and losses["_buy_cost"].sum() > 0 else 0
                avg_ret = (df_sub["수익률(%)"].values * df_sub["_buy_cost"].values).sum() / df_sub["_buy_cost"].sum() if df_sub["_buy_cost"].sum() > 0 else 0
                avg_planned_loss = losses["목표손절률(%)"].dropna().mean() if len(losses) > 0 and "목표손절률(%)" in losses.columns else None
                if avg_planned_loss is not None:
                    losses_wt = losses.dropna(subset=["목표손절률(%)"])
                    violations = losses_wt[losses_wt["수익률(%)"] < losses_wt["목표손절률(%)"]]
                    n_violations = len(violations)
                    violation_rate = n_violations / len(losses_wt) * 100 if len(losses_wt) > 0 else 0
                else:
                    n_violations = 0
                    violation_rate = 0
                initial_capital = get_total_capital()
                turnover = total_inv / initial_capital if initial_capital > 0 else None
                capital_ret = (total_pnl / initial_capital * 100) if initial_capital > 0 else None
                rr_vals = df_sub["RR"].dropna() if "RR" in df_sub.columns else pd.Series(dtype=float)
                avg_rr = rr_vals.mean() if len(rr_vals) > 0 else None
                avg_hold_win = wins["보유일수"].dropna().mean() if len(wins) > 0 and "보유일수" in wins.columns else None
                avg_hold_loss = losses["보유일수"].dropna().mean() if len(losses) > 0 and "보유일수" in losses.columns else None

                c1, c2, c3 = st.columns(3)
                c1.metric("총 실현손익 (비용차감)", f"${total_net:+,.2f}",
                          delta=f"거래비용 ${total_fees:,.2f}", delta_color="inverse")
                c2.metric("거래 건수", f"{n}건")
                c3.metric("승/패", f"{len(wins)}승 {len(losses)}패")
                c4, c5, c6 = st.columns(3)
                c4.metric("승률", f"{win_rate:.1f}%")
                c5.metric("승리 시 평균수익률", f"{avg_win:+.2f}%")
                if avg_planned_loss is not None:
                    _diff1 = avg_loss - avg_planned_loss
                    _delta1_txt = f"목표보다 {abs(_diff1):.2f}%p 절약 ✓" if _diff1 > 0 else f"목표보다 {abs(_diff1):.2f}%p 초과"
                else:
                    _delta1_txt = None
                c6.metric("패배 시 평균손실률", f"{avg_loss:+.2f}%",
                          delta=_delta1_txt, delta_color="normal")
                c4b, c5b, c6b = st.columns(3)
                c4b.metric("목표손절 위반 횟수", f"{n_violations}회")
                c5b.metric("목표손절 위반율", f"{violation_rate:.1f}%")
                c6b.metric("패배 시 평균목표손절률", f"{avg_planned_loss:.2f}%" if avg_planned_loss is not None else "-")
                c7, c8, c9 = st.columns(3)
                c7.metric("전체 평균수익률 (가중)", f"{avg_ret:+.2f}%")
                c8.metric("자산회전율", f"{turnover:.2f}배" if turnover is not None else "원금 미설정")
                c9.metric("원금대비 실현수익률", f"{capital_ret:+.2f}%" if capital_ret is not None else "원금 미설정")
                c10, c11, c12 = st.columns(3)
                c10.metric("평균 RR", f"{avg_rr:.2f}" if avg_rr is not None else "-")
                c11.metric("수익 시 평균보유기간", f"{avg_hold_win:.0f}일" if avg_hold_win is not None else "-")
                c12.metric("손실 시 평균보유기간", f"{avg_hold_loss:.0f}일" if avg_hold_loss is not None else "-")

            _render_trade_kpi_us(_us_pnl_filtered)

            # ── 월별 KPI 비교표 (전체/연간 선택 시) ──
            if not _us_pnl_sel_month and len(_us_pnl_filtered) > 0:
                _us_months_in_range = sorted(_us_pnl_filtered["_월"].unique())
                if len(_us_months_in_range) > 1:
                    st.divider()
                    st.subheader(f"월별 KPI 비교 ({_us_pnl_label})")
                    _us_mkpi_rows = []
                    _us_init_cap = get_total_capital()
                    for _m in _us_months_in_range:
                        _m_df = _us_pnl_filtered[_us_pnl_filtered["_월"] == _m]
                        _mn = len(_m_df)
                        if _mn == 0:
                            continue
                        _mw = _m_df[_m_df["수익률(%)"] > 0]
                        _ml = _m_df[_m_df["수익률(%)"] <= 0]
                        _m_bc = _m_df["_buy_cost"].sum()
                        _m_avg_win = (_mw["수익률(%)"].values * (_mw["평균매수가"] * _mw["수량"]).values).sum() / (_mw["평균매수가"] * _mw["수량"]).sum() if len(_mw) > 0 and (_mw["평균매수가"] * _mw["수량"]).sum() > 0 else 0
                        _m_avg_loss = (_ml["수익률(%)"].values * (_ml["평균매수가"] * _ml["수량"]).values).sum() / (_ml["평균매수가"] * _ml["수량"]).sum() if len(_ml) > 0 and (_ml["평균매수가"] * _ml["수량"]).sum() > 0 else 0
                        _m_avg = (_m_df["수익률(%)"].values * _m_df["_buy_cost"].values).sum() / _m_bc if _m_bc > 0 else 0
                        _m_pnl = _m_df[_pnl_col].sum() if _pnl_col in _m_df.columns else 0
                        _m_fees = _m_df[_fee_col].sum() if _fee_col in _m_df.columns else 0
                        _m_net = _m_df[_net_col].sum() if _net_col in _m_df.columns else _m_pnl
                        _m_rr = _m_df["RR"].dropna().mean() if "RR" in _m_df.columns and _m_df["RR"].dropna().any() else None
                        _m_planned = _ml["목표손절률(%)"].dropna().mean() if len(_ml) > 0 and "목표손절률(%)" in _ml.columns else None
                        _m_lwt = _ml.dropna(subset=["목표손절률(%)"]) if len(_ml) > 0 and "목표손절률(%)" in _ml.columns else pd.DataFrame()
                        _m_viols = len(_m_lwt[_m_lwt["수익률(%)"] < _m_lwt["목표손절률(%)"]]) if len(_m_lwt) > 0 else 0
                        _m_viol_rate = _m_viols / len(_m_lwt) * 100 if len(_m_lwt) > 0 else 0
                        _m_turnover = _m_bc / _us_init_cap if _us_init_cap > 0 else None
                        _m_cap_ret = (_m_pnl / _us_init_cap * 100) if _us_init_cap > 0 else None
                        _m_hold_win = _mw["보유일수"].dropna().mean() if len(_mw) > 0 and "보유일수" in _mw.columns else None
                        _m_hold_loss = _ml["보유일수"].dropna().mean() if len(_ml) > 0 and "보유일수" in _ml.columns else None
                        _us_mkpi_rows.append({
                            "월": _m,
                            "거래수": _mn,
                            "승/패": f"{len(_mw)}/{len(_ml)}",
                            "승률(%)": round(len(_mw) / _mn * 100, 1),
                            "승리평균(%)": round(_m_avg_win, 2),
                            "패배평균(%)": round(_m_avg_loss, 2),
                            "전체평균(%)": round(_m_avg, 2),
                            "평균RR": round(_m_rr, 2) if _m_rr is not None else None,
                            "손절위반": _m_viols,
                            "위반율(%)": round(_m_viol_rate, 1),
                            "회전율": round(_m_turnover, 2) if _m_turnover is not None else None,
                            "원금대비(%)": round(_m_cap_ret, 2) if _m_cap_ret is not None else None,
                            "승리보유일": round(_m_hold_win, 0) if _m_hold_win is not None else None,
                            "손실보유일": round(_m_hold_loss, 0) if _m_hold_loss is not None else None,
                            "비용차감손익($)": round(_m_net, 2),
                        })
                    if _us_mkpi_rows:
                        _us_mkpi_df = pd.DataFrame(_us_mkpi_rows)
                        _aggrid(_us_mkpi_df, key=f"us_monthly_kpi_compare_{_us_pnl_label}", height=min(300, 60 + len(_us_mkpi_df) * 40),
                                color_map={"전체평균(%)": "red_positive", "승리평균(%)": "red_positive", "패배평균(%)": "red_positive", "비용차감손익($)": "red_positive", "원금대비(%)": "red_positive"},
                                pct_cols=["승률(%)", "승리평균(%)", "패배평균(%)", "전체평균(%)", "원금대비(%)"],
                                price_cols=["비용차감손익($)"], price_decimals=2)

            st.divider()
            _us_pnl_color_map = {_pnl_col: "red_positive", _net_col: "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
            _aggrid(_us_pnl_filtered, key=f"us_trade_pnl_table_{_us_pnl_label}", height=450, click_nav=False,
                    color_map=_us_pnl_color_map, pct_cols=["수익률(%)", "비용차감수익률(%)"], price_decimals=2)

            st.divider()
            st.subheader(f"누적 수익 곡선 ({_us_pnl_label})")
            _render_equity_curve(source_df=_us_pnl_filtered)
            st.divider()
            if not _us_pnl_sel_month:
                st.subheader(f"월별 성과 ({_us_pnl_label})")
                _render_monthly_performance(source_df=_us_pnl_filtered)

            # 수익률 분포도
            _render_return_distribution(_us_pnl_filtered, _us_pnl_label, "us")

    # ── 종목별 성과분석 ─────────────────────────────
    with tab_perf:
        df_pos_pnl = get_position_pnl()
        if df_pos_pnl is None or df_pos_pnl.empty:
            st.info("청산된 포지션이 없습니다.")
        else:
            _rename_us2 = {c: c.replace("(원)", "($)") for c in df_pos_pnl.columns if "(원)" in c}
            df_pos_pnl = df_pos_pnl.rename(columns=_rename_us2)
            _pos_net_col = "비용차감손익($)" if "비용차감손익($)" in df_pos_pnl.columns else "비용차감손익(원)"
            _pos_fee_col = "거래비용($)" if "거래비용($)" in df_pos_pnl.columns else "거래비용(원)"
            _pos_pnl_col = "실현손익($)" if "실현손익($)" in df_pos_pnl.columns else "실현손익(원)"
            _us_currency = "$" if "실현손익($)" in df_pos_pnl.columns else "원"

            initial_capital_us = get_total_capital()

            def _kpi_metrics_us(df_sub):
                """df_sub 기준 KPI dict 반환 (미국)"""
                n       = len(df_sub)
                wins    = df_sub[df_sub["수익률(%)"] > 0]
                losses  = df_sub[df_sub["수익률(%)"] <= 0]
                total_inv  = (df_sub["평균매수가"] * df_sub["청산수량"]).sum()
                total_pnl  = df_sub[_pos_pnl_col].sum() if _pos_pnl_col in df_sub.columns else 0
                total_fees = df_sub[_pos_fee_col].sum() if _pos_fee_col in df_sub.columns else 0
                total_net  = df_sub[_pos_net_col].sum() if _pos_net_col in df_sub.columns else total_pnl
                # 금액 가중 평균수익률
                df_sub = df_sub.copy()
                df_sub["_buy_cost"] = df_sub["평균매수가"] * df_sub["청산수량"]
                _bc_total = df_sub["_buy_cost"].sum()
                wins_bc   = wins["평균매수가"] * wins["청산수량"] if len(wins) > 0 else None
                losses_bc = losses["평균매수가"] * losses["청산수량"] if len(losses) > 0 else None
                avg_win   = (wins["수익률(%)"].values * wins_bc.values).sum() / wins_bc.sum()       if wins_bc is not None and wins_bc.sum() > 0   else 0
                avg_loss  = (losses["수익률(%)"].values * losses_bc.values).sum() / losses_bc.sum() if losses_bc is not None and losses_bc.sum() > 0 else 0
                avg_ret   = (df_sub["수익률(%)"].values * df_sub["_buy_cost"].values).sum() / _bc_total if _bc_total > 0 else 0
                avg_planned_loss_p = losses["목표손절률(%)"].dropna().mean() if len(losses) > 0 and "목표손절률(%)" in losses.columns else None
                if avg_planned_loss_p is not None and "목표손절률(%)" in losses.columns:
                    losses_wt = losses.dropna(subset=["목표손절률(%)"])
                    viols = losses_wt[losses_wt["수익률(%)"] < losses_wt["목표손절률(%)"]]
                    n_viols    = len(viols)
                    viol_rate  = n_viols / len(losses_wt) * 100 if len(losses_wt) > 0 else 0
                else:
                    n_viols = 0
                    viol_rate = 0
                turnover    = total_inv / initial_capital_us if initial_capital_us > 0 else None
                adj_ret     = avg_ret * turnover if turnover is not None else None
                capital_ret = (total_pnl / initial_capital_us * 100) if initial_capital_us > 0 else None
                avg_rr    = df_sub["RR"].dropna().mean() if "RR" in df_sub.columns and df_sub["RR"].dropna().any() else None
                avg_hold_win  = wins["보유일수"].dropna().mean()   if len(wins) > 0 and "보유일수" in wins.columns   else None
                avg_hold_loss = losses["보유일수"].dropna().mean() if len(losses) > 0 and "보유일수" in losses.columns else None
                return {
                    "종목수":               n,
                    "승/패":               f"{len(wins)}승 {len(losses)}패",
                    "승률(%)":             round(len(wins)/n*100, 1) if n > 0 else 0,
                    "승리 평균수익률(%)":   round(avg_win,  2),
                    "패배 평균손실률(%)":   round(avg_loss, 2),
                    "패배 평균목표손절률(%)": round(avg_planned_loss_p, 2) if avg_planned_loss_p is not None else "-",
                    "목표손절 위반 횟수":    n_viols,
                    "목표손절 위반율(%)":    round(viol_rate, 1),
                    "전체 평균수익률(%)":   round(avg_ret,  2),
                    "자산회전율":          round(turnover, 2) if turnover is not None else "-",
                    "원금대비수익률(%)":    round(capital_ret, 2) if capital_ret is not None else "-",
                    "평균RR":              round(avg_rr, 2) if avg_rr is not None else "-",
                    "수익시 평균보유일":    round(avg_hold_win,  0) if avg_hold_win  is not None else "-",
                    "손실시 평균보유일":    round(avg_hold_loss, 0) if avg_hold_loss is not None else "-",
                    f"총 실현손익({_us_currency})":  round(total_pnl, 2),
                    f"거래비용({_us_currency})":     round(total_fees, 2),
                    f"비용차감손익({_us_currency})": round(total_net, 2),
                }

            # ── 기간 선택 ──
            df_pos_pnl_c = df_pos_pnl.copy()
            df_pos_pnl_c["청산월"] = pd.to_datetime(df_pos_pnl_c["청산일"]).dt.to_period("M").astype(str)
            df_pos_pnl_c["청산연도"] = pd.to_datetime(df_pos_pnl_c["청산일"]).dt.year.astype(str)

            _us_years = sorted(df_pos_pnl_c["청산연도"].unique(), reverse=True)
            _us_period_options = ["전체"] + _us_years
            _cur_year = datetime.now().strftime("%Y")
            _us_perf_year_idx = _us_period_options.index(_cur_year) if _cur_year in _us_period_options else 0
            _us_sel_year = st.selectbox("기간 선택", _us_period_options, index=_us_perf_year_idx, key="us_perf_year")

            if _us_sel_year == "전체":
                _us_perf_df = df_pos_pnl_c
                _us_sel_month_perf = None
            else:
                _us_year_df = df_pos_pnl_c[df_pos_pnl_c["청산연도"] == _us_sel_year]
                _us_month_opts = ["연간 전체"] + sorted(_us_year_df["청산월"].unique(), reverse=True)
                _cur_month = datetime.now().strftime("%Y-%m")
                _us_perf_month_idx = _us_month_opts.index(_cur_month) if _cur_month in _us_month_opts else 0
                _us_sel_month_perf = st.selectbox("월 선택", _us_month_opts, index=_us_perf_month_idx, key="us_perf_month")
                if _us_sel_month_perf == "연간 전체":
                    _us_perf_df = _us_year_df
                    _us_sel_month_perf = None
                else:
                    _us_perf_df = _us_year_df[_us_year_df["청산월"] == _us_sel_month_perf]

            _us_period_label = _us_sel_year if _us_sel_year != "전체" else "전체"
            if _us_sel_month_perf:
                _us_period_label = _us_sel_month_perf

            def _render_kpi_cards_us(kpi):
                c1, c2, c3 = st.columns(3)
                c1.metric("총 실현손익 (비용차감)",
                          f"${kpi[f'비용차감손익({_us_currency})']:+,.2f}",
                          delta=f"거래비용 ${kpi[f'거래비용({_us_currency})']:,.2f}", delta_color="inverse")
                c2.metric("종목 수", f"{kpi['종목수']}종목")
                c3.metric("승/패", kpi["승/패"])
                _pl_us = kpi["패배 평균목표손절률(%)"]
                _al_us = kpi["패배 평균손실률(%)"]
                if _pl_us != "-":
                    _diff_us = _al_us - _pl_us
                    _delta_us_txt = f"목표보다 {abs(_diff_us):.2f}%p 절약 ✓" if _diff_us > 0 else f"목표보다 {abs(_diff_us):.2f}%p 초과"
                else:
                    _delta_us_txt = None
                c4, c5, c6 = st.columns(3)
                c4.metric("승률", f"{kpi['승률(%)']:.1f}%")
                c5.metric("승리 시 평균수익률", f"{kpi['승리 평균수익률(%)']:+.2f}%")
                c6.metric("패배 시 평균손실률", f"{kpi['패배 평균손실률(%)']:+.2f}%",
                          delta=_delta_us_txt, delta_color="normal")
                c4b, c5b, c6b = st.columns(3)
                c4b.metric("목표손절 위반 횟수", f"{kpi['목표손절 위반 횟수']}회")
                c5b.metric("목표손절 위반율", f"{kpi['목표손절 위반율(%)']:.1f}%")
                c6b.metric("패배 시 평균목표손절률", f"{_pl_us:.2f}%" if _pl_us != "-" else "-")
                c7, c8, c9 = st.columns(3)
                c7.metric("전체 평균수익률 (가중)", f"{kpi['전체 평균수익률(%)']:+.2f}%")
                c8.metric("자산회전율", f"{kpi['자산회전율']:.2f}배" if kpi['자산회전율'] != "-" else "원금 미설정")
                c9.metric("원금대비 실현수익률", f"{kpi['원금대비수익률(%)']:+.2f}%" if kpi['원금대비수익률(%)'] != "-" else "원금 미설정")
                c10, c11, c12 = st.columns(3)
                c10.metric("평균 RR", f"{kpi['평균RR']:.2f}" if kpi['평균RR'] != "-" else "-")
                c11.metric("수익 시 평균보유기간", f"{kpi['수익시 평균보유일']:.0f}일" if kpi['수익시 평균보유일'] != "-" else "-")
                c12.metric("손실 시 평균보유기간", f"{kpi['손실시 평균보유일']:.0f}일" if kpi['손실시 평균보유일'] != "-" else "-")

            # ── 1. 성과분석 ──
            if _us_perf_df.empty:
                st.info(f"{_us_period_label} 기간에 청산된 종목이 없습니다.")
            else:
                st.subheader(f"1. 성과분석 ({_us_period_label})")
                overall_us = _kpi_metrics_us(_us_perf_df)
                _render_kpi_cards_us(overall_us)

            st.divider()

            # ── 2. 종목별 성과분석 ──
            if not _us_perf_df.empty:
                st.subheader(f"2. 종목별 성과분석 ({_us_period_label})")
                _pos_pnl_color_map2 = {_pos_pnl_col: "red_positive", _pos_net_col: "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
                _pos_pnl_n = len(_us_perf_df)
                _pos_pnl_height = 250 if _pos_pnl_n <= 5 else (350 if _pos_pnl_n <= 10 else 450)
                _aggrid(_us_perf_df, key=f"us_position_pnl_table_{_us_period_label}", height=_pos_pnl_height,
                        click_nav=False, color_map=_pos_pnl_color_map2, pct_cols=["수익률(%)", "비용차감수익률(%)"], price_decimals=2)

            st.divider()

            # ── 3. 진입근거별 성과분석 ──
            if not _us_perf_df.empty:
                st.subheader(f"3. 진입근거별 성과분석 ({_us_period_label})")
            us_reason_rows = []
            if "진입근거" in _us_perf_df.columns and not _us_perf_df.empty:
                for prefix in ["PB", "HB", "BO"]:
                    sub = _us_perf_df[_us_perf_df["진입근거"].str.startswith(prefix)]
                    if sub.empty:
                        continue
                    row = _kpi_metrics_us(sub)
                    us_reason_rows.append({"진입근거": prefix, **row})

            if us_reason_rows:
                df_reason_us = pd.DataFrame(us_reason_rows).reset_index(drop=True)
                _reason_color_map_us = {
                    "승리 평균수익률(%)": "red_positive",
                    "패배 평균손실률(%)": "red_positive",
                    "전체 평균수익률(%)": "red_positive",
                    "원금대비수익률(%)":  "red_positive",
                    f"총 실현손익({_us_currency})": "red_positive",
                }
                _aggrid(df_reason_us, key=f"us_reason_perf_table_{_us_period_label}", height=250,
                        click_nav=False, color_map=_reason_color_map_us)
            else:
                st.info("진입근거별 데이터가 없습니다.")

    # ── 월별 리뷰 ─────────────────────────────
    with tab_review:
        _us_review_df = get_realized_pnl()
        if _us_review_df.empty:
            st.info("실현 거래가 없습니다.")
        else:
            _us_review_c = _us_review_df.copy()
            _us_review_c["월"] = pd.to_datetime(_us_review_c["날짜"]).dt.to_period("M").astype(str)
            _us_months = sorted(_us_review_c["월"].unique(), reverse=True)
            _us_sel_month = st.selectbox("월 선택", _us_months, key="us_review_month")

            us_review = get_monthly_review(_us_sel_month)
            if us_review.get("summary"):
                s = us_review["summary"]

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("거래수", s["거래수"])
                m2.metric("승률", f"{s['승률(%)']:.1f}%")
                m3.metric("평균수익률", f"{s['평균수익률(%)']:+.2f}%")
                m4.metric("총실현손익", f"${s['총실현손익(원)']:,.0f}")

                m5, m6, m7, m8 = st.columns(4)
                m5.metric("승리 평균", f"{s['승리 평균(%)']:+.2f}%")
                m6.metric("패배 평균", f"{s['패배 평균(%)']:+.2f}%")
                m7.metric("최대수익", f"{s['최대수익(%)']:+.2f}%")
                m8.metric("최대손실", f"{s['최대손실(%)']:+.2f}%")

                m9, m10 = st.columns(2)
                m9.metric("평균보유일수", f"{s['평균보유일수']:.0f}일")
                if s.get("평균RR") is not None:
                    m10.metric("평균 RR", f"{s['평균RR']:.2f}")

                st.divider()

                if us_review["by_reason"]:
                    st.subheader("진입근거별 분석")
                    us_reason_rows = []
                    for reason, stats in us_review["by_reason"].items():
                        us_reason_rows.append({
                            "진입근거": reason,
                            "거래수": stats["거래수"],
                            "승률(%)": stats["승률(%)"],
                            "평균수익률(%)": stats["평균수익률(%)"],
                            "승리 평균(%)": stats["승리 평균(%)"],
                            "패배 평균(%)": stats["패배 평균(%)"],
                            "최대수익(%)": stats["최대수익(%)"],
                            "최대손실(%)": stats["최대손실(%)"],
                            "평균보유일(일)": stats["평균보유일수"],
                            "평균RR": stats.get("평균RR", ""),
                            "총손익($)": stats["총실현손익(원)"],
                        })
                    us_reason_df = pd.DataFrame(us_reason_rows)
                    _aggrid(
                        us_reason_df,
                        key="us_review_reason",
                        height=min(250, 60 + len(us_reason_df) * 40),
                        color_map={"평균수익률(%)": "red_positive", "승리 평균(%)": "red_positive", "패배 평균(%)": "red_positive", "총손익($)": "red_positive"},
                        pct_cols=["승률(%)", "평균수익률(%)", "승리 평균(%)", "패배 평균(%)", "최대수익(%)", "최대손실(%)"],
                        price_cols=["총손익($)"],
                        price_decimals=2,
                    )

                st.divider()

                st.subheader("개별 거래 내역")
                us_trades = us_review["trades"]
                _us_tcols = ["청산일", "종목명", "진입근거", "수익률(%)", "비용차감손익(원)", "거래비용(원)", "보유일수", "RR"]
                _us_tshow = us_trades[[c for c in _us_tcols if c in us_trades.columns]]
                _aggrid(
                    _us_tshow,
                    key="us_review_trades",
                    height=min(400, 60 + len(_us_tshow) * 35),
                    color_map={"수익률(%)": "red_positive", "비용차감손익(원)": "red_positive"},
                    pct_cols=["수익률(%)"],
                    price_cols=["비용차감손익(원)", "거래비용(원)"],
                    price_decimals=2,
                )
            else:
                st.info(f"{_us_sel_month}에 실현 거래가 없습니다.")

    # ── 거래 이력 ─────────────────────────────
    with tab_log:
        df_log = get_trade_log()
        if df_log.empty:
            st.info("거래 이력이 없습니다.")
        else:
            show_cols = [c for c in ["date", "name", "ticker", "type", "price", "quantity",
                                     "entry_reason", "reason", "memo"] if c in df_log.columns]
            rename_map = {
                "date": "날짜", "name": "종목명", "ticker": "종목코드",
                "type": "구분", "price": "가격", "quantity": "수량",
                "entry_reason": "진입근거", "reason": "사유", "memo": "메모",
            }
            disp_log = df_log[show_cols].rename(columns=rename_map)
            _aggrid(disp_log, key="us_trade_log_table", height=500, click_nav=False)


def show_portfolio():
    st.title("💼 포트폴리오")
    st.caption("매수/매도 기록 · 보유 현황 · 성과 분석")

    # rerun 후에도 확인 메시지 표시
    if st.session_state.get("portfolio_toast"):
        msg, kind = st.session_state.pop("portfolio_toast")
        if kind == "success":
            st.success(msg)
        elif kind == "error":
            st.error(msg)

    _mkt = st.radio("시장", ["🇰🇷 한국", "🇺🇸 미국"], horizontal=True, label_visibility="collapsed", key="portfolio_market")

    if _mkt == "🇺🇸 미국":
        set_portfolio_file("portfolio_us.json")
        _show_portfolio_us()
        return

    set_portfolio_file("portfolio.json")
    tab_hold, tab_pnl, tab_perf, tab_review, tab_log = st.tabs(["📋 보유 현황", "📊 거래별 성과분석", "📊 종목별 성과분석", "📅 월별 리뷰", "📜 거래 이력"])

    # ── 보유 현황 ─────────────────────────────
    with tab_hold:
        df_pos = get_open_positions()

        # 현재가 조회 버튼
        if st.button("🔄 현재가 조회"):
            prices = {}
            with st.spinner("현재가 조회 중..."):
                for _, row in df_pos.iterrows():
                    prices[row["종목코드"]] = _fetch_current_price(row["종목코드"])
            st.session_state["portfolio_prices"] = prices

        prices = st.session_state.get("portfolio_prices", {})

        if df_pos.empty:
            st.info("보유 중인 종목이 없습니다.")
        else:
            disp = df_pos.copy()

            # 현재가 관련 컬럼 초기화
            disp["현재가"]   = disp["종목코드"].map(lambda t: prices.get(t, None) if prices else None)
            disp["수익률(%)"] = disp.apply(
                lambda r: round((r["현재가"] - r["평균매수가"]) / r["평균매수가"] * 100, 2)
                          if pd.notna(r["현재가"]) and r["현재가"] > 0 else None, axis=1
            )
            disp["평가금액"] = disp.apply(
                lambda r: round(r["현재가"] * r["수량"]) if pd.notna(r["현재가"]) and r["현재가"] > 0 else None, axis=1
            )
            disp["손절경고"] = disp.apply(
                lambda r: "⚠️ 손절선 이탈" if pd.notna(r["현재가"]) and r["현재가"] > 0 and r["현재가"] <= r["손절가"] else "", axis=1
            )

            # 정렬: 평가금액 있으면 평가금액, 없으면 평균매수가*수량 기준 내림차순
            if disp["평가금액"].notna().any():
                disp = disp.sort_values("평가금액", ascending=False)
            else:
                disp = disp.assign(_sort=disp["평균매수가"] * disp["수량"])\
                           .sort_values("_sort", ascending=False)\
                           .drop(columns=["_sort"])
            disp.index = range(1, len(disp) + 1)

            # 컬럼 순서
            show_cols = ["종목코드", "종목명", "진입근거", "평균매수가", "수량", "손절가",
                         "현재가", "수익률(%)", "평가금액", "매수일", "경과일", "손절경고"]
            disp = disp[[c for c in show_cols if c in disp.columns]]

            _hold_color_map = {"수익률(%)": "blue_positive"}
            _hold_n = len(disp)
            _hold_height = 250 if _hold_n <= 5 else (350 if _hold_n <= 10 else 450)
            _hold_result = _aggrid(
                disp.reset_index().rename(columns={"index": "#"}),
                key="portfolio_hold_table",
                height=_hold_height,
                click_nav=True,
                color_map=_hold_color_map,
                col_widths={
                    "#":        55,
                    "진입근거": 90,
                    "수량":     70,
                    "매수일":   100,
                    "경과일":   75,
                    "수익률(%)": 95,
                    "손절경고": 120,
                },
            )
            _hold_selected = _hold_result["selected_rows"]
            if _hold_selected is not None and len(_hold_selected) > 0:
                _sel = _hold_selected[0]
                st.session_state.view           = "chart"
                st.session_state.chart_ticker   = _sel["종목코드"]
                st.session_state.chart_name     = _sel.get("종목명", "")
                st.session_state.chart_period   = st.session_state.get("chart_period", 20)
                st.session_state.sidebar_ticker = _sel["종목코드"]
                st.session_state.return_to_view = "portfolio"
                st.rerun()

            if prices and disp["평가금액"].notna().any():
                qty_map = df_pos.set_index("종목코드")["수량"]
                total_cost = (df_pos["평균매수가"] * df_pos["수량"]).sum()
                total_eval = disp["평가금액"].sum()
                total_pnl_unreal = total_eval - total_cost
                total_ret  = total_pnl_unreal / total_cost * 100 if total_cost > 0 else 0
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("총 투자금액", f"{total_cost:,.0f}원")
                c2.metric("총 평가금액", f"{total_eval:,.0f}원")
                c3.metric("평가손익", f"{total_pnl_unreal:+,.0f}원",
                          delta_color="normal" if total_pnl_unreal >= 0 else "inverse")
                c4.metric("전체 수익률", f"{total_ret:+.2f}%",
                          delta_color="normal" if total_ret >= 0 else "inverse")

        st.divider()

        # ── 매수 입력 ──
        with st.expander("➕ 매수 입력", expanded=st.session_state.get("buy_expander_open", False)):
            # KRX 종목 검색 (폼 외부 - 선택 시 코드/종목명 자동입력)
            krx_df = load_krx_listing()
            krx_options = [""] + [f"{row['Name']}  ({row['Code']})" for _, row in krx_df.iterrows()]

            def _on_buy_search():
                val = st.session_state.get("buy_stock_search", "")
                if val:
                    code = val.rsplit("(", 1)[-1].rstrip(")")
                    name = val.rsplit("  (", 1)[0]
                    st.session_state["buy_ticker"] = code
                    st.session_state["buy_name"] = name
                st.session_state["buy_expander_open"] = True

            st.selectbox("종목 검색 (KRX)", krx_options, key="buy_stock_search",
                         on_change=_on_buy_search, index=0,
                         help="종목명 또는 코드로 검색 → 아래 코드/종목명 자동입력")

            def _on_reason_change():
                st.session_state["buy_expander_open"] = True
            _reason_col, _ = st.columns([1, 2])
            _reason_col.selectbox("진입근거", ["PB", "HB", "BO"],
                                  key="buy_reason_type_outer", on_change=_on_reason_change)
            _is_bo = st.session_state.get("buy_reason_type_outer", "PB") == "BO"

            with st.form("buy_form", clear_on_submit=False):
                c1, c2, c3 = st.columns(3)
                buy_ticker = c1.text_input("종목코드", key="buy_ticker").strip()
                buy_name   = c2.text_input("종목명",   key="buy_name").strip()
                buy_date   = c3.date_input("매수일", value=datetime.now().date(), key="buy_date")

                c4, c5, c6, c7 = st.columns(4)
                buy_price  = c4.number_input("매수가 (원)", min_value=0, step=100, key="buy_price")
                buy_qty    = c5.number_input("수량 (주)",   min_value=1, step=1,   key="buy_qty")
                buy_stop   = c6.number_input("손절가 (원)", min_value=0, step=100, key="buy_stop")
                buy_tp     = c7.number_input("1차익절가 (원)", min_value=0, step=100, key="buy_tp")

                if _is_bo:
                    buy_memo = st.text_input("메모", key="buy_memo")
                    ma_num   = None
                else:
                    c8, c9 = st.columns([1, 2])
                    ma_num   = c8.selectbox("기준 이동평균", [5, 20, 60, 100, 120, 200], index=1, key="buy_ma")
                    buy_memo = c9.text_input("메모", key="buy_memo")

                if st.form_submit_button("✅ 매수 저장", type="primary"):
                    reason_type  = st.session_state.get("buy_reason_type_outer", "PB")
                    entry_reason = "BO" if reason_type == "BO" else f"{reason_type}{ma_num}"
                    if not buy_ticker or not buy_name or buy_price <= 0:
                        st.error("종목코드, 종목명, 매수가를 입력해주세요.")
                    else:
                        add_buy(
                            ticker=buy_ticker, name=buy_name,
                            date=buy_date.strftime("%Y-%m-%d"),
                            price=buy_price, quantity=int(buy_qty),
                            stop_loss=buy_stop, entry_reason=entry_reason, memo=buy_memo,
                            take_profit=buy_tp,
                        )
                        st.session_state["portfolio_toast"] = (f"✅ {buy_name} 매수 저장 완료!", "success")
                        st.session_state["buy_expander_open"] = True
                        # 폼 필드 초기화 (다음 입력 준비)
                        for k in ["buy_ticker", "buy_name", "buy_price", "buy_qty", "buy_stop", "buy_tp", "buy_memo", "buy_stock_search"]:
                            if k in st.session_state:
                                del st.session_state[k]
                        st.rerun()

        # ── 매도 입력 ──
        with st.expander("➖ 매도 입력"):
            df_pos2 = get_open_positions()
            if df_pos2.empty:
                st.info("보유 중인 종목이 없습니다.")
            else:
                choices = {
                    f"{r['종목명']} ({r['종목코드']}) — {r['수량']}주 보유": r["position_id"]
                    for _, r in df_pos2.iterrows()
                }
                with st.form("sell_form"):
                    sel    = st.selectbox("종목 선택", list(choices.keys()))
                    pos_id = choices[sel]

                    c1, c2, c3 = st.columns(3)
                    sell_date  = c1.date_input("매도일", value=datetime.now().date())
                    sell_price = c2.number_input("매도가 (원)", min_value=0, step=100)
                    sell_qty   = c3.number_input("수량 (주)",   min_value=1, step=1)

                    _SELL_REASONS = ["+20%익절", "일중반전", "전고점전축소", "MA20돌파", "MA60돌파", "손절", "기타"]
                    c4, c5 = st.columns([1, 2])
                    sell_reason_type = c4.selectbox("매도 사유", _SELL_REASONS)
                    sell_reason_memo = c5.text_input("메모", placeholder="추가 메모 (선택)")

                    submitted = st.form_submit_button("✅ 매도 저장", type="primary")

                if submitted:
                    sell_reason = f"{sell_reason_type}" + (f" — {sell_reason_memo}" if sell_reason_memo else "")
                    if sell_price <= 0:
                        st.error("매도가를 입력해주세요.")
                    else:
                        add_sell(
                            position_id=pos_id,
                            date=sell_date.strftime("%Y-%m-%d"),
                            price=sell_price, quantity=int(sell_qty),
                            reason=sell_reason,
                        )
                        st.session_state.pop("portfolio_prices", None)
                        st.session_state["portfolio_toast"] = ("✅ 매도 저장 완료!", "success")
                        st.rerun()

        # ── 손절가 수정 ──
        with st.expander("✏️ 손절가 수정"):
            df_pos3 = get_open_positions()
            if df_pos3.empty:
                st.info("보유 중인 종목이 없습니다.")
            else:
                choices2 = {
                    f"{r['종목명']} ({r['종목코드']}) — 현재 손절가 {r['손절가']:,.0f}원": r["position_id"]
                    for _, r in df_pos3.iterrows()
                }
                with st.form("sl_form"):
                    sel2    = st.selectbox("종목 선택", list(choices2.keys()))
                    pos_id2 = choices2[sel2]

                    c1, c2, c3 = st.columns(3)
                    sl_date  = c1.date_input("수정일", value=datetime.now().date())
                    sl_price = c2.number_input("새 손절가 (원)", min_value=0, step=100)
                    sl_note  = c3.text_input("메모", placeholder="예: 1차 상승 후 이동")

                    sl_submitted = st.form_submit_button("✅ 손절가 저장", type="primary")

                if sl_submitted:
                    if sl_price <= 0:
                        st.error("새 손절가를 입력해주세요.")
                    else:
                        update_stop_loss(pos_id2, sl_date.strftime("%Y-%m-%d"), sl_price, sl_note)
                        st.session_state["portfolio_toast"] = ("✅ 손절가 수정 완료!", "success")
                        st.rerun()

        # ── 1차 익절가 수정 ──
        with st.expander("✏️ 1차 익절가 수정"):
            df_pos_tp_kr = get_open_positions()
            if df_pos_tp_kr.empty:
                st.info("보유 중인 종목이 없습니다.")
            else:
                _tp_choices_kr = {
                    f"{r['종목명']} ({r['종목코드']}) — 현재 익절가 {r['1차익절가']:,.0f}원" if r['1차익절가'] else
                    f"{r['종목명']} ({r['종목코드']}) — 미설정": r["position_id"]
                    for _, r in df_pos_tp_kr.iterrows()
                }
                with st.form("kr_tp_form"):
                    _tp_sel_kr = st.selectbox("종목 선택", list(_tp_choices_kr.keys()), key="kr_tp_sel")
                    _tp_pos_id_kr = _tp_choices_kr[_tp_sel_kr]
                    _tp_price_kr = st.number_input("1차 익절가 (원)", min_value=0, step=100, key="kr_tp_price")
                    _kr_tp_submitted = st.form_submit_button("✅ 익절가 저장", type="primary")

                if _kr_tp_submitted:
                    if _tp_price_kr <= 0:
                        st.error("1차 익절가를 입력해주세요.")
                    else:
                        update_take_profit(_tp_pos_id_kr, _tp_price_kr)
                        st.session_state["portfolio_toast"] = ("✅ 1차 익절가 수정 완료!", "success")
                        st.rerun()

        # ── 거래 내역 수정/삭제 ──
        with st.expander("🔧 거래 내역 수정/삭제"):
            import json as _json
            import portfolio as _pf_module
            _pf_data = _json.loads(_pf_module.PORTFOLIO_FILE.read_text(encoding="utf-8")) if _pf_module.PORTFOLIO_FILE.exists() else {}
            _all_pos = _pf_data.get("positions", [])

            if not _all_pos:
                st.info("포지션이 없습니다.")
            else:
                _pos_choices = {
                    f"{p['name']} ({p['ticker']}) [{p['status']}]": p
                    for p in _all_pos
                }
                _sel_name = st.selectbox("종목 선택", list(_pos_choices.keys()), key="edit_pos_select")
                _sel_pos  = _pos_choices[_sel_name]
                _pos_id   = _sel_pos["id"]
                _trades   = _sel_pos.get("trades", [])

                if not _trades:
                    st.info("거래 내역이 없습니다.")
                else:
                    st.markdown("**거래 목록** — 수정하려면 행을 선택하세요")
                    for _tr in _trades:
                        _label = (
                            f"{'🟢 매수' if _tr['type']=='buy' else '🔴 매도'}  "
                            f"{_tr['date']}  {_tr['price']:,}원  {_tr['quantity']}주"
                            + (f"  [{_tr.get('entry_reason','')}]" if _tr['type']=='buy' else "")
                            + (f"  {_tr.get('memo','') or _tr.get('reason','')}"[:20] if (_tr.get('memo') or _tr.get('reason')) else "")
                        )
                        _col1, _col2 = st.columns([8, 1])
                        _col1.markdown(_label)
                        if _col2.button("🗑️", key=f"del_trade_{_tr['id']}", help="삭제"):
                            delete_trade(_pos_id, _tr["id"])
                            st.session_state["portfolio_toast"] = ("✅ 거래 내역이 삭제되었습니다.", "success")
                            st.rerun()

                    st.markdown("---")
                    st.markdown("**수정할 거래 선택**")
                    _trade_labels = {
                        f"{'매수' if t['type']=='buy' else '매도'} | {t['date']} | {t['price']:,}원 | {t['quantity']}주": t
                        for t in _trades
                    }
                    _edit_label = st.selectbox("거래 선택", list(_trade_labels.keys()), key="edit_trade_select")
                    _edit_tr    = _trade_labels[_edit_label]

                    _eid = _edit_tr["id"]
                    _ec1, _ec2, _ec3 = st.columns(3)
                    _e_date = _ec1.date_input("날짜", value=datetime.strptime(_edit_tr["date"], "%Y-%m-%d").date(), key=f"edit_date_{_eid}")
                    _e_price = _ec2.number_input("가격 (원)", value=int(_edit_tr["price"]), min_value=0, step=100, key=f"edit_price_{_eid}")
                    _e_qty   = _ec3.number_input("수량 (주)", value=int(_edit_tr["quantity"]), min_value=1, step=1, key=f"edit_qty_{_eid}")

                    if _edit_tr["type"] == "buy":
                        _ec4, _ec5, _ec6 = st.columns(3)
                        _e_stop = _ec4.number_input("손절가 (원)", value=int(_edit_tr.get("stop_loss", 0)), min_value=0, step=100, key=f"edit_stop_{_eid}")
                        _e_reason = _ec5.text_input("진입근거", value=_edit_tr.get("entry_reason", ""), key=f"edit_reason_{_eid}")
                        _e_memo   = _ec6.text_input("메모", value=_edit_tr.get("memo", ""), key=f"edit_memo_{_eid}")
                    else:
                        _SELL_REASONS = ["+20%익절", "일중반전", "전고점전축소", "MA20돌파", "MA60돌파", "손절", "기타"]
                        _cur_reason = _edit_tr.get("reason", "")
                        _cur_type   = next((r for r in _SELL_REASONS if _cur_reason.startswith(r)), "기타")
                        _cur_memo   = _cur_reason.split(" — ", 1)[1] if " — " in _cur_reason else ""
                        _er1, _er2  = st.columns([1, 2])
                        _e_reason_type = _er1.selectbox("매도 사유", _SELL_REASONS, index=_SELL_REASONS.index(_cur_type), key=f"edit_sell_reason_type_{_eid}")
                        _e_reason_memo = _er2.text_input("메모", value=_cur_memo, key=f"edit_sell_reason_memo_{_eid}")
                        _e_sell_reason = f"{_e_reason_type}" + (f" — {_e_reason_memo}" if _e_reason_memo else "")

                    if st.button("💾 수정 저장", type="primary", key="edit_save_btn"):
                        _fields = {
                            "date":     _e_date.strftime("%Y-%m-%d"),
                            "price":    _e_price,
                            "quantity": int(_e_qty),
                        }
                        if _edit_tr["type"] == "buy":
                            _fields["stop_loss"]    = _e_stop
                            _fields["entry_reason"] = _e_reason
                            _fields["memo"]         = _e_memo
                        else:
                            _fields["reason"] = _e_sell_reason
                        update_trade(_pos_id, _edit_tr["id"], _fields)
                        st.session_state["portfolio_toast"] = ("✅ 거래 내역이 수정되었습니다.", "success")
                        st.rerun()

        # ── 손절가 이력 ──
        with st.expander("📋 손절가 변경 이력"):
            df_pos4 = get_open_positions()
            if df_pos4.empty:
                st.info("보유 중인 종목이 없습니다.")
            else:
                choices3 = {
                    f"{r['종목명']} ({r['종목코드']})": r["position_id"]
                    for _, r in df_pos4.iterrows()
                }
                sel3    = st.selectbox("종목 선택", list(choices3.keys()), key="slh_select")
                pos_id3 = choices3[sel3]
                df_hist = get_stop_loss_history(pos_id3)
                if df_hist.empty:
                    st.info("이력이 없습니다.")
                else:
                    _aggrid(df_hist, key="stop_loss_history", height=250, click_nav=False)

        # ── 원금 입출금 관리 ──
        with st.expander("⚙️ 원금 입출금 관리", expanded=(get_total_capital() == 0)):
            c1, c2, c3 = st.columns(3)
            flow_date   = c1.date_input("날짜", value=datetime.now().date(), key="flow_date")
            flow_type   = c2.selectbox("구분", ["입금", "출금"], key="flow_type")
            flow_amount = c3.number_input("금액 (원)", min_value=0, step=1000000, key="flow_amount")
            flow_note   = st.text_input("메모", key="flow_note", placeholder="예: 초기 원금 / 추가 투자 / 일부 인출")
            if st.button("✅ 저장", key="flow_save"):
                if flow_amount <= 0:
                    st.error("금액을 입력해주세요.")
                else:
                    signed = float(flow_amount) if flow_type == "입금" else -float(flow_amount)
                    add_capital_flow(flow_date.strftime("%Y-%m-%d"), signed, flow_note)
                    st.success("저장 완료!")
                    st.rerun()

            df_flows = get_capital_flows()
            if not df_flows.empty:
                st.caption(f"현재 원금 합계: **{get_total_capital():,.0f}원**")
                for _, row in df_flows.iterrows():
                    col_a, col_b, col_c, col_d = st.columns([2, 3, 3, 1])
                    col_a.write(row.get("날짜", ""))
                    amount = row.get("금액(원)", 0)
                    col_b.write(f"{amount:+,.0f}원")
                    col_c.write(row.get("메모", ""))
                    flow_id = row.get("id", "")
                    if flow_id and col_d.button("🗑️", key=f"del_flow_{flow_id}"):
                        delete_capital_flow(flow_id)
                        st.rerun()

    # ── 거래별 성과분석 ────────────────────────
    with tab_pnl:
        df_pnl = get_realized_pnl()
        if df_pnl.empty:
            st.info("실현된 손익이 없습니다. 매도 후 확인하세요.")
        else:
            df_pnl["_buy_cost"] = df_pnl["평균매수가"] * df_pnl["수량"]
            df_pnl["_월"] = pd.to_datetime(df_pnl["날짜"]).dt.to_period("M").astype(str)
            df_pnl["_연도"] = pd.to_datetime(df_pnl["날짜"]).dt.year.astype(str)

            _pnl_years = sorted(df_pnl["_연도"].unique(), reverse=True)
            _pnl_period_opts = ["전체"] + _pnl_years
            _cur_year = datetime.now().strftime("%Y")
            _pnl_year_idx = _pnl_period_opts.index(_cur_year) if _cur_year in _pnl_period_opts else 0
            _pnl_sel_year = st.selectbox("기간 선택", _pnl_period_opts, index=_pnl_year_idx, key="kr_pnl_year")

            if _pnl_sel_year == "전체":
                _pnl_filtered = df_pnl
                _pnl_sel_month = None
            else:
                _pnl_year_df = df_pnl[df_pnl["_연도"] == _pnl_sel_year]
                _pnl_month_opts = ["연간 전체"] + sorted(_pnl_year_df["_월"].unique(), reverse=True)
                _cur_month = datetime.now().strftime("%Y-%m")
                _pnl_month_idx = _pnl_month_opts.index(_cur_month) if _cur_month in _pnl_month_opts else 0
                _pnl_sel_month = st.selectbox("월 선택", _pnl_month_opts, index=_pnl_month_idx, key="kr_pnl_month")
                if _pnl_sel_month == "연간 전체":
                    _pnl_filtered = _pnl_year_df
                    _pnl_sel_month = None
                else:
                    _pnl_filtered = _pnl_year_df[_pnl_year_df["_월"] == _pnl_sel_month]

            _pnl_label = _pnl_sel_year if _pnl_sel_year != "전체" else "전체"
            if _pnl_sel_month:
                _pnl_label = _pnl_sel_month

            def _render_trade_kpi(df_sub, currency="원"):
                n = len(df_sub)
                if n == 0:
                    st.info("해당 기간에 거래가 없습니다.")
                    return
                wins = df_sub[df_sub["수익률(%)"] > 0]
                losses = df_sub[df_sub["수익률(%)"] <= 0]
                win_rate = len(wins) / n * 100
                avg_planned_loss = losses["목표손절률(%)"].dropna().mean() if len(losses) > 0 else None
                losses_wt = losses.dropna(subset=["목표손절률(%)"])
                violations = losses_wt[losses_wt["수익률(%)"] < losses_wt["목표손절률(%)"]]
                n_violations = len(violations)
                violation_rate = n_violations / len(losses_wt) * 100 if len(losses_wt) > 0 else 0
                total_inv = df_sub["_buy_cost"].sum()
                total_pnl = df_sub["실현손익(원)"].sum()
                total_fees = df_sub["거래비용(원)"].sum() if "거래비용(원)" in df_sub.columns else 0
                total_net = df_sub["비용차감손익(원)"].sum() if "비용차감손익(원)" in df_sub.columns else total_pnl
                _w_wins = wins["수익률(%)"].values * wins["_buy_cost"].values if len(wins) > 0 else []
                _w_losses = losses["수익률(%)"].values * losses["_buy_cost"].values if len(losses) > 0 else []
                avg_win = _w_wins.sum() / wins["_buy_cost"].sum() if len(wins) > 0 and wins["_buy_cost"].sum() > 0 else 0
                avg_loss = _w_losses.sum() / losses["_buy_cost"].sum() if len(losses) > 0 and losses["_buy_cost"].sum() > 0 else 0
                avg_ret = (df_sub["수익률(%)"].values * df_sub["_buy_cost"].values).sum() / df_sub["_buy_cost"].sum() if df_sub["_buy_cost"].sum() > 0 else 0
                initial_capital = get_total_capital()
                turnover = total_inv / initial_capital if initial_capital > 0 else None
                capital_ret = (total_pnl / initial_capital * 100) if initial_capital > 0 else None
                rr_vals = df_sub["RR"].dropna()
                avg_rr = rr_vals.mean() if len(rr_vals) > 0 else None
                avg_hold_win = wins["보유일수"].dropna().mean() if len(wins) > 0 else None
                avg_hold_loss = losses["보유일수"].dropna().mean() if len(losses) > 0 else None

                c1, c2, c3 = st.columns(3)
                c1.metric(f"총 실현손익 (비용차감)", f"{total_net:+,.0f}{currency}",
                          delta=f"거래비용 {total_fees:,.0f}{currency}", delta_color="inverse")
                c2.metric("거래 건수", f"{n}건")
                c3.metric("승/패", f"{len(wins)}승 {len(losses)}패")
                c4, c5, c6 = st.columns(3)
                c4.metric("승률", f"{win_rate:.1f}%")
                c5.metric("승리 시 평균수익률", f"{avg_win:+.2f}%")
                if avg_planned_loss is not None:
                    _diff1 = avg_loss - avg_planned_loss
                    _delta1_txt = f"목표보다 {abs(_diff1):.2f}%p 절약 ✓" if _diff1 > 0 else f"목표보다 {abs(_diff1):.2f}%p 초과"
                else:
                    _delta1_txt = None
                c6.metric("패배 시 평균손실률", f"{avg_loss:+.2f}%",
                          delta=_delta1_txt, delta_color="normal")
                c4b, c5b, c6b = st.columns(3)
                c4b.metric("목표손절 위반 횟수", f"{n_violations}회")
                c5b.metric("목표손절 위반율", f"{violation_rate:.1f}%")
                c6b.metric("패배 시 평균목표손절률", f"{avg_planned_loss:.2f}%" if avg_planned_loss is not None else "-")
                c7, c8, c9 = st.columns(3)
                c7.metric("전체 평균수익률 (가중)", f"{avg_ret:+.2f}%")
                c8.metric("자산회전율", f"{turnover:.2f}배" if turnover is not None else "원금 미설정")
                c9.metric("원금대비 실현수익률", f"{capital_ret:+.2f}%" if capital_ret is not None else "원금 미설정")
                c10, c11, c12 = st.columns(3)
                c10.metric("평균 RR", f"{avg_rr:.2f}" if avg_rr is not None else "-")
                c11.metric("수익 시 평균보유기간", f"{avg_hold_win:.0f}일" if avg_hold_win is not None else "-")
                c12.metric("손실 시 평균보유기간", f"{avg_hold_loss:.0f}일" if avg_hold_loss is not None else "-")

            _render_trade_kpi(_pnl_filtered)

            # ── 월별 KPI 비교표 (전체/연간 선택 시) ──
            if not _pnl_sel_month and len(_pnl_filtered) > 0:
                _months_in_range = sorted(_pnl_filtered["_월"].unique())
                if len(_months_in_range) > 1:
                    st.divider()
                    st.subheader(f"월별 KPI 비교 ({_pnl_label})")
                    _monthly_kpi_rows = []
                    _init_cap = get_total_capital()
                    for _m in _months_in_range:
                        _m_df = _pnl_filtered[_pnl_filtered["_월"] == _m]
                        _mn = len(_m_df)
                        if _mn == 0:
                            continue
                        _mw = _m_df[_m_df["수익률(%)"] > 0]
                        _ml = _m_df[_m_df["수익률(%)"] <= 0]
                        _m_bc = _m_df["_buy_cost"].sum()
                        _m_avg_win = (_mw["수익률(%)"].values * (_mw["평균매수가"] * _mw["수량"]).values).sum() / (_mw["평균매수가"] * _mw["수량"]).sum() if len(_mw) > 0 and (_mw["평균매수가"] * _mw["수량"]).sum() > 0 else 0
                        _m_avg_loss = (_ml["수익률(%)"].values * (_ml["평균매수가"] * _ml["수량"]).values).sum() / (_ml["평균매수가"] * _ml["수량"]).sum() if len(_ml) > 0 and (_ml["평균매수가"] * _ml["수량"]).sum() > 0 else 0
                        _m_avg = (_m_df["수익률(%)"].values * _m_df["_buy_cost"].values).sum() / _m_bc if _m_bc > 0 else 0
                        _m_pnl = _m_df["실현손익(원)"].sum()
                        _m_fees = _m_df["거래비용(원)"].sum() if "거래비용(원)" in _m_df.columns else 0
                        _m_net = _m_df["비용차감손익(원)"].sum() if "비용차감손익(원)" in _m_df.columns else _m_pnl
                        _m_rr = _m_df["RR"].dropna().mean() if _m_df["RR"].dropna().any() else None
                        _m_planned = _ml["목표손절률(%)"].dropna().mean() if len(_ml) > 0 else None
                        _m_lwt = _ml.dropna(subset=["목표손절률(%)"])
                        _m_viols = len(_m_lwt[_m_lwt["수익률(%)"] < _m_lwt["목표손절률(%)"]]) if len(_m_lwt) > 0 else 0
                        _m_viol_rate = _m_viols / len(_m_lwt) * 100 if len(_m_lwt) > 0 else 0
                        _m_turnover = _m_bc / _init_cap if _init_cap > 0 else None
                        _m_cap_ret = (_m_pnl / _init_cap * 100) if _init_cap > 0 else None
                        _m_hold_win = _mw["보유일수"].dropna().mean() if len(_mw) > 0 else None
                        _m_hold_loss = _ml["보유일수"].dropna().mean() if len(_ml) > 0 else None
                        _monthly_kpi_rows.append({
                            "월": _m,
                            "거래수": _mn,
                            "승/패": f"{len(_mw)}/{len(_ml)}",
                            "승률(%)": round(len(_mw) / _mn * 100, 1),
                            "승리평균(%)": round(_m_avg_win, 2),
                            "패배평균(%)": round(_m_avg_loss, 2),
                            "전체평균(%)": round(_m_avg, 2),
                            "평균RR": round(_m_rr, 2) if _m_rr is not None else None,
                            "손절위반": _m_viols,
                            "위반율(%)": round(_m_viol_rate, 1),
                            "회전율": round(_m_turnover, 2) if _m_turnover is not None else None,
                            "원금대비(%)": round(_m_cap_ret, 2) if _m_cap_ret is not None else None,
                            "승리보유일": round(_m_hold_win, 0) if _m_hold_win is not None else None,
                            "손실보유일": round(_m_hold_loss, 0) if _m_hold_loss is not None else None,
                            "비용차감손익(원)": int(_m_net),
                        })
                    if _monthly_kpi_rows:
                        _mkpi_df = pd.DataFrame(_monthly_kpi_rows)
                        _aggrid(_mkpi_df, key=f"kr_monthly_kpi_compare_{_pnl_label}", height=min(300, 60 + len(_mkpi_df) * 40),
                                color_map={"전체평균(%)": "red_positive", "승리평균(%)": "red_positive", "패배평균(%)": "red_positive", "비용차감손익(원)": "red_positive", "원금대비(%)": "red_positive"},
                                pct_cols=["승률(%)", "승리평균(%)", "패배평균(%)", "전체평균(%)", "위반율(%)", "원금대비(%)"],
                                price_cols=["비용차감손익(원)"])

            st.divider()

            _pnl_color_map = {"실현손익(원)": "red_positive", "비용차감손익(원)": "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
            _aggrid(_pnl_filtered, key=f"trade_pnl_table_{_pnl_label}", height=450, click_nav=False, color_map=_pnl_color_map, pct_cols=["수익률(%)", "비용차감수익률(%)"])

            st.divider()

            # ── 누적 수익 곡선 ──
            st.subheader(f"누적 수익 곡선 ({_pnl_label})")
            _render_equity_curve(source_df=_pnl_filtered)

            st.divider()

            # ── 월별 성과 (전체/연간 선택 시만 표시, 월별 선택 시 불필요) ──
            if not _pnl_sel_month:
                st.subheader(f"월별 성과 ({_pnl_label})")
                _render_monthly_performance(source_df=_pnl_filtered)

            # 수익률 분포도
            _render_return_distribution(_pnl_filtered, _pnl_label, "kr")

    # ── 종목별 성과분석 ───────────────────────
    with tab_perf:
        df_pos_pnl = get_position_pnl()
        if df_pos_pnl.empty:
            st.info("완전 청산된 종목이 없습니다.")
        else:
            initial_capital_p = get_total_capital()

            def _kpi_metrics(df_sub, label="전체"):
                """df_sub 기준 KPI dict 반환"""
                n       = len(df_sub)
                wins    = df_sub[df_sub["수익률(%)"] > 0]
                losses  = df_sub[df_sub["수익률(%)"] <= 0]
                total_inv  = (df_sub["평균매수가"] * df_sub["청산수량"]).sum()
                total_pnl  = df_sub["실현손익(원)"].sum()
                total_fees = df_sub["거래비용(원)"].sum() if "거래비용(원)" in df_sub.columns else 0
                total_net  = df_sub["비용차감손익(원)"].sum() if "비용차감손익(원)" in df_sub.columns else total_pnl
                # 금액 가중 평균수익률
                df_sub = df_sub.copy()
                df_sub["_buy_cost"] = df_sub["평균매수가"] * df_sub["청산수량"]
                _bc_total = df_sub["_buy_cost"].sum()
                wins_bc   = wins["평균매수가"] * wins["청산수량"] if len(wins) > 0 else None
                losses_bc = losses["평균매수가"] * losses["청산수량"] if len(losses) > 0 else None
                avg_win   = (wins["수익률(%)"].values * wins_bc.values).sum() / wins_bc.sum()       if wins_bc is not None and wins_bc.sum() > 0   else 0
                avg_loss  = (losses["수익률(%)"].values * losses_bc.values).sum() / losses_bc.sum() if losses_bc is not None and losses_bc.sum() > 0 else 0
                avg_ret   = (df_sub["수익률(%)"].values * df_sub["_buy_cost"].values).sum() / _bc_total if _bc_total > 0 else 0
                avg_planned_loss_p = losses["목표손절률(%)"].dropna().mean() if len(losses) > 0 else None
                losses_wt = losses.dropna(subset=["목표손절률(%)"])
                viols = losses_wt[losses_wt["수익률(%)"] < losses_wt["목표손절률(%)"]]
                n_viols    = len(viols)
                viol_rate  = n_viols / len(losses_wt) * 100 if len(losses_wt) > 0 else 0
                turnover    = total_inv / initial_capital_p if initial_capital_p > 0 else None
                adj_ret     = avg_ret * turnover if turnover is not None else None
                capital_ret = (total_pnl / initial_capital_p * 100) if initial_capital_p > 0 else None
                avg_rr    = df_sub["RR"].dropna().mean() if df_sub["RR"].dropna().any() else None
                avg_hold_win  = wins["보유일수"].dropna().mean()   if len(wins)   > 0 else None
                avg_hold_loss = losses["보유일수"].dropna().mean() if len(losses) > 0 else None
                return {
                    "종목수":               n,
                    "승/패":               f"{len(wins)}승 {len(losses)}패",
                    "승률(%)":             round(len(wins)/n*100, 1) if n > 0 else 0,
                    "승리 평균수익률(%)":   round(avg_win,  2),
                    "패배 평균손실률(%)":   round(avg_loss, 2),
                    "패배 평균목표손절률(%)": round(avg_planned_loss_p, 2) if avg_planned_loss_p is not None else "-",
                    "목표손절 위반 횟수":    n_viols,
                    "목표손절 위반율(%)":    round(viol_rate, 1),
                    "전체 평균수익률(%)":   round(avg_ret,  2),
                    "자산회전율":          round(turnover, 2) if turnover is not None else "-",
                    "원금대비수익률(%)":    round(capital_ret, 2) if capital_ret is not None else "-",
                    "평균RR":              round(avg_rr, 2) if avg_rr is not None else "-",
                    "수익시 평균보유일":    round(avg_hold_win,  0) if avg_hold_win  is not None else "-",
                    "손실시 평균보유일":    round(avg_hold_loss, 0) if avg_hold_loss is not None else "-",
                    "총 실현손익(원)":      round(total_pnl),
                    "거래비용(원)":         round(total_fees),
                    "비용차감손익(원)":     round(total_net),
                }

            # ── 기간 선택 ──
            df_pos_pnl_c = df_pos_pnl.copy()
            df_pos_pnl_c["청산월"] = pd.to_datetime(df_pos_pnl_c["청산일"]).dt.to_period("M").astype(str)
            df_pos_pnl_c["청산연도"] = pd.to_datetime(df_pos_pnl_c["청산일"]).dt.year.astype(str)

            _years = sorted(df_pos_pnl_c["청산연도"].unique(), reverse=True)
            _period_options = ["전체"] + _years
            _cur_year = datetime.now().strftime("%Y")
            _perf_year_idx = _period_options.index(_cur_year) if _cur_year in _period_options else 0
            _sel_year = st.selectbox("기간 선택", _period_options, index=_perf_year_idx, key="kr_perf_year")

            if _sel_year == "전체":
                _perf_df = df_pos_pnl_c
                _sel_month_perf = None
            else:
                _year_df = df_pos_pnl_c[df_pos_pnl_c["청산연도"] == _sel_year]
                _month_options = ["연간 전체"] + sorted(_year_df["청산월"].unique(), reverse=True)
                _cur_month = datetime.now().strftime("%Y-%m")
                _perf_month_idx = _month_options.index(_cur_month) if _cur_month in _month_options else 0
                _sel_month_perf = st.selectbox("월 선택", _month_options, index=_perf_month_idx, key="kr_perf_month")
                if _sel_month_perf == "연간 전체":
                    _perf_df = _year_df
                    _sel_month_perf = None
                else:
                    _perf_df = _year_df[_year_df["청산월"] == _sel_month_perf]

            _period_label = _sel_year if _sel_year != "전체" else "전체"
            if _sel_month_perf:
                _period_label = _sel_month_perf

            def _render_kpi_cards(kpi, currency="원"):
                """KPI 카드 렌더링"""
                c1, c2, c3 = st.columns(3)
                c1.metric("총 실현손익 (비용차감)", f"{kpi['비용차감손익(원)']:+,.0f}{currency}",
                          delta=f"거래비용 {kpi['거래비용(원)']:,.0f}{currency}", delta_color="inverse")
                c2.metric("종목 수", f"{kpi['종목수']}종목")
                c3.metric("승/패", kpi["승/패"])
                _pl = kpi["패배 평균목표손절률(%)"]
                _al = kpi["패배 평균손실률(%)"]
                if _pl != "-":
                    _diff2 = _al - _pl
                    _delta2_txt = f"목표보다 {abs(_diff2):.2f}%p 절약 ✓" if _diff2 > 0 else f"목표보다 {abs(_diff2):.2f}%p 초과"
                else:
                    _delta2_txt = None
                c4, c5, c6 = st.columns(3)
                c4.metric("승률", f"{kpi['승률(%)']:.1f}%")
                c5.metric("승리 시 평균수익률", f"{kpi['승리 평균수익률(%)']:+.2f}%")
                c6.metric("패배 시 평균손실률", f"{kpi['패배 평균손실률(%)']:+.2f}%",
                          delta=_delta2_txt, delta_color="normal")
                c4b, c5b, c6b = st.columns(3)
                c4b.metric("목표손절 위반 횟수", f"{kpi['목표손절 위반 횟수']}회")
                c5b.metric("목표손절 위반율", f"{kpi['목표손절 위반율(%)']:.1f}%")
                c6b.metric("패배 시 평균목표손절률", f"{_pl:.2f}%" if _pl != "-" else "-")
                c7, c8, c9 = st.columns(3)
                c7.metric("전체 평균수익률 (가중)", f"{kpi['전체 평균수익률(%)']:+.2f}%")
                c8.metric("자산회전율", f"{kpi['자산회전율']:.2f}배" if kpi['자산회전율'] != "-" else "원금 미설정")
                c9.metric("원금대비 실현수익률", f"{kpi['원금대비수익률(%)']:+.2f}%" if kpi['원금대비수익률(%)'] != "-" else "원금 미설정")
                c10, c11, c12 = st.columns(3)
                c10.metric("평균 RR", f"{kpi['평균RR']:.2f}" if kpi['평균RR'] != "-" else "-")
                c11.metric("수익 시 평균보유기간", f"{kpi['수익시 평균보유일']:.0f}일" if kpi['수익시 평균보유일'] != "-" else "-")
                c12.metric("손실 시 평균보유기간", f"{kpi['손실시 평균보유일']:.0f}일" if kpi['손실시 평균보유일'] != "-" else "-")

            # ── 1. 성과분석 ──
            if _perf_df.empty:
                st.info(f"{_period_label} 기간에 청산된 종목이 없습니다.")
            else:
                st.subheader(f"1. 성과분석 ({_period_label})")
                overall = _kpi_metrics(_perf_df)
                _render_kpi_cards(overall)

            st.divider()

            # ── 2. 종목별 성과분석 ──
            if not _perf_df.empty:
                st.subheader(f"2. 종목별 성과분석 ({_period_label})")
                _pos_pnl_color_map = {"실현손익(원)": "red_positive", "비용차감손익(원)": "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
                _pos_pnl_n = len(_perf_df)
                _pos_pnl_height = 250 if _pos_pnl_n <= 5 else (350 if _pos_pnl_n <= 10 else 450)
                _aggrid(_perf_df, key=f"position_pnl_table_{_period_label}", height=_pos_pnl_height,
                        click_nav=False, color_map=_pos_pnl_color_map, pct_cols=["수익률(%)", "비용차감수익률(%)"])

            st.divider()

            # ── 3. 진입근거별 성과분석 ──
            if not _perf_df.empty:
                st.subheader(f"3. 진입근거별 성과분석 ({_period_label})")
            reason_rows = []
            for prefix in ["PB", "HB", "BO"]:
                sub = _perf_df[_perf_df["진입근거"].str.startswith(prefix)] if not _perf_df.empty else pd.DataFrame()
                if sub.empty:
                    continue
                row = _kpi_metrics(sub)
                reason_rows.append({"진입근거": prefix, **row})

            if reason_rows:
                df_reason = pd.DataFrame(reason_rows).reset_index(drop=True)
                _reason_color_map = {
                    "승리 평균수익률(%)": "red_positive",
                    "패배 평균손실률(%)": "red_positive",
                    "전체 평균수익률(%)": "red_positive",
                    "원금대비수익률(%)":  "red_positive",
                    "총 실현손익(원)":    "red_positive",
                }
                _aggrid(df_reason, key=f"reason_perf_table_{_period_label}", height=250,
                        click_nav=False, color_map=_reason_color_map)
            else:
                st.info("진입근거별 데이터가 없습니다.")

            st.divider()

            # ── 4. 누적 수익 곡선 ──
            st.subheader("4. 누적 수익 곡선")
            _render_equity_curve(source_df=df_pos_pnl, date_col="청산일")

            st.divider()

            # ── 5. 월별 성과 ──
            st.subheader("5. 월별 성과")
            _render_monthly_performance(source_df=df_pos_pnl, date_col="청산일")

    # ── 월별 리뷰 ─────────────────────────────
    with tab_review:
        _review_df = get_realized_pnl()
        if _review_df.empty:
            st.info("실현 거래가 없습니다.")
        else:
            _review_df_c = _review_df.copy()
            _review_df_c["월"] = pd.to_datetime(_review_df_c["날짜"]).dt.to_period("M").astype(str)
            _months = sorted(_review_df_c["월"].unique(), reverse=True)
            _sel_month = st.selectbox("월 선택", _months, key="kr_review_month")

            review = get_monthly_review(_sel_month)
            if review.get("summary"):
                s = review["summary"]

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("거래수", s["거래수"])
                m2.metric("승률", f"{s['승률(%)']:.1f}%")
                m3.metric("평균수익률", f"{s['평균수익률(%)']:+.2f}%")
                m4.metric("총실현손익", f"{s['총실현손익(원)']:,}원")

                m5, m6, m7, m8 = st.columns(4)
                m5.metric("승리 평균", f"{s['승리 평균(%)']:+.2f}%")
                m6.metric("패배 평균", f"{s['패배 평균(%)']:+.2f}%")
                m7.metric("최대수익", f"{s['최대수익(%)']:+.2f}%")
                m8.metric("최대손실", f"{s['최대손실(%)']:+.2f}%")

                m9, m10 = st.columns(2)
                m9.metric("평균보유일수", f"{s['평균보유일수']:.0f}일")
                if s.get("평균RR") is not None:
                    m10.metric("평균 RR", f"{s['평균RR']:.2f}")

                st.divider()

                if review["by_reason"]:
                    st.subheader("진입근거별 분석")
                    reason_rows = []
                    for reason, stats in review["by_reason"].items():
                        reason_rows.append({
                            "진입근거": reason,
                            "거래수": stats["거래수"],
                            "승률(%)": stats["승률(%)"],
                            "평균수익률(%)": stats["평균수익률(%)"],
                            "승리 평균(%)": stats["승리 평균(%)"],
                            "패배 평균(%)": stats["패배 평균(%)"],
                            "최대수익(%)": stats["최대수익(%)"],
                            "최대손실(%)": stats["최대손실(%)"],
                            "평균보유일(일)": stats["평균보유일수"],
                            "평균RR": stats.get("평균RR", ""),
                            "총손익(원)": stats["총실현손익(원)"],
                        })
                    reason_df = pd.DataFrame(reason_rows)
                    _aggrid(
                        reason_df,
                        key="kr_review_reason",
                        height=min(250, 60 + len(reason_df) * 40),
                        color_map={"평균수익률(%)": "red_positive", "승리 평균(%)": "red_positive", "패배 평균(%)": "red_positive", "총손익(원)": "red_positive"},
                        pct_cols=["승률(%)", "평균수익률(%)", "승리 평균(%)", "패배 평균(%)", "최대수익(%)", "최대손실(%)"],
                        price_cols=["총손익(원)"],
                    )

                st.divider()

                st.subheader("개별 거래 내역")
                trades = review["trades"]
                _trade_cols = ["청산일", "종목명", "진입근거", "수익률(%)", "비용차감손익(원)", "거래비용(원)", "보유일수", "RR"]
                _trade_show = trades[[c for c in _trade_cols if c in trades.columns]]
                _aggrid(
                    _trade_show,
                    key="kr_review_trades",
                    height=min(400, 60 + len(_trade_show) * 35),
                    color_map={"수익률(%)": "red_positive", "비용차감손익(원)": "red_positive"},
                    pct_cols=["수익률(%)"],
                    price_cols=["비용차감손익(원)", "거래비용(원)"],
                )
            else:
                st.info(f"{_sel_month}에 실현 거래가 없습니다.")

    # ── 거래 이력 ─────────────────────────────
    with tab_log:
        df_log = get_trade_log()
        if df_log.empty:
            st.info("거래 이력이 없습니다.")
        else:
            show_cols = [c for c in ["date", "name", "ticker", "type", "price", "quantity",
                                     "entry_reason", "reason", "memo"] if c in df_log.columns]
            rename_map = {
                "date": "날짜", "name": "종목명", "ticker": "종목코드",
                "type": "구분", "price": "가격", "quantity": "수량",
                "entry_reason": "진입근거", "reason": "사유", "memo": "메모",
            }
            disp = df_log[show_cols].rename(columns=rename_map)
            _aggrid(disp, key="trade_log_table", height=500, click_nav=False)


# ══════════════════════════════════════════════════════════
# 뷰 라우팅
# ══════════════════════════════════════════════════════════
def show_backtest():
    st.title("🧪 백테스트")
    st.caption("Strategy Backtest  ·  과거 데이터 기반 전략 검증")

    if st.button("← 홈으로", key="backtest_home_btn"):
        st.session_state.view = "home"
        st.rerun()

    st.divider()

    tab1, tab2, tab3 = st.tabs([
        "1. 신호 백테스트",
        "2. 일중반전 분석",
        "3. 커스텀 전략 백테스트",
    ])

    with tab1:
        st.subheader("신호 백테스트")
        st.caption("진입신호 + 분배신호 동시 적색 발생 시 이후 주가 변동을 검증합니다.")

        # ── 필터 ──
        sc1, sc2, sc3, sc4, _ = st.columns([1, 1, 1, 1, 2])
        with sc1:
            sig_market = st.selectbox("시장", ["KOSPI", "KOSDAQ", "NASDAQ", "NYSE"],
                                      key="sig_bt_market")
        with sc2:
            sig_lookback = st.selectbox("분석 기간", [126, 252, 504],
                                        format_func=lambda d: {126: "6개월", 252: "1년", 504: "2년"}[d],
                                        index=1, key="sig_bt_lookback")
        with sc3:
            sig_fwd = st.selectbox("관찰일", [3, 5, 10, 20],
                                   format_func=lambda d: f"{d}거래일",
                                   index=1, key="sig_bt_fwd")
        with sc4:
            sig_thresh = st.selectbox("적색 기준", [0.5, 0.6, 0.66, 0.75],
                                      format_func=lambda v: f"{v:.0%}",
                                      index=2, key="sig_bt_thresh")

        # ── 캐시 / 실행 ──
        cache_info = get_signal_cache_info(sig_market, sig_lookback)
        sc_run, sc_re, sc_cache = st.columns([1, 1, 4])
        with sc_run:
            sig_run = st.button("분석 실행", key="sig_bt_run", type="primary",
                                use_container_width=True)
        with sc_re:
            sig_rerun = st.button("재계산", key="sig_bt_rerun", use_container_width=True)
        with sc_cache:
            if cache_info:
                st.caption(f"캐시: {cache_info}")

        # ── 실행 ──
        sig_df = None
        if sig_run or sig_rerun:
            prog = st.progress(0, text="신호 백테스트 진행 중...")
            def _sig_prog(done, total):
                prog.progress(done / total, text=f"스캔 중... {done}/{total}")
            sig_df = run_signal_backtest(
                market=sig_market, lookback_days=sig_lookback,
                entry_threshold=sig_thresh, dist_threshold=sig_thresh,
                forward_days=sig_fwd,
                use_cache=(not sig_rerun),
                progress_cb=_sig_prog,
            )
            prog.empty()
            st.session_state["sig_bt_result"] = sig_df
        elif "sig_bt_result" in st.session_state:
            sig_df = st.session_state["sig_bt_result"]

        if sig_df is not None and not sig_df.empty:
            ret_col  = f"{sig_fwd}일수익률(%)"
            gain_col = f"{sig_fwd}일최대상승(%)"
            drop_col = f"{sig_fwd}일최대낙폭(%)"

            # 컬럼 존재 확인 (캐시된 데이터의 forward_days가 다를 수 있음)
            if ret_col not in sig_df.columns:
                st.warning(f"캐시된 데이터의 관찰일이 다릅니다. '재계산' 버튼을 눌러주세요.")
            else:
                n_events = len(sig_df)
                n_down   = (sig_df[ret_col] < 0).sum()
                avg_ret  = sig_df[ret_col].mean()
                med_ret  = sig_df[ret_col].median()
                avg_gain = sig_df[gain_col].mean()
                avg_drop = sig_df[drop_col].mean()

                # ── KPI ──
                k1, k2, k3, k4, k5, k6 = st.columns(6)
                k1.metric("이벤트 수", f"{n_events}건")
                k2.metric("하락 확률", f"{n_down/n_events*100:.1f}%")
                k3.metric(f"평균 {sig_fwd}일 수익률", f"{avg_ret:+.2f}%")
                k4.metric(f"중앙값 수익률", f"{med_ret:+.2f}%")
                k5.metric(f"평균 최대상승", f"{avg_gain:+.2f}%")
                k6.metric(f"평균 최대낙폭", f"{avg_drop:+.2f}%")

                st.divider()

                # ── 수익률 분포 ──
                st.subheader(f"{sig_fwd}거래일 후 수익률 분포")
                import plotly.graph_objects as go
                fig_hist = go.Figure()
                fig_hist.add_trace(go.Histogram(
                    x=sig_df[ret_col], nbinsx=40,
                    marker_color=["#D92B2B" if v < 0 else "#27AE60"
                                  for v in sorted(sig_df[ret_col])],
                    opacity=0.8,
                ))
                fig_hist.add_vline(x=0, line_dash="dash", line_color="white", line_width=1)
                fig_hist.add_vline(x=avg_ret, line_dash="dot", line_color="#F39C12",
                                   annotation_text=f"평균 {avg_ret:+.2f}%",
                                   annotation_font_color="#F39C12")
                fig_hist.update_layout(
                    template="plotly_dark",
                    height=300, margin=dict(l=40, r=20, t=30, b=40),
                    xaxis_title=f"{sig_fwd}일 수익률 (%)",
                    yaxis_title="빈도",
                    showlegend=False,
                )
                st.plotly_chart(fig_hist, use_container_width=True)

                # ── 상세 테이블 ──
                with st.expander(f"상세 이벤트 ({n_events}건)", expanded=False):
                    _num_cols = [ret_col, gain_col, drop_col]
                    _avail = [c for c in _num_cols if c in sig_df.columns]
                    _color_map = {c: "red_positive" for c in _avail}
                    _aggrid(sig_df, key="sig_bt_detail", height=400,
                            click_nav=False, color_map=_color_map)

        elif sig_df is not None and sig_df.empty:
            st.info("해당 조건의 이벤트가 없습니다.")

    with tab2:
        st.subheader("일중반전 분석")
        st.caption("당일 고가 갱신 후 전일 종가 하회 + 거래량 급증 패턴의 이후 수익률 분포를 분석합니다.")

        # ── 필터 행 ──────────────────────────────────────────
        col_mkt, col_period, col_vol, _ = st.columns([1, 1, 2, 2])
        with col_mkt:
            ir_market = st.selectbox(
                "시장",
                ["KOSPI", "KOSDAQ", "NASDAQ", "NYSE"],
                key="ir_market",
            )
        with col_period:
            ir_period_label = st.selectbox(
                "분석기간",
                ["1년(252일)", "6개월(126일)", "3개월(63일)"],
                key="ir_period_label",
            )
        with col_vol:
            ir_vol_pct = st.number_input(
                "거래량 기준: 60일 평균의 __% 이상",
                min_value=110,
                max_value=300,
                value=120,
                step=10,
                key="ir_vol_pct",
            )

        # 분석기간 → lookback_days (캐시는 항상 252일 기준으로 저장, UI에서 필터링)
        _period_map = {"1년(252일)": 252, "6개월(126일)": 126, "3개월(63일)": 63}
        ir_lookback = 252  # 캐시 단위는 항상 252일
        ir_display_days = _period_map[ir_period_label]
        ir_vol_threshold = ir_vol_pct / 100.0

        # 캐시 상태 확인
        _ir_cache_key = f"backtest_intraday_{ir_market}_{ir_lookback}"
        _ir_cache_info = get_backtest_cache_info(ir_market, ir_lookback)

        # 버튼 행
        col_btn1, col_btn2, col_info2, _ = st.columns([1, 1, 3, 3])
        _run_scan = False
        _force_rescan = False

        with col_btn1:
            if _ir_cache_key not in st.session_state:
                if st.button("🔍 분석 실행", type="primary", key="ir_run_btn"):
                    _run_scan = True
            else:
                st.success("캐시 로드됨")

        with col_btn2:
            if _ir_cache_info or _ir_cache_key in st.session_state:
                if st.button("🔄 재계산", key="ir_rerun_btn"):
                    _force_rescan = True
                    if _ir_cache_key in st.session_state:
                        del st.session_state[_ir_cache_key]

        with col_info2:
            if _ir_cache_info:
                st.caption(f"마지막 계산: {_ir_cache_info}")

        # ── 스캔 실행 ──────────────────────────────────────
        if _run_scan or _force_rescan:
            _prog_bar = st.progress(0)
            _prog_text = st.empty()

            def _ir_progress(done, total):
                pct = int(done / total * 100)
                _prog_bar.progress(min(pct, 100))
                _prog_text.text(f"진행 중... {done}/{total} 종목 ({pct}%)")

            with st.spinner(f"{ir_market} 전 종목 스캔 중... (수 분 소요될 수 있습니다)"):
                _ir_df = run_intraday_reversal_backtest(
                    market=ir_market,
                    lookback_days=ir_lookback,
                    vol_threshold=ir_vol_threshold,
                    vol_period=60,
                    use_cache=(not _force_rescan),
                    progress_cb=_ir_progress,
                )

            _prog_bar.empty()
            _prog_text.empty()

            if not _ir_df.empty:
                st.session_state[_ir_cache_key] = _ir_df
            else:
                st.warning("이벤트가 감지되지 않았습니다.")

        # ── 데이터 로드 ──────────────────────────────────────
        if _ir_cache_key not in st.session_state:
            # 파일 캐시에서 자동 로드 시도
            _cached_on_disk = run_intraday_reversal_backtest.__module__ and get_backtest_cache_info(ir_market, ir_lookback)
            if _cached_on_disk:
                from backtest import _load_backtest_cache
                _loaded = _load_backtest_cache(ir_market, ir_lookback)
                if _loaded is not None and not _loaded.empty:
                    st.session_state[_ir_cache_key] = _loaded

        if _ir_cache_key not in st.session_state:
            st.info("'분석 실행' 버튼을 눌러 스캔을 시작하세요.")
        else:
            import altair as alt

            _full_df = st.session_state[_ir_cache_key].copy()

            # 거래량 기준 필터 적용
            _full_df = _full_df[_full_df["거래량비율(%)"] >= ir_vol_pct].copy()

            # 분석기간 필터 (날짜 기준)
            _cutoff = (datetime.now() - timedelta(days=ir_display_days)).strftime("%Y-%m-%d")
            _disp_df = _full_df[_full_df["날짜"] >= _cutoff].copy()

            if _disp_df.empty:
                st.warning("선택한 기간/거래량 기준에 해당하는 이벤트가 없습니다.")
            else:
                # RS 그룹 분류
                _disp_df["RS그룹"] = _disp_df["RS순위백분위(%)"].apply(
                    lambda x: "RS 상위 40%" if x <= 40 else "RS 하위 60%"
                )

                # ── KPI 행 ──────────────────────────────────
                _n_events = len(_disp_df)
                _drop1d = (_disp_df["1일"] < 0).sum() / _n_events * 100
                _avg5d = _disp_df["5일"].mean()
                _avg_mdd = _disp_df["20일최대낙폭"].mean()

                kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                kpi1.metric("이벤트 건수", f"{_n_events:,}건")
                kpi2.metric("익일 하락확률", f"{_drop1d:.1f}%")
                kpi3.metric("평균 5일 수익률", f"{_avg5d:+.2f}%")
                kpi4.metric("평균 20일 최대낙폭", f"{_avg_mdd:.2f}%")

                st.divider()

                # ── RS 그룹 필터 ─────────────────────────────
                _rs_filter = st.radio(
                    "RS 그룹 필터",
                    ["전체", "RS 상위 40%", "RS 하위 60%"],
                    horizontal=True,
                    key="ir_rs_filter",
                )
                if _rs_filter != "전체":
                    _view_df = _disp_df[_disp_df["RS그룹"] == _rs_filter].copy()
                else:
                    _view_df = _disp_df.copy()

                st.caption(f"필터 적용 후 이벤트: {len(_view_df):,}건")

                # ── 거래량 구간별 분석 테이블 ─────────────────
                st.markdown("#### 거래량 구간별 분석")

                _vol_bands = ["120~150%", "150~200%", "200~300%", "300%+"]
                _vol_rows = []
                for _band in _vol_bands:
                    _g = _view_df[_view_df["거래량구간"] == _band]
                    if _g.empty:
                        continue
                    _cnt = len(_g)
                    _row = {
                        "구간": _band,
                        "건수": _cnt,
                        "익일하락확률(%)": round((_g["1일"] < 0).sum() / _cnt * 100, 1),
                        "3일하락확률(%)": round((_g["3일"] < 0).sum() / _cnt * 100, 1),
                        "5일하락확률(%)": round((_g["5일"] < 0).sum() / _cnt * 100, 1),
                        "평균1일(%)": round(_g["1일"].mean(), 2),
                        "평균3일(%)": round(_g["3일"].mean(), 2),
                        "평균5일(%)": round(_g["5일"].mean(), 2),
                        "평균10일(%)": round(_g["10일"].mean(), 2),
                        "평균20일(%)": round(_g["20일"].mean(), 2),
                        "평균최대낙폭(%)": round(_g["20일최대낙폭"].mean(), 2),
                    }
                    _vol_rows.append(_row)

                if _vol_rows:
                    _vol_tbl = pd.DataFrame(_vol_rows)
                    _vol_color_map = {c: "red_positive" for c in
                                      ["평균1일(%)", "평균3일(%)", "평균5일(%)", "평균10일(%)", "평균20일(%)", "평균최대낙폭(%)"]}
                    _aggrid(_vol_tbl, key="vol_band_table", height=250, click_nav=False, color_map=_vol_color_map)
                else:
                    st.info("해당 조건의 거래량 구간 데이터가 없습니다.")

                st.divider()

                # ── 수익률 분포 차트 (Box Plot) ─────────────
                st.markdown("#### 수익률 분포 (기간별 Box Plot)")

                _return_cols = ["1일", "3일", "5일", "10일", "20일"]
                _melt_df = _view_df[["RS그룹"] + _return_cols].melt(
                    id_vars=["RS그룹"],
                    var_name="기간",
                    value_name="수익률(%)",
                )
                _melt_df = _melt_df.dropna(subset=["수익률(%)"])

                if not _melt_df.empty:
                    _box_chart = (
                        alt.Chart(_melt_df)
                        .mark_boxplot(extent="min-max")
                        .encode(
                            x=alt.X(
                                "기간:N",
                                sort=["1일", "3일", "5일", "10일", "20일"],
                                title="기간",
                            ),
                            y=alt.Y("수익률(%):Q", title="수익률 (%)"),
                            color=alt.Color(
                                "RS그룹:N",
                                scale=alt.Scale(
                                    domain=["RS 상위 40%", "RS 하위 60%"],
                                    range=["#1a5ecc", "#c0392b"],
                                ),
                            ),
                        )
                        .properties(height=320)
                    )
                    st.altair_chart(_box_chart, use_container_width=True)

                st.divider()

                # ── 상세 이벤트 테이블 ────────────────────────
                with st.expander(f"상세 이벤트 목록 ({len(_view_df):,}건)", expanded=False):
                    _detail_cols = [
                        "날짜", "종목코드", "종목명", "RS Score", "RS순위백분위(%)",
                        "거래량비율(%)", "거래량구간", "1일", "3일", "5일", "10일", "20일", "20일최대낙폭",
                    ]
                    _show_cols = [c for c in _detail_cols if c in _view_df.columns]
                    _detail_df = _view_df[_show_cols].reset_index(drop=True)

                    _num_ret_cols = ["1일", "3일", "5일", "10일", "20일", "20일최대낙폭"]
                    _avail_ret_cols = [c for c in _num_ret_cols if c in _detail_df.columns]
                    _detail_color_map = {c: "red_positive" for c in _avail_ret_cols}
                    _aggrid(_detail_df, key="backtest_detail_table", height=400,
                            click_nav=False, color_map=_detail_color_map)

    with tab3:
        st.subheader("커스텀 전략 백테스트")
        st.info("🚧 준비 중입니다. 조건을 직접 설정하여 다양한 진입/청산 전략을 검증합니다.")


def show_watchlist_stocks():
    st.title("👀 관심종목")
    st.caption("진입 대기 중인 종목 · 이유와 조건을 기록하고 차트로 바로 이동")

    _mkt = st.radio("시장", ["🇰🇷 한국", "🇺🇸 미국"], horizontal=True,
                    label_visibility="collapsed", key="wls_market")
    market = "KR" if _mkt == "🇰🇷 한국" else "US"

    data   = load_watchlist_stocks()
    stocks = data.get(market, [])

    # ── 종목 추가 ──
    with st.expander("➕ 종목 추가"):
        with st.form("wls_add_form", clear_on_submit=True):
            if market == "KR":
                _krx     = load_krx_listing()
                _options = [""] + [f"{r['Name']}  ({r['Code']})" for _, r in _krx.iterrows()]
                _sel = st.selectbox("종목 검색", _options,
                                    label_visibility="collapsed", key="wls_sel_kr")
            else:
                _sel = st.text_input("Ticker", placeholder="NVDA",
                                     label_visibility="collapsed", key="wls_sel_us")
            reason    = st.text_area("대기 이유", placeholder="예: VCP 형성 중, 섹터 RS 상승 중", height=80)
            condition = st.text_area("진입 조건", placeholder="예: 20일선 풀백 후 거래량 증가 시", height=80)
            if st.form_submit_button("추가", use_container_width=True):
                if _sel and _sel.strip():
                    if market == "KR" and "(" in _sel:
                        _code = _sel.split("(")[-1].rstrip(")").strip()
                        _name = _sel.split("(")[0].strip()
                    else:
                        _code = _sel.strip().upper()
                        _name = _code
                    add_watchlist_stock(market, _code, _name, reason, condition)
                    st.rerun()

    if not stocks:
        st.info("관심종목이 없습니다. 위에서 종목을 추가하세요.")
        return

    st.markdown(f"**{len(stocks)}종목 대기 중**")
    st.divider()

    # KR 종목명 맵
    _krx_map = {}
    if market == "KR":
        try:
            _krx_df  = load_krx_listing()
            _krx_map = dict(zip(_krx_df["Code"], _krx_df["Name"]))
        except Exception:
            pass

    for s in stocks:
        ticker    = s["ticker"]
        name      = _krx_map.get(ticker, s.get("name", ticker)) if market == "KR" else s.get("name", ticker)
        reason    = s.get("reason", "")
        condition = s.get("condition", "")
        added     = s.get("added_date", "")

        h1, h2, h3 = st.columns([4, 1, 1])
        if market == "KR":
            h1.markdown(f"**{name}** <span style='color:#888;font-size:13px'>({ticker})</span>",
                        unsafe_allow_html=True)
        else:
            h1.markdown(f"**{ticker}**")
        if added:
            h1.caption(f"추가일: {added}")

        if h2.button("📈 차트", key=f"wls_chart_{ticker}"):
            st.session_state["chart_ticker"]   = ticker
            st.session_state["chart_name"]     = name
            st.session_state["chart_market"]   = market
            st.session_state["sidebar_ticker"] = ticker
            st.session_state["return_to_view"] = "watchlist_stocks"
            st.session_state["view"]           = "chart"
            st.rerun()

        if h3.button("🗑️ 삭제", key=f"wls_rm_{ticker}"):
            remove_watchlist_stock(market, ticker)
            st.rerun()

        if reason:
            st.markdown(f"📌 **대기이유** · {reason}")
        if condition:
            st.markdown(f"🎯 **진입조건** · {condition}")

        with st.expander("✏️ 메모 편집"):
            with st.form(f"wls_edit_{ticker}"):
                new_reason    = st.text_area("대기 이유",  value=reason,    height=80, key=f"wls_r_{ticker}")
                new_condition = st.text_area("진입 조건",  value=condition, height=80, key=f"wls_c_{ticker}")
                if st.form_submit_button("저장", use_container_width=True):
                    update_watchlist_stock(market, ticker, new_reason, new_condition)
                    st.rerun()

        st.divider()


def show_watchlist():
    st.title("📂 그룹 분석")
    st.caption("산업/테마별 종목 그룹 관리 및 RS 강도 비교")

    _mkt = st.radio("시장", ["🇰🇷 한국", "🇺🇸 미국"], horizontal=True,
                    label_visibility="collapsed", key="wl_market")
    market = "KR" if _mkt == "🇰🇷 한국" else "US"
    benchmark_name = "코스피" if market == "KR" else "S&P 500"

    wl = load_watchlists()
    groups = wl.get(market, {})

    # ── 전체 그룹 RS 랭킹 테이블 (최상단) ──
    _period = st.select_slider("분석 기간", options=[10, 20, 40, 60, 120, 252], value=60,
                               format_func=lambda x: f"{x}일", key="wl_period")

    if groups:
        # 당일 캐시 자동 로드
        _cached = load_group_rs_cache(market, groups)
        if _cached and "wl_group_rs_rows" not in st.session_state:
            st.session_state["wl_group_rs_rows"]   = _cached
            st.session_state["wl_group_rs_period"] = _period
            st.session_state["wl_group_rs_market"] = market

        _btn_col, _info_col = st.columns([1, 3])
        if _btn_col.button("📊 전체 그룹 RS 계산", key="wl_all_rs"):
            _group_rs_rows = []
            with st.spinner(f"{len(groups)}개 그룹 계산 중..."):
                for _gname, _gtickers in groups.items():
                    if not _gtickers:
                        continue
                    _gi = calc_group_index(market, _gtickers, period=_period)
                    if _gi:
                        _group_rs_rows.append({
                            "그룹명":               _gname,
                            "RS Score":             _gi["rs_score"],
                            "그룹수익률(%)":        _gi["group_ret"],
                            f"{benchmark_name}(%)": _gi["bench_ret"],
                            "종목수":               len(_gtickers),
                        })
            if _group_rs_rows:
                save_group_rs_cache(market, groups, _group_rs_rows)
                st.session_state["wl_group_rs_rows"]   = _group_rs_rows
                st.session_state["wl_group_rs_period"] = _period
                st.session_state["wl_group_rs_market"] = market

        _saved_rows   = st.session_state.get("wl_group_rs_rows", [])
        _saved_market = st.session_state.get("wl_group_rs_market", market)
        if _saved_rows and _saved_market == market:
            _saved_period = st.session_state.get("wl_group_rs_period", _period)
            from watchlist import _group_rs_cache_path
            _cache_path = _group_rs_cache_path(market)
            _cache_label = "캐시" if _cache_path.exists() else "방금 계산"
            _info_col.caption(f"기준: {_saved_period}일 · {_cache_label} · 행 클릭 시 그룹 차트로 이동")
            _grp_df = pd.DataFrame(_saved_rows).sort_values("RS Score", ascending=False).reset_index(drop=True)
            _grp_result = _aggrid(
                _grp_df, key="wl_group_rs_table",
                height=min(500, 80 + len(_grp_df) * 35),
                click_nav=True,
                color_map={"RS Score": "red_positive", "그룹수익률(%)": "red_positive"},
                hide_cols=[],
                col_widths={"그룹명": 160, "RS Score": 110, "그룹수익률(%)": 120, "종목수": 80},
            )
            _grp_sel = _grp_result["selected_rows"]
            if _grp_sel is not None and len(_grp_sel) > 0:
                _sel_gname   = _grp_sel[0]["그룹명"]
                _sel_tickers = groups.get(_sel_gname, [])
                st.session_state["wl_chart_group"]   = _sel_gname
                st.session_state["wl_chart_market"]  = market
                st.session_state["wl_chart_tickers"] = _sel_tickers
                st.session_state["wl_chart_period"]  = _saved_period
                st.session_state["wl_chart_bench"]   = benchmark_name
                st.session_state["return_to_view"]   = "watchlist"
                st.session_state["view"]             = "group_chart"
                st.rerun()

    st.divider()

    # ── 그룹 생성 ──
    with st.expander("➕ 새 그룹 만들기"):
        _nc1, _nc2 = st.columns([3, 1])
        new_group_name = _nc1.text_input("그룹명", placeholder="예: 2차전지 소재",
                                         label_visibility="collapsed", key="wl_new_group")
        if _nc2.button("생성", key="wl_create_group"):
            if new_group_name.strip():
                add_group(market, new_group_name.strip())
                st.rerun()

    if not groups:
        st.info("그룹이 없습니다. 위에서 새 그룹을 만들어보세요.")
        return

    # ── 그룹 선택 및 관리 ──
    group_names = list(groups.keys())
    selected_group = st.selectbox("그룹 선택", group_names, key="wl_selected_group")
    tickers = groups.get(selected_group, [])

    col_left, col_right = st.columns([2, 1])

    with col_left:
        if not tickers:
            st.info("종목을 추가하세요.")
        else:
            st.markdown(f"**{selected_group}** — {len(tickers)}종목 · 벤치마크: {benchmark_name}")
            if st.button("📈 그룹 차트 보기", type="primary", key="wl_calc_rs"):
                st.session_state["wl_chart_group"]   = selected_group
                st.session_state["wl_chart_market"]  = market
                st.session_state["wl_chart_tickers"] = tickers
                st.session_state["wl_chart_period"]  = _period
                st.session_state["wl_chart_bench"]   = benchmark_name
                st.session_state["return_to_view"]   = "watchlist"
                st.session_state["view"]             = "group_chart"
                st.rerun()

    with col_right:
        st.markdown("**종목 관리**")
        with st.form("wl_add_form", clear_on_submit=True):
            if market == "KR":
                _krx = load_krx_listing()
                _options = [""] + [f"{r['Name']}  ({r['Code']})" for _, r in _krx.iterrows()]
                _sel = st.selectbox("종목 검색", _options,
                                    label_visibility="collapsed", key="wl_sel_kr")
            else:
                _sel = st.text_input("Ticker 입력", placeholder="NVDA",
                                     label_visibility="collapsed", key="wl_sel_us")
            if st.form_submit_button("추가", use_container_width=True):
                if _sel and _sel.strip():
                    if market == "KR" and "(" in _sel:
                        _code = _sel.split("(")[-1].rstrip(")")
                    else:
                        _code = _sel.strip().upper()
                    add_ticker(market, selected_group, _code)
                    st.rerun()

        if tickers:
            st.caption(f"{len(tickers)}종목")
            _krx_map = {}
            if market == "KR":
                try:
                    _krx_df = load_krx_listing()
                    _krx_map = dict(zip(_krx_df["Code"], _krx_df["Name"]))
                except Exception:
                    pass
            for _t in tickers:
                _r1, _r2 = st.columns([3, 1])
                if market == "KR":
                    _name = _krx_map.get(_t, _t)
                    _label = f"{_name} ({_t})" if _name != _t else _t
                else:
                    _label = _t
                _r1.markdown(_label)
                if _r2.button("✕", key=f"wl_rm_{_t}"):
                    remove_ticker(market, selected_group, _t)
                    st.rerun()

        st.divider()
        if st.button("🗑️ 그룹 삭제", key="wl_delete_group"):
            delete_group(market, selected_group)
            st.rerun()


if st.session_state.view == "portfolio":
    show_portfolio()

elif st.session_state.view == "chart" and st.session_state.chart_ticker:
    st.title("📈 SEPA")
    st.caption("Specific Entry Point Analysis  ·  IBD 스타일 상대강도 분석 | 한국·미국 주식 지원")
    show_chart(st.session_state.chart_ticker, st.session_state.chart_period, custom_benchmark)

elif st.session_state.view == "backtest":
    show_backtest()

elif st.session_state.view == "pattern_scanner":
    show_pattern_scanner()

elif st.session_state.view == "short_scanner":
    show_short_scanner()

elif st.session_state.view == "watchlist_stocks":
    show_watchlist_stocks()

elif st.session_state.view == "watchlist":
    show_watchlist()

elif st.session_state.view == "group_chart":
    group_name    = st.session_state.get("wl_chart_group", "")
    market        = st.session_state.get("wl_chart_market", "KR")
    tickers       = st.session_state.get("wl_chart_tickers", [])
    benchmark_name = st.session_state.get("wl_chart_bench", "코스피")

    period = st.session_state.get("gc_period", st.session_state.get("wl_chart_period", 60))

    st.title(f"📂 {group_name}")
    st.caption(f"동일 비중 그룹 지수 · 벤치마크: {benchmark_name} · {period}일")

    with st.spinner(f"{len(tickers)}종목 데이터 수집 중..."):
        gi = calc_group_index(market, tickers, period=period)

    if gi is None:
        st.error("데이터를 불러올 수 없습니다. 종목코드를 확인해주세요.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("그룹 RS Score", f"{gi['rs_score']:+.1f}")
        c2.metric(f"그룹 수익률 ({period}일)", f"{gi['group_ret']:+.2f}%")
        c3.metric(f"{benchmark_name} 수익률", f"{gi['bench_ret']:+.2f}%")

        fig = build_group_chart(gi, group_name, benchmark_name)
        st.plotly_chart(fig, use_container_width=True)

        # ── 그룹 내 종목별 RS 테이블 ──────────────────
        st.subheader("📊 종목별 RS")
        with st.spinner("종목별 RS 계산 중..."):
            rs_df = calc_group_rs(market, tickers, period=period)

        if not rs_df.empty:
            rs_result = _aggrid(
                rs_df.reset_index(drop=True),
                key="group_rs_ticker_table",
                height=min(500, 80 + len(rs_df) * 35),
                click_nav=True,
                color_map={"RS Score": "red_positive", "수익률(%)": "red_positive"},
                hide_cols=[],
                col_widths={"종목코드": 90, "종목명": 160, "RS Score": 110, "수익률(%)": 110, "현재가": 110},
            )
            _sel = rs_result["selected_rows"]
            if _sel is not None and len(_sel) > 0:
                _ticker = _sel[0]["종목코드"]
                st.session_state["sidebar_ticker"] = _ticker
                st.session_state["chart_ticker"]   = _ticker
                st.session_state["chart_period"]   = period
                st.session_state["return_to_view"] = "group_chart"
                st.session_state["view"]           = "chart"
                st.rerun()

elif st.session_state.view in ("home", "dashboard"):
    show_dashboard()

elif st.session_state.view == "market_indicators":
    show_market_indicators()

elif st.session_state.view in ("rs_scanner", "ranking"):
    st.title("📊 RS Scanner")
    st.caption("Trend-based Entry (PB / HB)  ·  RS 강세 상위 종목 탐색")
    st.subheader("🏆 RS 강세 상위 종목")

    selected_period = st.select_slider(
        "랭킹 계산 기간",
        options=[10, 20, 40, 60],
        value=st.session_state.confirmed_rank_period,
        format_func=lambda x: f"{x}일",
    )

    # 슬라이더 값이 현재 확정된 기간과 다르면 확인 요청
    if selected_period != st.session_state.confirmed_rank_period:
        st.warning(
            f"기간을 **{st.session_state.confirmed_rank_period}일 → {selected_period}일**로 변경하면 전체 재계산됩니다. (수 분 소요)"
        )
        col_yes, col_no, _ = st.columns([1, 1, 4])
        if col_yes.button("✅ 확인 (재계산)", type="primary"):
            st.session_state.confirmed_rank_period = selected_period
            # 기존 캐시 삭제
            for k in [k for k in st.session_state if k.startswith("ranking_") or k.startswith("vcp_") or k.startswith("stage2_")]:
                del st.session_state[k]
            st.rerun()
        if col_no.button("❌ 취소"):
            st.rerun()

    rank_period = st.session_state.confirmed_rank_period

    col_ref, col_info, _ = st.columns([1, 4, 3])
    with col_ref:
        if st.button("🔄 강제 재계산", help="RS 랭킹 + VCP + 2단계 전체 재계산 (새 캐시로 덮어쓰기)"):
            st.session_state["_force_rs_all"] = True
            st.rerun()
    with col_info:
        st.caption("💡 매일 첫 실행 시 자동 재계산 · 당일은 캐시에서 즉시 로드")

    st.divider()

    # 차트에서 미국탭으로 복귀 시 JS로 탭 클릭
    _ret_top = st.session_state.pop("return_top_tab", 0)
    if _ret_top == 1:
        _jump_to_tab(1)

    tab_kr, tab_us = st.tabs(["🇰🇷 한국", "🇺🇸 미국"])

    with tab_kr:
        col_kospi, col_kosdaq = st.columns(2)
        with col_kospi:
            st.markdown("#### 📊 KOSPI")
            show_ranking_table("KOSPI", rank_period)
        with col_kosdaq:
            st.markdown("#### 📊 KOSDAQ")
            show_ranking_table("KOSDAQ", rank_period)

    with tab_us:
        st.caption("⚠️ 첫 계산 시 NASDAQ 약 20~30분, NYSE 약 15~20분 소요됩니다. 당일 캐시 이후엔 즉시 로드됩니다.")
        col_nasdaq, col_nyse = st.columns(2)
        with col_nasdaq:
            st.markdown("#### 📊 NASDAQ")
            show_ranking_table("NASDAQ", rank_period, auto_calc=False)
        with col_nyse:
            st.markdown("#### 📊 NYSE")
            show_ranking_table("NYSE", rank_period, auto_calc=False)

    st.divider()
    with st.expander("ℹ️ 사용 방법 & 차트 구성"):
        st.markdown("""
**종목 분석 방법**
1. **순위표에서 종목 행 클릭** → 바로 차트로 이동
2. 또는 왼쪽 사이드바에서 종목 코드 직접 입력 후 **분석 시작** 클릭

**차트 구성**
| 패널 | 내용 |
|------|------|
| 상단 | 캔들스틱 + MA5·20·60·WMA100·120·200 + 지수 비교선 |
| 중단 | 거래량 |
| 하단 | RS Line (100 위=강세 빨강, 100 아래=약세 파랑) |
""")

    with st.expander("📐 RS Score · RS Line 정의 및 수식"):
        st.markdown("""
---
### RS Line (상대강도선)

**정의**
종목 주가를 벤치마크 지수로 나눈 비율을 분석 시작 시점 기준으로 정규화한 값입니다.
지수 대비 종목의 상대적 강세/약세를 선으로 시각화합니다.

**수식**
```
RS Line(t) = [ 종목가격(t) / 지수가격(t) ]
           ÷ [ 종목가격(0) / 지수가격(0) ]
           × 100
```
- 분석 시작일(t=0) 기준값 = **100**
- **100 초과** → 지수 대비 강세 (차트에서 빨간색)
- **100 미만** → 지수 대비 약세 (차트에서 파란색)
- RS Line이 신고가를 갱신하며 우상향 → 강한 종목의 특징

---
### RS Score (상대강도 점수)

**정의**
IBD(Investor's Business Daily) 방식을 응용한 가중 상대수익률입니다.
분석 기간을 4등분하여 **최근 1/4 구간에 2배 가중치**를 부여해,
최근 모멘텀을 더 강하게 반영합니다.

**수식**
```
분석 기간 n일 → 1/4 구간 = n ÷ 4 거래일

종목 최근수익률 = (종목가격[-1]     / 종목가격[-n/4] - 1) × 100
종목 이전수익률 = (종목가격[-n/4]   / 종목가격[0]   - 1) × 100
지수  최근수익률 = (지수가격[-1]     / 지수가격[-n/4] - 1) × 100
지수  이전수익률 = (지수가격[-n/4]   / 지수가격[0]   - 1) × 100

종목 가중수익률 = 2 × 종목최근수익률 + 종목이전수익률
지수 가중수익률 = 2 × 지수최근수익률 + 지수이전수익률

RS Score = 종목 가중수익률 − 지수 가중수익률
```

**예시** (분석기간 60일, n/4 = 15일)
```
종목 최근 15일 수익률: +8%,  이전 45일: +5%  → 가중 = 2×8 + 5 = 21
지수 최근 15일 수익률: +3%,  이전 45일: +4%  → 가중 = 2×3 + 4 = 10
RS Score = 21 − 10 = +11 (강세)
```

**해석**
| RS Score | 의미 |
|----------|------|
| 양수(+) 클수록 | 지수 대비 강한 초과수익 → 강세 종목 |
| 0 근처 | 지수와 유사한 움직임 |
| 음수(-) 클수록 | 지수 대비 부진 → 약세 종목 |

> **핵심 원칙**: RS Line이 신고가를 먼저 돌파하는 종목은
> 주가 돌파에 앞서 강세 신호를 보내는 경우가 많습니다. (IBD 방식)
""")
