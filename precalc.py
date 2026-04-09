#!/usr/bin/env python3
"""
SEPA Scanner 사전 계산 에이전트
- 날짜가 바뀌면 RS 랭킹, VCP, Stage2 필터를 미리 계산해서 캐시에 저장
- launchd로 스케줄링하여 자동 실행

한국 시장: 장 마감 후 16:30 실행
미국 시장: 한국 시간 07:00 실행 (미국 장 마감 후)
"""

import sys
import os
import logging
import signal
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeout

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import warnings
warnings.filterwarnings("ignore")

# ── 로그 설정 ──
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "precalc.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("precalc")

# 단계별 타임아웃 (초)
TIMEOUT_RANKING = 600    # RS 랭킹: 10분
TIMEOUT_FILTER = 1200    # VCP/Stage2 필터: 20분
TIMEOUT_PATTERN = 1200   # VCP 패턴 스캔: 20분


def _run_with_timeout(func, args=(), timeout=600, desc="작업"):
    """함수를 별도 프로세스에서 타임아웃 제한으로 실행"""
    with ProcessPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            log.error(f"[타임아웃] {desc} — {timeout}초 초과")
            return None
        except Exception as e:
            log.error(f"[에러] {desc} — {e}")
            return None


def _calc_ranking(market, period=60, top_n=9999):
    from market_ranking import calc_market_ranking
    return calc_market_ranking(market=market, period=period, top_n=top_n, today_only=True)


def _calc_vcp(df, market, period=60, range_pct=10.0):
    from market_ranking import apply_vcp_filter
    return apply_vcp_filter(df, market=market, period=period, range_pct=range_pct, use_cache=False)


def _calc_stage2(df, market, period=60):
    from market_ranking import apply_stage2_filter
    return apply_stage2_filter(df, market=market, period=period, use_cache=False)


def _calc_vcp_pattern(market, period=60):
    from market_ranking import scan_vcp_patterns
    return scan_vcp_patterns(market=market, period=period, use_cache=False)


def _run_market(market):
    """단일 시장 사전 계산 (RS 랭킹 → VCP → Stage2 → VCP패턴)"""
    market_start = datetime.now()

    # 1) RS 랭킹
    log.info(f"[{market}] RS 랭킹 계산 시작")
    df = _run_with_timeout(_calc_ranking, args=(market,),
                           timeout=TIMEOUT_RANKING, desc=f"{market} RS 랭킹")
    if df is None or df.empty:
        log.warning(f"[{market}] RS 랭킹 데이터 없음 — 이후 단계 스킵")
        return

    log.info(f"[{market}] RS 랭킹 완료: {len(df)}종목")

    # VCP/Stage2 필터는 RS 상위 100종목만 대상
    df_top100 = df.head(100)

    # 2) VCP 필터
    log.info(f"[{market}] VCP 필터 시작 (상위 100종목)")
    vcp = _run_with_timeout(_calc_vcp, args=(df_top100, market),
                            timeout=TIMEOUT_FILTER, desc=f"{market} VCP 필터")
    log.info(f"[{market}] VCP 필터 완료: {len(vcp) if vcp is not None else '실패'}")

    # 3) Stage2 필터
    log.info(f"[{market}] Stage2 필터 시작")
    s2 = _run_with_timeout(_calc_stage2, args=(df_top100, market),
                           timeout=TIMEOUT_FILTER, desc=f"{market} Stage2 필터")
    log.info(f"[{market}] Stage2 필터 완료: {len(s2) if s2 is not None else '실패'}")

    # 4) VCP 패턴 스캔
    log.info(f"[{market}] VCP 패턴 스캔 시작")
    vcp_pat = _run_with_timeout(_calc_vcp_pattern, args=(market,),
                                timeout=TIMEOUT_PATTERN, desc=f"{market} VCP 패턴")
    log.info(f"[{market}] VCP 패턴 스캔 완료: {len(vcp_pat) if vcp_pat is not None else '실패'}")

    elapsed = (datetime.now() - market_start).total_seconds()
    log.info(f"[{market}] 전체 완료: {elapsed:.0f}초")


def run_kr():
    """한국 시장 사전 계산 (KOSPI + KOSDAQ)"""
    for market in ["KOSPI", "KOSDAQ"]:
        try:
            _run_market(market)
        except Exception as e:
            log.error(f"[{market}] 예기치 못한 오류: {e}")


def run_us():
    """미국 시장 사전 계산 (NASDAQ + NYSE)"""
    for market in ["NASDAQ", "NYSE"]:
        try:
            _run_market(market)
        except Exception as e:
            log.error(f"[{market}] 예기치 못한 오류: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SEPA Scanner 사전 계산")
    parser.add_argument("target", choices=["kr", "us", "all"], default="all", nargs="?",
                        help="계산 대상: kr(한국), us(미국), all(전체)")
    args = parser.parse_args()

    log.info(f"========== 사전 계산 시작: {args.target} ==========")
    start = datetime.now()

    if args.target in ("kr", "all"):
        run_kr()
    if args.target in ("us", "all"):
        run_us()

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"========== 사전 계산 완료: {elapsed:.0f}초 ==========")
    print(f"사전 계산 완료 ({elapsed:.0f}초). 로그: {LOG_DIR}/precalc.log")
