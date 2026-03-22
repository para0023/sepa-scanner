"""
백테스트 모듈
- 일중반전(Intraday Reversal) 패턴 감지 및 이후 수익률 분석
- 신호(진입+분배) 동시 적색 백테스트
"""

import warnings
warnings.filterwarnings("ignore")

import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import FinanceDataReader as fdr

from market_ranking import (
    calc_market_ranking,
    CACHE_DIR,
    MAX_WORKERS,
    REQUEST_TIMEOUT,
)


# ─────────────────────────────────────────────
# 거래량 구간 분류
# ─────────────────────────────────────────────

def _vol_band(ratio_pct: float) -> str:
    """거래량비율(%)을 구간 문자열로 변환"""
    if ratio_pct >= 300:
        return "300%+"
    elif ratio_pct >= 200:
        return "200~300%"
    elif ratio_pct >= 150:
        return "150~200%"
    else:
        return "120~150%"


# ─────────────────────────────────────────────
# 캐시 헬퍼
# ─────────────────────────────────────────────

def _backtest_cache_path(market: str, lookback_days: int) -> Path:
    today = datetime.now().strftime("%Y%m%d")
    return CACHE_DIR / f"backtest_intraday_{market}_{lookback_days}d_{today}.json"


def _load_backtest_cache(market: str, lookback_days: int):
    path = _backtest_cache_path(market, lookback_days)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        print(f"[백테스트 캐시 로드] {path.name}  ({len(df)}건)")
        return df
    except Exception as e:
        print(f"[백테스트 캐시 로드 실패] {e}")
        return None


def _save_backtest_cache(df: pd.DataFrame, market: str, lookback_days: int):
    path = _backtest_cache_path(market, lookback_days)
    try:
        payload = {
            "saved_at": datetime.now().isoformat(),
            "market": market,
            "lookback_days": lookback_days,
            "columns": list(df.columns),
            "rows": df.values.tolist(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[백테스트 캐시 저장] {path.name}")
    except Exception as e:
        print(f"[백테스트 캐시 저장 실패] {e}")


def get_backtest_cache_info(market: str, lookback_days: int):
    """캐시 저장 시각 문자열 반환 (없으면 None)"""
    path = _backtest_cache_path(market, lookback_days)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        saved = datetime.fromisoformat(data["saved_at"])
        return saved.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


# ─────────────────────────────────────────────
# 단일 종목 반전 감지
# ─────────────────────────────────────────────

def _detect_reversals_single(
    ticker: str,
    name: str,
    rs_score: float,
    rs_rank_pct: float,
    lookback_days: int,
    vol_period: int,
    vol_threshold: float,
) -> list:
    """
    단일 종목에서 일중반전 이벤트를 감지하고 이후 수익률을 계산한다.
    반환: 이벤트 dict 리스트
    """
    try:
        fetch_days = lookback_days * 2 + vol_period + 30
        end = datetime.now()
        start = end - timedelta(days=fetch_days)

        df = fdr.DataReader(ticker, start, end)
        if df is None or df.empty:
            return []

        # 중복 인덱스 제거
        df = df[~df.index.duplicated(keep="last")]
        df = df.sort_index()

        required_cols = {"High", "Low", "Close", "Volume"}
        if not required_cols.issubset(df.columns):
            return []

        df = df.dropna(subset=["High", "Low", "Close", "Volume"])
        if len(df) < vol_period + 21:
            return []

        # 감지 시작 기준일 (lookback_days 이내만)
        cutoff_date = datetime.now() - timedelta(days=lookback_days)

        events = []

        for i in range(1, len(df) - 20):
            date_idx = df.index[i]
            # timezone-naive 비교
            if hasattr(date_idx, "tzinfo") and date_idx.tzinfo is not None:
                date_naive = date_idx.replace(tzinfo=None)
            else:
                date_naive = date_idx

            if pd.Timestamp(date_naive) < pd.Timestamp(cutoff_date):
                continue

            # 60일 평균 거래량 (현재 바 이전)
            vol_start = max(0, i - vol_period)
            avg_vol = df["Volume"].iloc[vol_start:i].mean()
            if avg_vol <= 0:
                continue

            today_bar = df.iloc[i]
            prev_bar = df.iloc[i - 1]

            # 일중반전 조건
            cond_high = today_bar["High"] > prev_bar["High"]
            cond_close = today_bar["Close"] < prev_bar["Close"]
            vol_ratio = today_bar["Volume"] / avg_vol
            cond_vol = vol_ratio >= vol_threshold

            # 전일 상승률 5% 이상 (급등 후 반전만 포착)
            if i >= 2:
                prev_prev_close = df["Close"].iloc[i - 2]
                cond_prev_surge = prev_prev_close > 0 and (prev_bar["Close"] / prev_prev_close - 1) >= 0.05
            else:
                cond_prev_surge = False

            if not (cond_high and cond_close and cond_vol and cond_prev_surge):
                continue

            # 이후 20영업일 수익률 계산
            ref_close = today_bar["Close"]
            forward = df["Close"].iloc[i + 1 : i + 21]
            if len(forward) < 20:
                continue

            ret_1d = (forward.iloc[0] / ref_close - 1) * 100 if len(forward) >= 1 else None
            ret_3d = (forward.iloc[2] / ref_close - 1) * 100 if len(forward) >= 3 else None
            ret_5d = (forward.iloc[4] / ref_close - 1) * 100 if len(forward) >= 5 else None
            ret_10d = (forward.iloc[9] / ref_close - 1) * 100 if len(forward) >= 10 else None
            ret_20d = (forward.iloc[19] / ref_close - 1) * 100 if len(forward) >= 20 else None
            max_dd_20d = (forward.min() / ref_close - 1) * 100

            vol_ratio_pct = vol_ratio * 100

            events.append({
                "날짜": pd.Timestamp(date_naive).strftime("%Y-%m-%d"),
                "종목코드": ticker,
                "종목명": name,
                "RS Score": round(rs_score, 1),
                "RS순위백분위(%)": rs_rank_pct,
                "거래량비율(%)": round(vol_ratio_pct, 1),
                "거래량구간": _vol_band(vol_ratio_pct),
                "1일": round(ret_1d, 2) if ret_1d is not None else None,
                "3일": round(ret_3d, 2) if ret_3d is not None else None,
                "5일": round(ret_5d, 2) if ret_5d is not None else None,
                "10일": round(ret_10d, 2) if ret_10d is not None else None,
                "20일": round(ret_20d, 2) if ret_20d is not None else None,
                "20일최대낙폭": round(max_dd_20d, 2),
            })

        return events

    except Exception as e:
        print(f"[백테스트] {ticker} 오류: {e}")
        return []


# ─────────────────────────────────────────────
# 메인 백테스트 함수
# ─────────────────────────────────────────────

def run_intraday_reversal_backtest(
    market: str = "KOSPI",
    lookback_days: int = 252,
    vol_threshold: float = 1.2,
    vol_period: int = 60,
    use_cache: bool = True,
    progress_cb=None,
) -> pd.DataFrame:
    """
    일중반전 패턴 백테스트를 실행하고 결과 DataFrame을 반환한다.

    일중반전 조건:
      - 당일 고가 > 전일 고가
      - 당일 종가 < 전일 종가
      - 당일 거래량 >= 60일 평균 거래량 × vol_threshold
    """
    # ① 캐시 확인
    if use_cache:
        cached = _load_backtest_cache(market, lookback_days)
        if cached is not None:
            return cached

    # ② RS 랭킹 조회 (전 종목)
    print(f"[백테스트] {market} RS 랭킹 조회 중...")
    ranking_df = calc_market_ranking(market, period=60, top_n=9999)
    if ranking_df is None or ranking_df.empty:
        print(f"[백테스트] {market} 랭킹 데이터 없음")
        return pd.DataFrame()

    # 랭킹 DataFrame 컬럼 확인
    ticker_col = "종목코드" if "종목코드" in ranking_df.columns else "Code"
    name_col = "종목명" if "종목명" in ranking_df.columns else "Name"
    rs_col = "RS Score" if "RS Score" in ranking_df.columns else "RS"

    tickers = ranking_df[ticker_col].tolist()
    names = ranking_df[name_col].tolist()
    rs_scores = ranking_df[rs_col].tolist()
    n_total = len(tickers)

    # RS순위백분위: 인덱스 0(최고) → ~0%, 끝 → ~100%
    rs_rank_pcts = [round((idx + 1) / n_total * 100, 1) for idx in range(n_total)]

    print(f"[백테스트] {market} {n_total}종목 반전 감지 시작...")

    all_events = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                _detect_reversals_single,
                tickers[i],
                names[i],
                rs_scores[i],
                rs_rank_pcts[i],
                lookback_days,
                vol_period,
                vol_threshold,
            ): tickers[i]
            for i in range(n_total)
        }

        for future in as_completed(future_map):
            done += 1
            if progress_cb:
                progress_cb(done, n_total)
            try:
                events = future.result(timeout=REQUEST_TIMEOUT)
                if events:
                    all_events.extend(events)
            except Exception:
                pass

    print(f"[백테스트] {market} 완료: {len(all_events)}건 이벤트 발견")

    if not all_events:
        return pd.DataFrame()

    result_df = pd.DataFrame(all_events)
    result_df = result_df.sort_values("날짜", ascending=False).reset_index(drop=True)

    # ③ 캐시 저장
    if use_cache:
        _save_backtest_cache(result_df, market, lookback_days)

    return result_df


# ─────────────────────────────────────────────
# 신호 백테스트: 진입+분배 동시 적색
# ─────────────────────────────────────────────

from relative_strength import calc_entry_signal, calc_sell_signal


def _signal_cache_path(market: str, lookback_days: int) -> Path:
    return CACHE_DIR / f"signal_bt_{market}_{lookback_days}d_{datetime.now():%Y%m%d}.json"


def _load_signal_cache(market: str, lookback_days: int):
    p = _signal_cache_path(market, lookback_days)
    if p.exists():
        return pd.read_json(p, orient="records")
    return None


def _save_signal_cache(df: pd.DataFrame, market: str, lookback_days: int):
    p = _signal_cache_path(market, lookback_days)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(p, orient="records", force_ascii=False, indent=2)


def get_signal_cache_info(market: str, lookback_days: int) -> str:
    p = _signal_cache_path(market, lookback_days)
    if p.exists():
        from datetime import datetime as dt
        ts = dt.fromtimestamp(p.stat().st_mtime)
        return ts.strftime("%Y-%m-%d %H:%M")
    return ""


def _detect_signal_events_single(
    ticker: str,
    name: str,
    rs_score: float,
    lookback_days: int,
    entry_threshold: float,
    dist_threshold: float,
    forward_days: int,
) -> list:
    """
    단일 종목에서 진입신호 + 분배신호 동시 적색 이벤트를 감지하고
    이후 forward_days 거래일 수익률을 계산한다.
    """
    try:
        fetch_days = lookback_days * 2 + 100
        end = datetime.now()
        start = end - timedelta(days=fetch_days)

        df = fdr.DataReader(ticker, start, end)
        if df is None or df.empty:
            return []

        df = df[~df.index.duplicated(keep="last")].sort_index()
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return []
        df = df.dropna(subset=list(required))
        if len(df) < 80:
            return []

        entry_sig = calc_entry_signal(df)
        dist_sig  = calc_sell_signal(df)

        cutoff = datetime.now() - timedelta(days=lookback_days)
        events = []

        for i in range(len(df) - forward_days):
            date_idx = df.index[i]
            date_naive = date_idx.replace(tzinfo=None) if hasattr(date_idx, "tzinfo") and date_idx.tzinfo else date_idx
            if pd.Timestamp(date_naive) < pd.Timestamp(cutoff):
                continue

            e_val = float(entry_sig.iloc[i])
            d_val = float(dist_sig.iloc[i])

            if e_val < entry_threshold or d_val < dist_threshold:
                continue

            # ── 추세 필터: 이미 MA20 위에서 상승 중일 때만 ──
            # (상승 추세에서의 분배만 포착, 베이스 BO나 하락 중은 제외)
            if i < 20:
                continue
            closes = df["Close"].iloc[:i+1]
            ma20 = float(closes.iloc[-20:].mean())
            cur_close = float(closes.iloc[-1])
            if cur_close <= ma20:
                continue
            # 최근 10일 중 7일 이상 MA20 위 (안정적 상승 추세 확인)
            above_count = 0
            for k in range(max(0, i-9), i+1):
                if k >= 20:
                    k_ma20 = float(df["Close"].iloc[k-20:k].mean())
                    if float(df["Close"].iloc[k]) > k_ma20:
                        above_count += 1
            if above_count < 7:
                continue

            ref_close = cur_close
            if ref_close <= 0:
                continue

            fwd_slice = df.iloc[i + 1: i + 1 + forward_days]
            if len(fwd_slice) < forward_days:
                continue

            fwd_close = float(fwd_slice["Close"].iloc[-1])
            fwd_high  = float(fwd_slice["High"].max())
            fwd_low   = float(fwd_slice["Low"].min())

            ret      = (fwd_close / ref_close - 1) * 100
            max_gain = (fwd_high / ref_close - 1) * 100
            max_drop = (fwd_low / ref_close - 1) * 100

            events.append({
                "날짜": pd.Timestamp(date_naive).strftime("%Y-%m-%d"),
                "종목코드": ticker,
                "종목명": name,
                "RS Score": round(rs_score, 1),
                "진입신호": round(e_val, 2),
                "분배신호": round(d_val, 2),
                "종가": round(ref_close, 2),
                f"{forward_days}일수익률(%)": round(ret, 2),
                f"{forward_days}일최대상승(%)": round(max_gain, 2),
                f"{forward_days}일최대낙폭(%)": round(max_drop, 2),
            })

        return events

    except Exception as e:
        print(f"[신호BT] {ticker} 오류: {e}")
        return []


def run_signal_backtest(
    market: str = "KOSPI",
    lookback_days: int = 252,
    entry_threshold: float = 0.66,
    dist_threshold: float = 0.66,
    forward_days: int = 5,
    use_cache: bool = True,
    progress_cb=None,
) -> pd.DataFrame:
    """
    진입신호 + 분배신호 동시 적색 이벤트 백테스트.

    Parameters:
        entry_threshold: 진입신호 적색 기준 (기본 0.66)
        dist_threshold:  분배신호 적색 기준 (기본 0.66)
        forward_days:    이후 관찰 기간 (기본 5거래일)
    """
    if use_cache:
        cached = _load_signal_cache(market, lookback_days)
        if cached is not None:
            return cached

    ranking_df = calc_market_ranking(market, period=60, top_n=9999)
    if ranking_df is None or ranking_df.empty:
        return pd.DataFrame()

    ticker_col = "종목코드" if "종목코드" in ranking_df.columns else "Code"
    name_col   = "종목명" if "종목명" in ranking_df.columns else "Name"
    rs_col     = "RS Score" if "RS Score" in ranking_df.columns else "RS"

    tickers   = ranking_df[ticker_col].tolist()
    names     = ranking_df[name_col].tolist()
    rs_scores = ranking_df[rs_col].tolist()
    n_total   = len(tickers)

    print(f"[신호BT] {market} {n_total}종목 스캔 시작...")

    all_events = []
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                _detect_signal_events_single,
                tickers[i], names[i], rs_scores[i],
                lookback_days, entry_threshold, dist_threshold, forward_days,
            ): tickers[i]
            for i in range(n_total)
        }
        for future in as_completed(future_map):
            done += 1
            if progress_cb:
                progress_cb(done, n_total)
            try:
                evts = future.result(timeout=REQUEST_TIMEOUT)
                if evts:
                    all_events.extend(evts)
            except Exception:
                pass

    print(f"[신호BT] {market} 완료: {len(all_events)}건")

    if not all_events:
        return pd.DataFrame()

    result_df = pd.DataFrame(all_events)
    result_df = result_df.sort_values("날짜", ascending=False).reset_index(drop=True)

    if use_cache:
        _save_signal_cache(result_df, market, lookback_days)

    return result_df
