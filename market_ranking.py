"""
코스피 / 코스닥 전체 종목 RS 랭킹 계산

캐시 전략:
- 결과를 cache/ 디렉터리에 날짜별 JSON으로 저장
- 당일 캐시가 있으면 즉시 로드 (재시작/새로고침 무관)
- 당일 캐시가 없으면 전체 계산 후 저장
"""

import warnings
warnings.filterwarnings("ignore")

import json
import os
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
import pandas as pd
import FinanceDataReader as fdr

# HTTP 요청 타임아웃 전역 패치 (hang 방지)
_orig_request = requests.Session.request
def _request_with_timeout(self, method, url, **kwargs):
    kwargs.setdefault("timeout", 20)
    return _orig_request(self, method, url, **kwargs)
requests.Session.request = _request_with_timeout

from relative_strength import (
    fetch_data,
    align_data,
    trim_to_period,
    calculate_mas,
    calculate_ibd_rs,
)

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
MARKET_CONFIG = {
    "KOSPI":  dict(listing_code="KOSPI",  benchmark_code="KS11",   benchmark_name="KOSPI"),
    "KOSDAQ": dict(listing_code="KOSDAQ", benchmark_code="KQ11",   benchmark_name="KOSDAQ"),
    "NASDAQ": dict(listing_code="NASDAQ", benchmark_code="^IXIC",  benchmark_name="NASDAQ"),
    "NYSE":   dict(listing_code="NYSE",   benchmark_code="^GSPC",  benchmark_name="S&P 500"),
}

MAX_WORKERS    = 8   # 병렬 요청 수 (너무 많으면 rate limit)
REQUEST_TIMEOUT = 25  # 종목당 최대 대기 시간(초)

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────
# 파일 캐시 (날짜 기반)
# ─────────────────────────────────────────────

def _cache_path(market: str, period: int, date_str: str = None) -> Path:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    return CACHE_DIR / f"ranking_{market}_{period}d_{date_str}.json"


def _find_latest_cache_path(market: str, period: int) -> Optional[Path]:
    """오늘~7일 전까지 가장 최근 캐시 파일 탐색"""
    for i in range(8):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        path = CACHE_DIR / f"ranking_{market}_{period}d_{d}.json"
        if path.exists():
            return path
    return None


def _load_cache(market: str, period: int, today_only: bool = False) -> Optional[pd.DataFrame]:
    """캐시 파일이 있으면 DataFrame으로 반환.
    today_only=True: 오늘자 캐시만 확인 (precalc용)
    today_only=False: 오늘 없으면 최근 7일 폴백 (앱 조회용)
    """
    if today_only:
        path = _cache_path(market, period)
        if not path.exists():
            return None
    else:
        path = _find_latest_cache_path(market, period)
        if path is None:
            return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        df.index = pd.RangeIndex(start=1, stop=len(df) + 1)
        df.index.name = "순위"
        print(f"[캐시 로드] {path.name}  ({len(df)}건)")
        return df
    except Exception as e:
        print(f"[캐시 로드 실패] {e}")
        return None


def _save_cache(df: pd.DataFrame, market: str, period: int):
    """결과 DataFrame을 당일 캐시 파일로 저장 (과거 파일 보존)"""
    path = _cache_path(market, period)
    try:
        payload = {
            "saved_at": datetime.now().isoformat(),
            "market":   market,
            "period":   period,
            "columns":  list(df.columns),
            "rows":     df.values.tolist(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[캐시 저장] {path.name}")
    except Exception as e:
        print(f"[캐시 저장 실패] {e}")


def _filter_cache_path(filter_type: str, market: str, period: int, date_str: str = None) -> Path:
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    return CACHE_DIR / f"{filter_type}_{market}_{period}d_{date_str}.json"


def _find_latest_filter_cache_path(filter_type: str, market: str, period: int) -> Optional[Path]:
    """오늘~7일 전까지 가장 최근 필터 캐시 파일 탐색"""
    for i in range(8):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        path = CACHE_DIR / f"{filter_type}_{market}_{period}d_{d}.json"
        if path.exists():
            return path
    return None


def _load_filter_cache(filter_type: str, market: str, period: int) -> Optional[pd.DataFrame]:
    path = _find_latest_filter_cache_path(filter_type, market, period)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        print(f"[캐시 로드] {path.name}  ({len(df)}건)")
        return df
    except Exception as e:
        print(f"[캐시 로드 실패] {e}")
        return None


def _save_filter_cache(df: pd.DataFrame, filter_type: str, market: str, period: int):
    path = _filter_cache_path(filter_type, market, period)
    try:
        payload = {
            "saved_at": datetime.now().isoformat(),
            "filter":   filter_type,
            "market":   market,
            "period":   period,
            "columns":  list(df.columns),
            "rows":     df.values.tolist(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[캐시 저장] {path.name}")

        # vcp_pattern은 히스토리 폴더에도 영구 보관
        if filter_type == "vcp_pattern":
            history_dir = CACHE_DIR / "history"
            history_dir.mkdir(exist_ok=True)
            history_path = history_dir / path.name
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(f"[히스토리 저장] {history_path}")
    except Exception as e:
        print(f"[캐시 저장 실패] {e}")


def get_filter_cache_info(filter_type: str, market: str, period: int) -> Optional[str]:
    path = _find_latest_filter_cache_path(filter_type, market, period)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        saved = datetime.fromisoformat(data["saved_at"])
        return saved.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


def get_cache_info(market: str, period: int) -> Optional[str]:
    """캐시 파일의 저장 시각 문자열 반환 (없으면 None)"""
    path = _find_latest_cache_path(market, period)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        saved = datetime.fromisoformat(data["saved_at"])
        return saved.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


# ─────────────────────────────────────────────
# 종목 리스트 조회
# ─────────────────────────────────────────────

def _get_listing(market_code: str) -> pd.DataFrame:
    """전체 종목 리스트 조회 (Code, Name)"""
    df = fdr.StockListing(market_code)
    df.columns = [c.strip() for c in df.columns]

    code_col = next((c for c in df.columns if c in ("Code", "Symbol", "종목코드")), None)
    name_col = next((c for c in df.columns if c in ("Name", "종목명")), None)
    cap_col  = next((c for c in df.columns if c in ("Marcap", "시가총액", "MarCap")), None)

    if code_col is None or name_col is None:
        raise ValueError(f"종목 리스트 컬럼 오류: {df.columns.tolist()}")

    result = df[[code_col, name_col]].rename(columns={code_col: "Code", name_col: "Name"})

    if cap_col:
        result = result.assign(Marcap=pd.to_numeric(df[cap_col], errors="coerce"))
        result = result.sort_values("Marcap", ascending=False).drop(columns=["Marcap"])

    return result.dropna(subset=["Code"]).reset_index(drop=True)


# ─────────────────────────────────────────────
# 단일 종목 RS 계산 (벤치마크 데이터 공유)
# ─────────────────────────────────────────────

def _fetch_benchmark(benchmark_code: str, period: int) -> pd.DataFrame:
    """벤치마크 데이터를 한 번만 가져옴"""
    fetch_days = period * 3 + 30
    end_date   = datetime.now()
    start_date = end_date - timedelta(days=fetch_days)
    return fdr.DataReader(benchmark_code, start_date, end_date)


def _calc_rs_single(ticker: str, name: str, index_df: pd.DataFrame, period: int) -> Optional[dict]:
    """단일 종목 RS 계산 - 벤치마크는 외부에서 공유"""
    try:
        # 52주 신고가를 위해 최소 365일 확보
        fetch_days = max(365 + 30, period * 3 + 30)
        end_date   = datetime.now()
        start_date = end_date - timedelta(days=fetch_days)
        stock_df   = fdr.DataReader(ticker, start_date, end_date)

        if stock_df.empty:
            return None

        stock_full, index_full = align_data(stock_df, index_df)
        if len(stock_full) < 4:
            return None

        # 52주(252 거래일) 실제 신고가
        n = len(stock_full)
        high_window = stock_full.iloc[max(0, n - 252):]
        if high_window.empty:
            return None
        high_52w      = high_window["Close"].max()
        current_price = stock_full["Close"].iloc[-1]
        pct_from_high = round((current_price / high_52w - 1) * 100, 2)

        mas_full = calculate_mas(stock_full["Close"])
        s, i, _  = trim_to_period(stock_full, index_full, mas_full, period)
        rs_line, rs_score, stock_ret, index_ret = calculate_ibd_rs(s, i)

        return {
            "종목코드":    ticker,
            "종목명":      name,
            "RS Score":    round(rs_score, 2),
            "RS Line":     round(rs_line.iloc[-1], 2),
            "종목수익률":  round(stock_ret, 2),
            "지수수익률":  round(index_ret, 2),
            "현재가":      round(current_price, 2),
            "52주신고가":  round(high_52w, 2),
            "고가대비(%)": pct_from_high,
        }
    except Exception:
        return None


# ─────────────────────────────────────────────
# VCP 빠른 필터 (캐시 상위 종목에만 적용)
# ─────────────────────────────────────────────

def apply_vcp_filter(
    df: pd.DataFrame,
    market: str = "KOSPI",
    period: int = 20,
    vol_days: int = 5,
    vol_period: int = 60,
    range_pct: float = 7.0,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    캐시된 상위 종목에 대해 VCP 조건을 적용.
    당일 파일 캐시가 있으면 즉시 반환.

    조건1: 최근 vol_days일 평균 거래량 < vol_period일 평균 거래량
    조건2: 최근 vol_days일 각각 (고가-저가)/전일종가 ≤ range_pct%
    """
    if use_cache:
        cached = _load_filter_cache("vcp", market, period)
        if cached is not None:
            return cached
    if df.empty:
        return pd.DataFrame()

    end_date   = datetime.now()
    start_date = end_date - timedelta(days=vol_period * 2 + 30)

    vcp_tickers = []
    success_count = 0
    for _, row in df.iterrows():
        ticker = str(row["종목코드"])
        try:
            stock = fdr.DataReader(ticker, start_date, end_date)
            if stock.empty or "Volume" not in stock.columns:
                continue
            # FDR이 최신 날짜를 중복 행으로 반환하는 경우 제거 (미국 주식에서 발생)
            stock = stock[~stock.index.duplicated(keep='last')]
            if len(stock) < vol_period + vol_days + 1:
                continue

            success_count += 1
            last6       = stock.tail(vol_days + 1)
            last5       = last6.iloc[1:]
            prev_closes = last6["Close"].iloc[:-1].values
            vol_ma      = stock["Volume"].rolling(vol_period, min_periods=vol_period).mean().iloc[-1]

            if pd.isna(vol_ma) or vol_ma <= 0:
                continue

            vol_ok   = bool(last5["Volume"].mean() < vol_ma)
            hl_pct   = (last5["High"].values - last5["Low"].values) / prev_closes * 100
            range_ok = bool((hl_pct <= range_pct).all())

            if vol_ok and range_ok:
                vcp_tickers.append(ticker)
        except Exception:
            continue

    result = df[df["종목코드"].isin(vcp_tickers)].copy()
    # 실제로 처리된 종목이 입력의 10% 미만이면 네트워크 오류로 간주하고 캐시 저장 안 함
    if success_count >= max(1, len(df) * 0.1):
        _save_filter_cache(result, "vcp", market, period)
    return result


# ─────────────────────────────────────────────
# 2단계 시작 필터 (캐시 상위 종목에만 적용)
# ─────────────────────────────────────────────

def apply_stage2_filter(
    df: pd.DataFrame,
    market: str = "KOSPI",
    period: int = 20,
    slope_days: int = 10,
    cross_min: int = 20,   # MA60 돌파 후 최소 거래일 (1개월)
    cross_max: int = 40,   # MA60 돌파 후 최대 거래일 (2개월)
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    2단계 시작 조건 (스탠 와인스타인 기준):
    1. 종가 > MA20 > MA60  (상향 정렬)
    2. MA20 기울기 양수     (slope_days일 대비 상승)
    3. MA60 기울기 >= 0     (평탄 이상 - 하락 아님)
    4. MA60 돌파 시점이 cross_min~cross_max 거래일 이내 (1~2개월)
    """
    if use_cache:
        cached = _load_filter_cache("stage2", market, period)
        if cached is not None:
            return cached
    if df.empty:
        return pd.DataFrame()

    end_date   = datetime.now()
    start_date = end_date - timedelta(days=400)   # 돌파 시점 탐색을 위해 충분히 확보

    stage2_tickers = []
    for _, row in df.iterrows():
        ticker = str(row["종목코드"])
        try:
            stock = fdr.DataReader(ticker, start_date, end_date)
            if stock.empty or len(stock) < 65:
                continue
            stock = stock[~stock.index.duplicated(keep='last')]

            close = stock["Close"]
            ma20  = close.rolling(20, min_periods=20).mean()
            ma60  = close.rolling(60, min_periods=60).mean()

            c   = close.iloc[-1]
            m20 = ma20.iloc[-1]
            m60 = ma60.iloc[-1]

            if pd.isna(m20) or pd.isna(m60):
                continue

            # 조건1: Close > MA20 > MA60
            align_ok = bool(c > m20 > m60)
            if not align_ok:
                continue

            # 조건2: MA20 기울기 양수
            m20_prev = ma20.iloc[-(slope_days + 1)]
            ma20_up  = bool(not pd.isna(m20_prev) and m20 > m20_prev)
            if not ma20_up:
                continue

            # 조건3: MA60 기울기 >= 0 (하락하지 않음)
            m60_prev  = ma60.iloc[-(slope_days + 1)]
            ma60_flat = bool(not pd.isna(m60_prev) and m60 >= m60_prev)
            if not ma60_flat:
                continue

            # 조건4: MA60 돌파 시점이 1~3개월 이내
            # above: 종가 > MA60 인 날, 그 이전에 아래였던 마지막 교차 지점 탐색
            above = (close > ma60).dropna()
            valid = above.dropna()
            if len(valid) < 2:
                continue

            # 가장 최근 "아래→위" 크로스오버 인덱스 찾기
            cross_idx = None
            for i in range(len(valid) - 1, 0, -1):
                if valid.iloc[i] and not valid.iloc[i - 1]:
                    cross_idx = i  # valid 배열 내 위치
                    break

            if cross_idx is None:
                continue

            # 돌파 이후 경과 거래일 수
            days_since_cross = len(valid) - 1 - cross_idx
            if cross_min <= days_since_cross <= cross_max:
                stage2_tickers.append(ticker)
        except Exception:
            continue

    result = df[df["종목코드"].isin(stage2_tickers)].copy()
    _save_filter_cache(result, "stage2", market, period)
    return result


# ─────────────────────────────────────────────
# 메인: 랭킹 계산 (캐시 우선)
# ─────────────────────────────────────────────

def refresh_52w_high(market: str, period: int):
    """
    기존 캐시의 52주 신고가만 종가 기준으로 재계산 (빠름 - 상위 30종목만).
    캐시 파일을 덮어씀.
    """
    cached = _load_cache(market, period)
    if cached is None or cached.empty:
        return False
    if "52주신고가" not in cached.columns:
        return False

    end_date   = datetime.now()
    start_date = end_date - timedelta(days=395)

    updated = []
    for _, row in cached.iterrows():
        ticker = row["종목코드"]
        try:
            df = fdr.DataReader(ticker, start_date, end_date)
            if df.empty:
                updated.append(row)
                continue
            df = df[~df.index.duplicated(keep='last')]
            high_52w      = df["Close"].tail(252).max()
            current_price = df["Close"].iloc[-1]
            pct_from_high = round((current_price / high_52w - 1) * 100, 2)
            row = row.copy()
            row["52주신고가"]  = round(high_52w, 2)
            row["현재가"]      = round(current_price, 2)
            row["고가대비(%)"] = pct_from_high
        except Exception:
            pass
        updated.append(row)

    df_updated = pd.DataFrame(updated)
    df_updated.index = pd.RangeIndex(start=1, stop=len(df_updated) + 1)
    df_updated.index.name = "순위"
    _save_cache(df_updated, market, period)
    print(f"[{market}] 52주 신고가 종가 기준 업데이트 완료")
    return True


# ─────────────────────────────────────────────
# VCP 패턴 스캐너 (Pattern Scanner 전용)
# ─────────────────────────────────────────────

def _detect_vcp_single(
    ticker: str,
    name: str,
    rs_score: float,
    rs_rank_pct: float,
    max_base_days: int = 252,
    max_swing_days: int = 10,
    min_t: int = 2,
    vol_days: int = 5,
    vol_period: int = 60,
) -> Optional[dict]:
    """단일 종목 VCP 패턴 감지"""
    try:
        end_date   = datetime.now()
        start_date = end_date - timedelta(days=max_base_days + vol_period + 90)
        df = fdr.DataReader(ticker, start_date, end_date)
        if df.empty or len(df) < 30:
            return None
        df = df[~df.index.duplicated(keep='last')]

        close  = df["Close"]
        volume = df["Volume"] if "Volume" in df.columns else None

        # 거래량 수축 체크 (빠른 사전 필터)
        if volume is None or len(volume) < vol_period:
            return None
        vol_recent = float(volume.iloc[-vol_days:].mean())
        vol_ma     = float(volume.iloc[-vol_period:].mean())
        if vol_ma <= 0 or vol_recent >= vol_ma:
            return None
        vol_ratio = round(vol_recent / vol_ma * 100, 1)

        # ── 2단계 조건 (스탠 와인스타인 기준) ──────────────
        if len(close) < 65:
            return None
        ma20 = close.rolling(20, min_periods=20).mean()
        ma60 = close.rolling(60, min_periods=60).mean()
        c_last  = float(close.iloc[-1])
        m20     = float(ma20.iloc[-1])
        m60     = float(ma60.iloc[-1])
        if pd.isna(m20) or pd.isna(m60):
            return None
        # MA120, MA200 계산
        ma120 = close.rolling(120, min_periods=120).mean()
        ma200 = close.rolling(200, min_periods=200).mean()
        m120  = float(ma120.iloc[-1]) if not pd.isna(ma120.iloc[-1]) else None
        m200  = float(ma200.iloc[-1]) if not pd.isna(ma200.iloc[-1]) else None

        # 조건1: Close > MA60, MA20 > MA60 (VCP 수축 중 MA20 하회 허용)
        if not (c_last > m60 and m20 > m60):
            return None

        # 조건1-b: 정배열 MA60 > MA120 > MA200
        if m120 is None or m200 is None:
            return None
        if not (m60 > m120 > m200):
            return None
        # 조건2: MA20 기울기 양수
        slope_days = 10
        m20_prev = ma20.iloc[-(slope_days + 1)]
        if pd.isna(m20_prev) or m20 <= m20_prev:
            return None
        # 조건3: MA60 기울기 >= 0
        m60_prev = ma60.iloc[-(slope_days + 1)]
        if pd.isna(m60_prev) or m60 < m60_prev:
            return None
        # 조건4: MA60 돌파 후 20~40 거래일 이내
        above = (close > ma60).dropna()
        cross_idx = None
        for ci in range(len(above) - 1, 0, -1):
            if above.iloc[ci] and not above.iloc[ci - 1]:
                cross_idx = ci
                break
        if cross_idx is None:
            return None
        days_since_cross = len(above) - 1 - cross_idx
        if days_since_cross > 120:
            return None
        # ────────────────────────────────────────────────────

        # 베이스 구간 설정 (최근 max_base_days 거래일)
        close_window  = close.iloc[-max_base_days:] if len(close) >= max_base_days else close
        base_top_loc  = int(close_window.values.argmax())
        base_top_price = float(close_window.iloc[base_top_loc])
        current_price  = float(close_window.iloc[-1])
        base_period    = len(close_window) - 1 - base_top_loc

        # 현재가가 베이스 상단 98% 이상이면 이미 돌파 중 → 제외
        if current_price >= base_top_price * 0.98:
            return None
        if base_period < 15:
            return None

        # 베이스 상단 이후 구간
        base_close = close_window.iloc[base_top_loc + 1:]
        if len(base_close) < 10:
            return None

        # 로컬 고점 탐색 (3일 윈도우)
        win = 3
        local_highs = []  # (position, price)
        for i in range(win, len(base_close) - win):
            c         = float(base_close.iloc[i])
            neighbors = base_close.iloc[i - win : i + win + 1]
            if c >= float(neighbors.max()) * 0.999:
                if not local_highs or (i - local_highs[-1][0]) >= win:
                    local_highs.append((i, c))

        if len(local_highs) < min_t + 1:
            return None

        # 연속 로컬 고점 간 스윙 범위 계산
        swings = []
        for j in range(len(local_highs) - 1):
            p1, h1    = local_highs[j]
            p2, _     = local_highs[j + 1]
            swing_days = p2 - p1
            if swing_days > max_swing_days:
                continue
            seg       = base_close.iloc[p1 : p2 + 1]
            seg_max   = float(seg.max())
            seg_min   = float(seg.min())
            if seg_max <= 0:
                continue
            range_pct = (seg_max - seg_min) / seg_max * 100
            swings.append({
                "pos":        p1,
                "high_price": h1,
                "range_pct":  range_pct,
                "swing_days": swing_days,
            })

        if len(swings) < min_t:
            return None

        # 가장 긴 연속 수축 시퀀스 탐색
        best_t   = 0
        best_seq = []
        for start_idx in range(len(swings)):
            seq = [swings[start_idx]]
            for k in range(start_idx + 1, len(swings)):
                if swings[k]["range_pct"] < seq[-1]["range_pct"]:
                    seq.append(swings[k])
                else:
                    break
            if len(seq) > best_t:
                best_t   = len(seq)
                best_seq = seq

        if best_t < min_t:
            return None

        # 수축 강도: 첫 스윙 대비 마지막 스윙 범위 감소율
        first_range = best_seq[0]["range_pct"]
        last_range  = best_seq[-1]["range_pct"]
        if first_range <= 0:
            return None
        contraction_strength = round((first_range - last_range) / first_range * 100, 1)

        # 피벗 = 1차 스윙 고점 (베이스 내 첫 번째 수축 구간의 고점 = 전고점 돌파 기준)
        pivot          = round(best_seq[0]["high_price"])
        pivot_dist_pct = round((pivot - current_price) / current_price * 100, 2)

        # 이미 피벗 위에 있으면 제외 (돌파 후)
        if pivot_dist_pct < 0:
            return None

        return {
            "종목코드":      ticker,
            "종목명":        name,
            "RS Score":      round(rs_score, 2),
            "RS순위(%)":     round(rs_rank_pct, 1),
            "수축(T)":       best_t,
            "수축강도(%)":   contraction_strength,
            "피벗":          pivot,
            "현재가":        round(current_price),
            "피벗거리(%)":   pivot_dist_pct,
            "거래량비율(%)": vol_ratio,
            "베이스상단":    round(base_top_price),
            "베이스기간(일)": base_period,
        }
    except Exception:
        return None


def scan_vcp_patterns(
    market: str = "KOSPI",
    period: int = 20,
    top_pct: float = 0.7,
    max_base_days: int = 252,
    max_swing_days: int = 10,
    min_t: int = 2,
    use_cache: bool = True,
    progress_cb=None,
) -> pd.DataFrame:
    """
    VCP 우선 패턴 스캐너.
    RS 상위 top_pct 이내 종목에서 VCP 패턴 감지.

    정렬: 피벗거리(%) 오름차순 → 수축강도(%) 내림차순
    """
    cache_type = "vcp_pattern"
    if use_cache:
        cached = _load_filter_cache(cache_type, market, period)
        if cached is not None:
            return cached

    # RS 전체 랭킹 로드 (캐시 우선, top_n=9999로 전체 가져오기)
    df_rank = calc_market_ranking(market=market, period=period, top_n=9999)
    if df_rank.empty:
        return pd.DataFrame()

    # RS 상위 top_pct 종목 추출
    n_total      = len(df_rank)
    n_candidates = max(1, int(n_total * top_pct))
    df_cands     = df_rank.head(n_candidates).reset_index(drop=True)
    total        = len(df_cands)

    results = []
    done    = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                _detect_vcp_single,
                str(row["종목코드"]),
                str(row["종목명"]),
                float(row["RS Score"]),
                round((idx + 1) / n_total * 100, 1),
                max_base_days,
                max_swing_days,
                min_t,
            ): idx
            for idx, row in df_cands.iterrows()
        }
        for future in as_completed(future_map):
            done += 1
            if progress_cb:
                progress_cb(done, total)
            try:
                result = future.result(timeout=REQUEST_TIMEOUT)
                if result:
                    results.append(result)
            except Exception:
                pass

    if not results:
        return pd.DataFrame()

    df_result = (
        pd.DataFrame(results)
        .sort_values(["피벗거리(%)", "수축강도(%)"], ascending=[True, False])
        .reset_index(drop=True)
    )
    df_result.index     += 1
    df_result.index.name = "순위"

    _save_filter_cache(df_result, cache_type, market, period)
    print(f"[VCP 스캔] {market} 완료: {len(df_result)}개 패턴 발견 (후보 {total}종목 중)")
    return df_result


def get_vcp_pattern_cache_info(market: str, period: int) -> Optional[str]:
    """VCP 패턴 캐시 저장 시각 반환"""
    return get_filter_cache_info("vcp_pattern", market, period)


# ─────────────────────────────────────────────
# Short Scanner (Stage 4 + 인버스 ETF 매핑)
# ─────────────────────────────────────────────

# 원본 종목 → 인버스 ETF 매핑
INVERSE_ETF_MAP = {
    # ── 개별종목 인버스 ──
    "TSLA": {"name": "Tesla", "inverse": [("TSLS", "TSLA Bear 1X")]},
    "NVDA": {"name": "NVIDIA", "inverse": [("NVDS", "NVDA Bear 1.25X"), ("NVDQ", "NVDA Bear 2X")]},
    "AAPL": {"name": "Apple", "inverse": [("AAPD", "AAPL Bear 1X")]},
    "AMZN": {"name": "Amazon", "inverse": [("AMZD", "AMZN Bear 1X")]},
    "MSFT": {"name": "Microsoft", "inverse": [("MSFD", "MSFT Bear 1X")]},
    "META": {"name": "Meta", "inverse": [("METD", "META Bear 1X")]},
    "GOOGL": {"name": "Alphabet", "inverse": [("GGLS", "GOOGL Bear 1X")]},
    "AMD": {"name": "AMD", "inverse": [("AMDD", "AMD Bear 1X")]},
    "COIN": {"name": "Coinbase", "inverse": [("CONL", "COIN Short 2X")]},
    # ── 지수 인버스 ──
    "SPY": {"name": "S&P500", "inverse": [("SH", "S&P500 Short 1X"), ("SPXS", "S&P500 Bear 3X")]},
    "QQQ": {"name": "Nasdaq100", "inverse": [("PSQ", "QQQ Short 1X"), ("SQQQ", "QQQ Bear 3X")]},
    "DIA": {"name": "Dow30", "inverse": [("DOG", "Dow30 Short 1X"), ("SDOW", "Dow30 Bear 3X")]},
    "IWM": {"name": "Russell2000", "inverse": [("RWM", "Russell2000 Short 1X"), ("TZA", "Russell2000 Bear 3X")]},
    # ── 섹터 인버스 ──
    "SOXX": {"name": "반도체", "inverse": [("SOXS", "반도체 Bear 3X")]},
    "XLK": {"name": "기술", "inverse": [("TECS", "기술 Bear 3X")]},
    "XLF": {"name": "금융", "inverse": [("SEF", "금융 Short 1X"), ("FAZ", "금융 Bear 3X")]},
    "XLE": {"name": "에너지", "inverse": [("ERY", "에너지 Bear 2X")]},
    "XBI": {"name": "바이오", "inverse": [("LABD", "바이오 Bear 3X")]},
    # ── 해외/채권 인버스 ──
    "FXI": {"name": "중국", "inverse": [("YXI", "중국 Short 1X"), ("YANG", "중국 Bear 3X")]},
    "TLT": {"name": "장기국채", "inverse": [("TBF", "장기국채 Short 1X"), ("TBT", "장기국채 Short 2X"), ("TMV", "장기국채 Bear 3X")]},
}


def _check_stage4_single(ticker: str, name: str, rs_score: float, rs_pct: float) -> Optional[dict]:
    """
    Stage 4 시작 감지:
    - 돌파 임박: 200일선 위 5% 이내 + MA20 하락 중
    - 돌파 초기: 200일선 하방 돌파 후 20거래일 이내
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=400)
        stock = fdr.DataReader(ticker, start_date, end_date)
        if stock.empty or len(stock) < 200:
            return None
        stock = stock[~stock.index.duplicated(keep='last')]

        close = stock["Close"]
        ma20 = close.rolling(20, min_periods=20).mean()
        ma60 = close.rolling(60, min_periods=60).mean()
        ma200 = close.rolling(200, min_periods=200).mean()

        c = close.iloc[-1]
        m20 = ma20.iloc[-1]
        m60 = ma60.iloc[-1]
        m200 = ma200.iloc[-1]

        if pd.isna(m20) or pd.isna(m60) or pd.isna(m200):
            return None

        # MA20 기울기 음수 (하락 전환 중) — 공통 조건
        m20_prev = ma20.iloc[-11] if len(ma20) > 11 else ma20.iloc[0]
        if pd.isna(m20_prev) or m20 >= m20_prev:
            return None

        ma200_gap = round((c / m200 - 1) * 100, 2)

        if c < m200:
            # ── 돌파 초기: 200일선 아래 ──
            above_ma200 = (close > ma200).dropna()
            if len(above_ma200) < 2:
                return None

            cross_idx = None
            for i in range(len(above_ma200) - 1, 0, -1):
                if not above_ma200.iloc[i] and above_ma200.iloc[i - 1]:
                    cross_idx = i
                    break

            if cross_idx is None:
                return None

            days_since_cross = len(above_ma200) - 1 - cross_idx
            if days_since_cross > 20:
                return None

            status = "돌파 초기"
            days_label = days_since_cross

        elif ma200_gap <= 5.0:
            # ── 돌파 임박: 200일선 위 5% 이내 ──
            status = "돌파 임박"
            days_label = None
        else:
            return None

        # 거래량 비율 (5일/20일)
        vol = stock["Volume"]
        vol_5 = vol.tail(5).mean()
        vol_20 = vol.tail(20).mean()
        vol_ratio = round(vol_5 / vol_20 * 100, 1) if vol_20 > 0 else 0

        # 52주 고점 대비
        high_52w = close.tail(252).max()
        from_high = round((c / high_52w - 1) * 100, 1)

        # 인버스 ETF 정보
        inv_info = INVERSE_ETF_MAP.get(ticker, {})
        inv_tickers = ", ".join([t for t, _ in inv_info.get("inverse", [])])

        return {
            "종목코드": ticker,
            "종목명": name,
            "상태": status,
            "현재가": round(c, 2),
            "200일선대비(%)": ma200_gap,
            "고점대비(%)": from_high,
            "돌파경과(일)": days_label,
            "거래량비율(%)": vol_ratio,
            "인버스ETF": inv_tickers,
        }
    except Exception:
        return None


def scan_short_candidates(
    period: int = 60,
    use_cache: bool = True,
    progress_cb=None,
) -> pd.DataFrame:
    """
    Short Scanner: 인버스 ETF가 있는 종목 중 Stage 4 진입 종목 탐색.
    미국 대형주 + 지수 대상.
    """
    cache_type = "short"
    market = "SHORT"
    if use_cache:
        cached = _load_filter_cache(cache_type, market, period)
        if cached is not None:
            return cached

    # 인버스 ETF 매핑된 종목만 대상
    targets = list(INVERSE_ETF_MAP.keys())
    total = len(targets)
    results = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                _check_stage4_single,
                ticker,
                INVERSE_ETF_MAP[ticker]["name"],
                0.0,  # RS Score는 별도 계산 안 함
                0.0,
            ): ticker
            for ticker in targets
        }
        for future in as_completed(future_map):
            done += 1
            if progress_cb:
                progress_cb(done, total)
            try:
                result = future.result(timeout=REQUEST_TIMEOUT)
                if result:
                    results.append(result)
            except Exception:
                pass

    if not results:
        empty_df = pd.DataFrame()
        _save_filter_cache(empty_df, cache_type, market, period)
        return empty_df

    df_result = (
        pd.DataFrame(results)
        .sort_values("200일선대비(%)", ascending=True)
        .reset_index(drop=True)
    )
    df_result.index += 1
    df_result.index.name = "순위"

    _save_filter_cache(df_result, cache_type, market, period)
    print(f"[Short Scanner] 완료: {len(df_result)}개 종목 (대상 {total}종목 중)")
    return df_result


def get_short_cache_info(period: int = 60) -> Optional[str]:
    """Short Scanner 캐시 저장 시각 반환"""
    return get_filter_cache_info("short", "SHORT", period)


def calc_market_ranking(
    market: str = "KOSPI",
    period: int = 20,
    top_n: int = 100,
    min_price: float = 0,
    progress_cb=None,
    today_only: bool = False,
) -> pd.DataFrame:
    """
    시장 전체 RS 랭킹 반환.
    - 당일 캐시 있음 → 즉시 반환
    - 당일 캐시 없음 → 전체 계산 후 저장 → 반환
    today_only=True: 오늘 캐시만 확인 (precalc용 — 폴백 안 함)
    """
    # ① 캐시 확인
    cached = _load_cache(market, period, today_only=today_only)
    if cached is not None:
        return cached.head(top_n)

    # ② 벤치마크 1회만 가져오기
    cfg            = MARKET_CONFIG[market]
    print(f"[{market}] 벤치마크 {cfg['benchmark_code']} 수집 중...")
    index_df_full  = _fetch_benchmark(cfg["benchmark_code"], period)

    # ③ 전체 종목 리스트
    listing = _get_listing(cfg["listing_code"])
    total   = len(listing)
    results = []
    done    = 0

    print(f"[{market}] 전체 {total}종목 RS 계산 시작 (병렬 {MAX_WORKERS}개)...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                _calc_rs_single,
                row["Code"], row["Name"], index_df_full, period
            ): row["Code"]
            for _, row in listing.iterrows()
        }
        for future in as_completed(future_map):
            done += 1
            if progress_cb:
                progress_cb(done, total)
            try:
                result = future.result(timeout=REQUEST_TIMEOUT)
                if result:
                    results.append(result)
            except Exception:
                pass  # 타임아웃/오류 종목은 건너뜀

    if not results:
        return pd.DataFrame()

    df_full = (
        pd.DataFrame(results)
        .sort_values("RS Score", ascending=False)
        .reset_index(drop=True)
    )

    if min_price > 0:
        df_full = df_full[df_full["현재가"] >= min_price].reset_index(drop=True)

    df_full.index += 1
    df_full.index.name = "순위"

    _save_cache(df_full, market, period)
    print(f"[{market}] 완료: {len(df_full)}종목 계산, 상위 {top_n}종목 반환")
    return df_full.head(top_n)
