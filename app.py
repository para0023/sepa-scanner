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
from market_ranking import calc_market_ranking, get_cache_info, _cache_path, refresh_52w_high, apply_vcp_filter, apply_stage2_filter, get_filter_cache_info, scan_vcp_patterns, get_vcp_pattern_cache_info
from backtest import run_intraday_reversal_backtest, get_backtest_cache_info, run_signal_backtest, get_signal_cache_info
from portfolio import add_buy, add_sell, get_open_positions, get_trade_log, calculate_performance, update_stop_loss, get_stop_loss_history, get_realized_pnl, get_position_pnl, get_total_capital, set_initial_capital, add_capital_flow, get_capital_flows, delete_capital_flow, delete_trade, update_trade, get_equity_curve, get_monthly_performance, get_trades_by_ticker, set_portfolio_file
from watchlist import (load_watchlists, save_watchlists, add_group, delete_group,
                       add_ticker, remove_ticker, calc_group_rs,
                       calc_group_index, build_group_chart,
                       load_watchlist_stocks, add_watchlist_stock,
                       remove_watchlist_stock, update_watchlist_stock,
                       load_group_rs_cache, save_group_rs_cache)
import FinanceDataReader as fdr

@st.cache_data(ttl=86400)
def load_krx_listing():
    """KRX 전체 종목 목록 (하루 캐시)"""
    try:
        df = fdr.StockListing("KRX")[["Code", "Name", "Market"]].dropna()
        df = df[df["Code"].str.len() == 6].reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame(columns=["Code", "Name", "Market"])

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
    _price_keywords = ("가", "금액", "매출", "이익", "손실", "단가", "원", "원)")
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
# 페이지 설정
# ══════════════════════════════════════════════════════════
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
        placeholder="예: 005930  /  AAPL",
        help="한국 주식은 6자리 숫자 (예: 005930), 미국 주식은 영문 티커 (예: AAPL)",
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
            min_value=10, max_value=250, value=20, step=5,
            help="기본 20일. 길수록 중장기 추세가 보입니다.",
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
    if st.button("💼 포트폴리오", use_container_width=True):
        st.session_state.view = "portfolio"
        st.rerun()

    if st.button("📂 그룹 분석", use_container_width=True):
        st.session_state.view = "watchlist"
        st.rerun()

    if st.button("👀 관심종목", use_container_width=True):
        st.session_state.view = "watchlist_stocks"
        st.rerun()

    if st.button("🏠 홈", use_container_width=True):
        st.session_state.view = "home"
        st.session_state.sidebar_ticker = ""
        st.rerun()

    # 뒤로 가기 (차트 보는 중일 때)
    if st.session_state.get("view") == "chart":
        return_to = st.session_state.get("return_to_view", "rs_scanner")
        _back_labels = {
            "rs_scanner": "← RS Scanner로",
            "pattern_scanner": "← Pattern Scanner로",
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
    st.session_state.view = "home"
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
    filter_show_cols = ["종목코드", "종목명", "현재가", "RS Score", "RS Line", "종목수익률", "지수수익률", "고가대비(%)"]

    def _render_filter_table(data, key: str, tab_idx: int = 0):
        if data.empty:
            st.info("해당 조건의 종목이 없습니다.")
            return
        disp = data[filter_show_cols].reset_index(drop=True)
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
        if vcp_cache_key not in st.session_state:
            if vcp_file_time:
                with st.spinner("VCP 캐시 로드 중..."):
                    st.session_state[vcp_cache_key] = apply_vcp_filter(df, market=market, period=rank_period, range_pct=10.0)
                st.rerun()
            else:
                if st.button("🔍 VCP 조건 계산", key=f"vcp_btn_{market}_{rank_period}"):
                    with st.spinner("VCP 조건 확인 중... (상위 100종목)"):
                        st.session_state[vcp_cache_key] = apply_vcp_filter(df, market=market, period=rank_period, range_pct=10.0)
                    st.rerun()
                st.caption("버튼을 클릭하면 상위 100종목의 VCP 조건을 계산합니다. (하루 1회 캐시 저장)")
        else:
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
            st.caption(f"5일 평균 거래량 < 60일 평균  ·  5일 고저폭/전일종가 ≤ 10%  ·  캐시: {t}")
            if st.button("🔄 재계산", key=f"vcp_recalc_{market}_{rank_period}"):
                st.session_state.pop(vcp_cache_key, None)
                with st.spinner("VCP 재계산 중..."):
                    st.session_state[vcp_cache_key] = apply_vcp_filter(df, market=market, period=rank_period, range_pct=10.0, use_cache=False)
                st.rerun()

    # ── 2단계 필터 ──────────────────────────────────────────
    if has_high:
        st.markdown("### 📈 2단계 시작 필터")
        s2_file_time = get_filter_cache_info("stage2", market, rank_period)
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
        else:
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
                st.session_state.pop(s2_cache_key, None)
                with st.spinner("2단계 재계산 중..."):
                    st.session_state[s2_cache_key] = apply_stage2_filter(df, market=market, period=rank_period, use_cache=False)
                st.rerun()

    cache_time = get_cache_info(market, rank_period)
    st.caption(
        f"📅 저장: {cache_time or '방금 계산'}  ·  기간: {rank_period}일  ·  행 클릭 시 차트로 이동"
    )


# ══════════════════════════════════════════════════════════
# 홈 화면
# ══════════════════════════════════════════════════════════
def show_home():
    st.title("📈 SEPA")
    st.markdown("## Specific Entry Point Analysis")
    st.caption("마크 미너비니 · 윌리엄 오닐 방식의 매수 타점 분석 시스템")
    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📊 RS Scanner")
        st.markdown("**Trend-based Entry (PB / HB)**")
        st.markdown(
            "RS 강세 상위 종목 목록을 기반으로 "
            "눌림목(PB) 및 높은 베이스(HB) 타점을 탐색합니다."
        )
        if st.button("RS Scanner 시작 →", type="primary", use_container_width=True, key="home_rs_btn"):
            st.session_state.view = "rs_scanner"
            st.rerun()

    with col2:
        st.markdown("### 🔍 Pattern Scanner")
        st.markdown("**Breakout Entry (VCP / BO)**")
        st.markdown(
            "VCP 패턴 완성 종목에서 수축 강도·거래량 수축 기반으로 "
            "피벗 돌파(BO) 타점을 탐색합니다."
        )
        if st.button("Pattern Scanner 시작 →", type="primary", use_container_width=True, key="home_pattern_btn"):
            st.session_state.view = "pattern_scanner"
            st.rerun()

    col3, col4 = st.columns(2)

    with col3:
        st.markdown("### 🧪 백테스트")
        st.markdown("**Strategy Backtest**")
        st.markdown(
            "SEPA 전략, 일중반전, 커스텀 조건 기반으로 "
            "과거 데이터에서 전략 성과를 검증합니다."
        )
        if st.button("백테스트 시작 →", type="primary", use_container_width=True, key="home_backtest_btn"):
            st.session_state.view = "backtest"
            st.rerun()

    with col4:
        st.markdown("### 💼 포트폴리오")
        st.markdown("**Portfolio Management**")
        st.markdown(
            "매수/매도 기록, 보유 현황, 손익 분석 및 "
            "거래 성과를 관리합니다."
        )
        if st.button("포트폴리오 보기 →", type="primary", use_container_width=True, key="home_portfolio_btn"):
            st.session_state.view = "portfolio"
            st.rerun()


# ══════════════════════════════════════════════════════════
# Pattern Scanner 렌더링
# ══════════════════════════════════════════════════════════

_VCP_SHOW_COLS = [
    "종목코드", "종목명", "RS Score", "RS순위(%)",
    "수축(T)", "수축강도(%)", "피벗", "현재가", "피벗거리(%)",
    "거래량비율(%)", "베이스상단", "베이스기간(일)",
]
_VCP_FMT = {
    "RS Score":      "{:+.2f}",
    "RS순위(%)":     "{:.1f}%",
    "수축강도(%)":   "{:.1f}%",
    "피벗":          "{:,.0f}",
    "현재가":        "{:,.0f}",
    "피벗거리(%)":   "{:.2f}%",
    "거래량비율(%)": "{:.1f}%",
    "베이스상단":    "{:,.0f}",
}
_PS_PERIOD = 60  # Pattern Scanner 고정 기간


def _show_vcp_table(market: str, auto_calc: bool = True):
    """VCP 패턴 테이블 렌더링"""
    _is_us    = market in ("NASDAQ", "NYSE")
    cache_key = f"vcp_patterns_{market}_{_PS_PERIOD}"
    vcp_file_time = get_vcp_pattern_cache_info(market, _PS_PERIOD)

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
        vcp_fmt["피벗"]     = "${:,.2f}"
        vcp_fmt["현재가"]   = "${:,.2f}"
        vcp_fmt["베이스상단"] = "${:,.2f}"

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
        row = selected[0]
        st.session_state.view           = "chart"
        st.session_state.chart_ticker   = row["종목코드"]
        st.session_state.chart_name     = row.get("종목명", "")
        st.session_state.chart_period   = _PS_PERIOD
        st.session_state.sidebar_ticker = row["종목코드"]
        st.session_state.return_to_view = "pattern_scanner"
        st.rerun()


def show_pattern_scanner():
    st.title("🔍 Pattern Scanner")
    st.caption("Breakout Entry (VCP / BO)  ·  RS 60일 기준 · RS 상위 40% · 2단계 조건 포함")

    col_ref, col_info, _ = st.columns([1, 4, 3])
    with col_ref:
        if st.button("🔄 강제 재스캔", help="오늘 캐시를 삭제하고 전체 재스캔합니다 (미국장 제외)"):
            today = datetime.now().strftime("%Y%m%d")
            for f in (Path(__file__).parent / "cache").glob(f"vcp_pattern_*{today}.json"):
                f.unlink(missing_ok=True)
            for k in [k for k in st.session_state if k.startswith("vcp_patterns_")]:
                del st.session_state[k]
            st.rerun()
    with col_info:
        st.caption("💡 매일 첫 실행 시 자동 재계산 · 당일은 캐시에서 즉시 로드")

    st.divider()

    tab_kr, tab_us = st.tabs(["🇰🇷 한국", "🇺🇸 미국"])

    with tab_kr:
        st.markdown("#### 📊 KOSPI")
        _show_vcp_table("KOSPI")
        st.divider()
        st.markdown("#### 📊 KOSDAQ")
        _show_vcp_table("KOSDAQ")

    with tab_us:
        col_nasdaq, col_nyse = st.columns(2)
        with col_nasdaq:
            st.markdown("#### 📊 NASDAQ")
            _show_vcp_table("NASDAQ", auto_calc=False)
        with col_nyse:
            st.markdown("#### 📊 NYSE")
            _show_vcp_table("NYSE", auto_calc=False)


# ══════════════════════════════════════════════════════════
# 포트폴리오 렌더링
# ══════════════════════════════════════════════════════════

def _fetch_current_price(ticker: str) -> float:
    """현재가 조회 (최근 5일 중 마지막 종가)"""
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
        # 종목별: 청산일 기준 당일 합산 후 누적
        raw = source_df[[date_col, "실현손익(원)"]].copy()
        raw = raw.groupby(date_col, as_index=False)["실현손익(원)"].sum()
        raw = raw.sort_values(date_col).reset_index(drop=True)
        raw["누적손익(원)"] = raw["실현손익(원)"].cumsum()
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
        raw = source_df[[date_col, "실현손익(원)", "수익률(%)"]].copy()
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


def _show_portfolio_us():
    """미국 포트폴리오 UI (달러 기준)"""
    tab_hold, tab_pnl, tab_perf, tab_log = st.tabs(
        ["📋 보유 현황", "📊 거래별 성과분석", "📊 종목별 성과분석", "📜 거래 이력"]
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

            with st.form("us_buy_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                us_ticker = st.session_state.get("us_buy_ticker", "").strip().upper()
                us_name   = st.session_state.get("us_buy_name", "").strip()
                us_date   = c1.date_input("매수일", value=datetime.now().date(), key="us_buy_date")

                c4, c5, c6 = st.columns(3)
                us_price = c4.number_input("매수가 ($)", min_value=0.0, step=0.01, format="%.2f", key="us_buy_price")
                us_qty   = c5.number_input("수량 (주)", min_value=1, step=1, key="us_buy_qty")
                us_stop  = c6.number_input("손절가 ($)", min_value=0.0, step=0.01, format="%.2f", key="us_buy_stop")

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
                        )
                        st.session_state["portfolio_toast"] = (f"✅ {us_name} 매수 저장 완료!", "success")
                        st.session_state["us_buy_expander_open"] = False
                        st.session_state.pop("us_buy_ticker", None)
                        st.session_state.pop("us_buy_name", None)
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

            n      = len(df_pnl)
            wins   = df_pnl[df_pnl["수익률(%)"] > 0]
            losses = df_pnl[df_pnl["수익률(%)"] <= 0]
            win_rate  = len(wins) / n * 100 if n > 0 else 0
            avg_win   = wins["수익률(%)"].mean()   if len(wins)   > 0 else 0
            avg_loss  = losses["수익률(%)"].mean() if len(losses) > 0 else 0
            avg_ret   = df_pnl["수익률(%)"].mean()
            _pnl_col = "실현손익($)" if "실현손익($)" in df_pnl.columns else "실현손익(원)"
            _fee_col = "거래비용($)" if "거래비용($)" in df_pnl.columns else "거래비용(원)"
            _net_col = "비용차감손익($)" if "비용차감손익($)" in df_pnl.columns else "비용차감손익(원)"
            total_pnl  = df_pnl[_pnl_col].sum() if _pnl_col in df_pnl.columns else 0
            total_fees = df_pnl[_fee_col].sum() if _fee_col in df_pnl.columns else 0
            total_net  = df_pnl[_net_col].sum() if _net_col in df_pnl.columns else total_pnl
            total_inv = (df_pnl["평균매수가"] * df_pnl["수량"]).sum() if "평균매수가" in df_pnl.columns else 0

            initial_capital = get_total_capital()
            turnover = total_inv / initial_capital if initial_capital > 0 else None
            adj_ret  = avg_ret * turnover if turnover is not None else None

            c1, c2, c3 = st.columns(3)
            c1.metric("총 실현손익 (비용차감)", f"${total_net:+,.2f}",
                      delta=f"거래비용 ${total_fees:,.2f}", delta_color="inverse")
            c2.metric("거래 건수",   f"{n}건")
            c3.metric("승/패",       f"{len(wins)}승 {len(losses)}패")

            c4, c5, c6 = st.columns(3)
            c4.metric("승률",              f"{win_rate:.1f}%")
            c5.metric("승리 시 평균수익률", f"{avg_win:+.2f}%")
            c6.metric("패배 시 평균손실률", f"{avg_loss:+.2f}%")

            c7, c8, c9 = st.columns(3)
            c7.metric("전체 평균수익률",    f"{avg_ret:+.2f}%")
            c8.metric("자산회전율",
                      f"{turnover:.2f}배" if turnover is not None else "원금 미설정")
            c9.metric("회전율 감안 수익률",
                      f"{adj_ret:+.2f}%" if adj_ret is not None else "원금 미설정")

            st.divider()
            _us_pnl_color_map = {_pnl_col: "red_positive", _net_col: "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
            _aggrid(df_pnl, key="us_trade_pnl_table", height=450, click_nav=False,
                    color_map=_us_pnl_color_map, pct_cols=["수익률(%)", "비용차감수익률(%)"], price_decimals=2)

            st.divider()
            st.subheader("누적 수익 곡선")
            _render_equity_curve()
            st.divider()
            st.subheader("월별 성과")
            _render_monthly_performance()

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

            st.subheader("1. 전체 성과 요약")
            overall_wins   = df_pos_pnl[df_pos_pnl["수익률(%)"] > 0]
            overall_losses = df_pos_pnl[df_pos_pnl["수익률(%)"] <= 0]
            overall_net    = df_pos_pnl[_pos_net_col].sum() if _pos_net_col in df_pos_pnl.columns else 0
            overall_fees   = df_pos_pnl[_pos_fee_col].sum() if _pos_fee_col in df_pos_pnl.columns else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("총 실현손익 (비용차감)", f"${overall_net:+,.2f}",
                      delta=f"거래비용 ${overall_fees:,.2f}", delta_color="inverse")
            c2.metric("종목 수",     f"{len(df_pos_pnl)}종목")
            c3.metric("승/패",       f"{len(overall_wins)}승 {len(overall_losses)}패")

            st.divider()
            st.subheader("2. 종목별 성과분석")
            _pos_pnl_color_map2 = {_pos_pnl_col: "red_positive", _pos_net_col: "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
            _pos_pnl_n = len(df_pos_pnl)
            _pos_pnl_height = 250 if _pos_pnl_n <= 5 else (350 if _pos_pnl_n <= 10 else 450)
            _aggrid(df_pos_pnl, key="us_position_pnl_table", height=_pos_pnl_height,
                    click_nav=False, color_map=_pos_pnl_color_map2, pct_cols=["수익률(%)", "비용차감수익률(%)"], price_decimals=2)

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
    tab_hold, tab_pnl, tab_perf, tab_log = st.tabs(["📋 보유 현황", "📊 거래별 성과분석", "📊 종목별 성과분석", "📜 거래 이력"])

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

            with st.form("buy_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                buy_ticker = c1.text_input("종목코드", key="buy_ticker").strip()
                buy_name   = c2.text_input("종목명",   key="buy_name").strip()
                buy_date   = c3.date_input("매수일", value=datetime.now().date(), key="buy_date")

                c4, c5, c6 = st.columns(3)
                buy_price  = c4.number_input("매수가 (원)", min_value=0, step=100, key="buy_price")
                buy_qty    = c5.number_input("수량 (주)",   min_value=1, step=1,   key="buy_qty")
                buy_stop   = c6.number_input("손절가 (원)", min_value=0, step=100, key="buy_stop")

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
                        )
                        st.session_state["portfolio_toast"] = (f"✅ {buy_name} 매수 저장 완료!", "success")
                        st.session_state["buy_expander_open"] = False
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
            n      = len(df_pnl)
            wins   = df_pnl[df_pnl["수익률(%)"] > 0]
            losses = df_pnl[df_pnl["수익률(%)"] <= 0]
            win_rate  = len(wins) / n * 100 if n > 0 else 0
            avg_win   = wins["수익률(%)"].mean()   if len(wins)   > 0 else 0
            avg_loss  = losses["수익률(%)"].mean() if len(losses) > 0 else 0
            avg_ret   = df_pnl["수익률(%)"].mean()
            avg_planned_loss = losses["목표손절률(%)"].dropna().mean() if len(losses) > 0 else None
            # 목표손절 위반: 실제 손실이 목표손절률보다 더 큰 경우
            losses_with_target = losses.dropna(subset=["목표손절률(%)"])
            violations = losses_with_target[losses_with_target["수익률(%)"] < losses_with_target["목표손절률(%)"]]
            n_violations  = len(violations)
            violation_rate = n_violations / len(losses_with_target) * 100 if len(losses_with_target) > 0 else 0
            total_inv  = (df_pnl["평균매수가"] * df_pnl["수량"]).sum()
            total_pnl  = df_pnl["실현손익(원)"].sum()
            total_fees = df_pnl["거래비용(원)"].sum() if "거래비용(원)" in df_pnl.columns else 0
            total_net  = df_pnl["비용차감손익(원)"].sum() if "비용차감손익(원)" in df_pnl.columns else total_pnl

            initial_capital = get_total_capital()
            turnover = total_inv / initial_capital if initial_capital > 0 else None
            adj_ret  = avg_ret * turnover if turnover is not None else None

            # KPI 요약
            c1, c2, c3 = st.columns(3)
            c1.metric("총 실현손익 (비용차감)", f"{total_net:+,.0f}원",
                      delta=f"거래비용 {total_fees:,.0f}원", delta_color="inverse")
            c2.metric("거래 건수",         f"{n}건")
            c3.metric("승/패",             f"{len(wins)}승 {len(losses)}패")

            c4, c5, c6 = st.columns(3)
            c4.metric("승률",              f"{win_rate:.1f}%")
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
            c5b.metric("목표손절 위반율",    f"{violation_rate:.1f}%")
            c6b.metric("패배 시 평균목표손절률",
                       f"{avg_planned_loss:.2f}%" if avg_planned_loss is not None else "-")

            rr_vals  = df_pnl["RR"].dropna()
            avg_rr   = rr_vals.mean() if len(rr_vals) > 0 else None

            c7, c8, c9 = st.columns(3)
            c7.metric("전체 평균수익률",    f"{avg_ret:+.2f}%")
            c8.metric("자산회전율",
                      f"{turnover:.2f}배" if turnover is not None else "원금 미설정")
            c9.metric("회전율 감안 수익률",
                      f"{adj_ret:+.2f}%" if adj_ret is not None else "원금 미설정")

            # 보유기간 KPI
            hold_vals      = df_pnl["보유일수"].dropna()
            win_hold_vals  = df_pnl[df_pnl["수익률(%)"] > 0]["보유일수"].dropna()
            loss_hold_vals = df_pnl[df_pnl["수익률(%)"] <= 0]["보유일수"].dropna()
            avg_hold_win   = win_hold_vals.mean()  if len(win_hold_vals)  > 0 else None
            avg_hold_loss  = loss_hold_vals.mean() if len(loss_hold_vals) > 0 else None

            c10, c11, c12 = st.columns(3)
            c10.metric("평균 RR (손절가 대비)",
                       f"{avg_rr:.2f}" if avg_rr is not None else "-")
            c11.metric("수익 시 평균보유기간",
                       f"{avg_hold_win:.0f}일" if avg_hold_win is not None else "-")
            c12.metric("손실 시 평균보유기간",
                       f"{avg_hold_loss:.0f}일" if avg_hold_loss is not None else "-")

            st.divider()

            _pnl_color_map = {"실현손익(원)": "red_positive", "비용차감손익(원)": "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
            _aggrid(df_pnl, key="trade_pnl_table", height=450, click_nav=False, color_map=_pnl_color_map, pct_cols=["수익률(%)", "비용차감수익률(%)"])

            st.divider()

            # ── 누적 수익 곡선 ──
            st.subheader("누적 수익 곡선")
            _render_equity_curve()

            st.divider()

            # ── 월별 성과 ──
            st.subheader("월별 성과")
            _render_monthly_performance()

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
                avg_win   = wins["수익률(%)"].mean()   if len(wins)   > 0 else 0
                avg_loss  = losses["수익률(%)"].mean() if len(losses) > 0 else 0
                avg_ret   = df_sub["수익률(%)"].mean()
                avg_planned_loss_p = losses["목표손절률(%)"].dropna().mean() if len(losses) > 0 else None
                losses_wt = losses.dropna(subset=["목표손절률(%)"])
                viols = losses_wt[losses_wt["수익률(%)"] < losses_wt["목표손절률(%)"]]
                n_viols    = len(viols)
                viol_rate  = n_viols / len(losses_wt) * 100 if len(losses_wt) > 0 else 0
                turnover  = total_inv / initial_capital_p if initial_capital_p > 0 else None
                adj_ret   = avg_ret * turnover if turnover is not None else None
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
                    "회전율감안수익률(%)":  round(adj_ret, 2) if adj_ret is not None else "-",
                    "평균RR":              round(avg_rr, 2) if avg_rr is not None else "-",
                    "수익시 평균보유일":    round(avg_hold_win,  0) if avg_hold_win  is not None else "-",
                    "손실시 평균보유일":    round(avg_hold_loss, 0) if avg_hold_loss is not None else "-",
                    "총 실현손익(원)":      round(total_pnl),
                    "거래비용(원)":         round(total_fees),
                    "비용차감손익(원)":     round(total_net),
                }

            # ── 1. 전체 성과분석 ──
            st.subheader("1. 전체 성과분석")
            overall = _kpi_metrics(df_pos_pnl)
            wins_p   = df_pos_pnl[df_pos_pnl["수익률(%)"] > 0]
            losses_p = df_pos_pnl[df_pos_pnl["수익률(%)"] <= 0]
            c1, c2, c3 = st.columns(3)
            c1.metric("총 실현손익 (비용차감)", f"{overall['비용차감손익(원)']:+,.0f}원",
                      delta=f"거래비용 {overall['거래비용(원)']:,.0f}원", delta_color="inverse")
            c2.metric("종목 수",            f"{overall['종목수']}종목")
            c3.metric("승/패",              overall["승/패"])
            _pl = overall["패배 평균목표손절률(%)"]
            _al = overall["패배 평균손실률(%)"]
            if _pl != "-":
                _diff2 = _al - _pl
                _delta2_txt = f"목표보다 {abs(_diff2):.2f}%p 절약 ✓" if _diff2 > 0 else f"목표보다 {abs(_diff2):.2f}%p 초과"
            else:
                _delta2_txt = None

            c4, c5, c6 = st.columns(3)
            c4.metric("승률",               f"{overall['승률(%)']:.1f}%")
            c5.metric("승리 시 평균수익률",  f"{overall['승리 평균수익률(%)']:+.2f}%")
            c6.metric("패배 시 평균손실률",  f"{overall['패배 평균손실률(%)']:+.2f}%",
                      delta=_delta2_txt, delta_color="normal")

            c4b, c5b, c6b = st.columns(3)
            c4b.metric("목표손절 위반 횟수", f"{overall['목표손절 위반 횟수']}회")
            c5b.metric("목표손절 위반율",    f"{overall['목표손절 위반율(%)']:.1f}%")
            c6b.metric("패배 시 평균목표손절률",
                       f"{_pl:.2f}%" if _pl != "-" else "-")
            c7, c8, c9 = st.columns(3)
            c7.metric("전체 평균수익률",     f"{overall['전체 평균수익률(%)']:+.2f}%")
            c8.metric("자산회전율",
                      f"{overall['자산회전율']:.2f}배" if overall['자산회전율'] != "-" else "원금 미설정")
            c9.metric("회전율 감안 수익률",
                      f"{overall['회전율감안수익률(%)']:+.2f}%" if overall['회전율감안수익률(%)'] != "-" else "원금 미설정")
            c10, c11, c12 = st.columns(3)
            c10.metric("평균 RR",
                       f"{overall['평균RR']:.2f}" if overall['평균RR'] != "-" else "-")
            c11.metric("수익 시 평균보유기간",
                       f"{overall['수익시 평균보유일']:.0f}일" if overall['수익시 평균보유일'] != "-" else "-")
            c12.metric("손실 시 평균보유기간",
                       f"{overall['손실시 평균보유일']:.0f}일" if overall['손실시 평균보유일'] != "-" else "-")

            st.divider()

            # ── 2. 종목별 성과분석 ──
            st.subheader("2. 종목별 성과분석")
            _pos_pnl_color_map = {"실현손익(원)": "red_positive", "비용차감손익(원)": "red_positive", "수익률(%)": "red_positive", "비용차감수익률(%)": "red_positive"}
            _pos_pnl_n = len(df_pos_pnl)
            _pos_pnl_height = 250 if _pos_pnl_n <= 5 else (350 if _pos_pnl_n <= 10 else 450)
            _aggrid(df_pos_pnl, key="position_pnl_table", height=_pos_pnl_height,
                    click_nav=False, color_map=_pos_pnl_color_map, pct_cols=["수익률(%)", "비용차감수익률(%)"])

            st.divider()

            # ── 3. 진입근거별 성과분석 ──
            st.subheader("3. 진입근거별 성과분석")
            reason_rows = []
            for prefix in ["PB", "HB", "BO"]:
                sub = df_pos_pnl[df_pos_pnl["진입근거"].str.startswith(prefix)]
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
                    "총 실현손익(원)":    "red_positive",
                }
                _aggrid(df_reason, key="reason_perf_table", height=250,
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
    _period = st.select_slider("분석 기간", options=[60, 120, 252], value=60,
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

elif st.session_state.view == "home":
    show_home()

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
        if st.button("🔄 강제 재계산", help="오늘 캐시를 삭제하고 전체 재계산합니다"):
            from market_ranking import CACHE_DIR
            today = datetime.now().strftime("%Y%m%d")
            # 오늘 파일 캐시만 삭제
            for f in CACHE_DIR.glob(f"ranking_*{today}.json"):
                f.unlink(missing_ok=True)
            # 세션 캐시 삭제 (랭킹 + VCP + 2단계)
            for k in [k for k in st.session_state if k.startswith("ranking_") or k.startswith("vcp_") or k.startswith("stage2_")]:
                del st.session_state[k]
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
