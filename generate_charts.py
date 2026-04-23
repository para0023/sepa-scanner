#!/usr/bin/env python3
"""
SEPA Scanner 보유종목 차트 이미지 자동 생성
- 보유종목 전체 차트를 reports/charts/에 PNG로 저장
- 코워크(Co-work)에서 종목 분석 시 참조용
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from pathlib import Path
from portfolio import set_portfolio_file, get_open_positions
from relative_strength import build_trade_chart_image

CHART_DIR = Path(__file__).parent / "reports" / "charts"


def generate_all_charts(period: int = 180):
    """보유종목 전체 차트 이미지 생성"""
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    total = 0
    for market, file in [("KR", "portfolio.json"), ("US", "portfolio_us.json")]:
        set_portfolio_file(file)
        pos = get_open_positions()
        if pos.empty:
            continue

        print(f"\n[{market}] {len(pos)}종목 차트 생성 중...")
        for _, row in pos.iterrows():
            ticker = row["종목코드"]
            name = row["종목명"]
            filename = f"{ticker}_{today}.png"
            filepath = CHART_DIR / filename

            try:
                print(f"  {name} ({ticker})...", end=" ")
                img = build_trade_chart_image(ticker, today, period=period)
                if img:
                    filepath.write_bytes(img)
                    print(f"OK ({len(img):,} bytes)")
                    total += 1
                else:
                    print("SKIP (빈 데이터)")
            except Exception as e:
                print(f"FAIL ({e})")

    set_portfolio_file("portfolio.json")
    print(f"\n완료: {total}종목 차트 저장 → {CHART_DIR}")
    print(f"코워크에서 참조 경로: {CHART_DIR}/{{티커}}_{today}.png")


def generate_single_chart(ticker: str, period: int = 180):
    """단일 종목 차트 이미지 생성"""
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{ticker}_{today}.png"
    filepath = CHART_DIR / filename

    print(f"{ticker} 차트 생성 중...")
    img = build_trade_chart_image(ticker, today, period=period)
    if img:
        filepath.write_bytes(img)
        print(f"저장: {filepath} ({len(img):,} bytes)")
    else:
        print("생성 실패")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="보유종목 차트 이미지 생성")
    parser.add_argument("--ticker", "-t", help="특정 종목만 생성 (미지정 시 전체)")
    parser.add_argument("--period", "-p", type=int, default=180, help="차트 기간 (기본 180일)")
    args = parser.parse_args()

    if args.ticker:
        generate_single_chart(args.ticker, args.period)
    else:
        generate_all_charts(args.period)
