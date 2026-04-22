#!/usr/bin/env python3
"""
SEPA Scanner 리포트 데이터 추출기
- 주간/월간 리포트용 데이터를 추출하여 분석 가능한 형태로 출력
- Claude Code에서 "주간 리포트 만들어줘" 시 이 스크립트를 실행하면 됨
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from datetime import datetime, timedelta
from portfolio import (
    set_portfolio_file, get_realized_pnl, get_position_pnl,
    get_open_positions, get_total_capital, get_available_weeks, get_weekly_review,
)


def _calc_kpi(df, label=""):
    """거래/종목 DataFrame에서 KPI 계산"""
    if df.empty:
        return {"label": label, "count": 0}
    n = len(df)
    wins = df[df["수익률(%)"] > 0]
    losses = df[df["수익률(%)"] <= 0]
    pnl_cols = [c for c in df.columns if "비용차감손익" in c]
    total_pnl = df[pnl_cols[0]].sum() if pnl_cols else 0
    hold = df["보유일수"].dropna() if "보유일수" in df.columns else pd.Series()
    rr = df["RR"].dropna() if "RR" in df.columns else pd.Series()

    return {
        "label": label,
        "count": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_win": round(wins["수익률(%)"].mean(), 2) if len(wins) > 0 else 0,
        "avg_loss": round(losses["수익률(%)"].mean(), 2) if len(losses) > 0 else 0,
        "avg_all": round(df["수익률(%)"].mean(), 2),
        "avg_rr": round(rr.mean(), 2) if len(rr) > 0 else 0,
        "avg_hold": round(hold.mean(), 1) if len(hold) > 0 else 0,
        "total_pnl": round(total_pnl),
    }


def _by_reason(df):
    """진입근거별 KPI"""
    if df.empty or "진입근거" not in df.columns:
        return {}
    result = {}
    for reason, grp in df.groupby("진입근거"):
        result[reason] = _calc_kpi(grp, reason)
    return result


def _by_hold_period(df):
    """보유기간별 KPI"""
    if df.empty or "보유일수" not in df.columns:
        return {}
    bins = {"0일(당일)": df[df["보유일수"] == 0],
            "1~3일": df[(df["보유일수"] >= 1) & (df["보유일수"] <= 3)],
            "4~10일": df[(df["보유일수"] >= 4) & (df["보유일수"] <= 10)],
            "10일+": df[df["보유일수"] > 10]}
    return {k: _calc_kpi(v, k) for k, v in bins.items() if not v.empty}


def extract_weekly_report(week_start=None):
    """주간 리포트 데이터 추출"""
    print("=" * 70)
    print("📊 SEPA Scanner 주간 리포트 데이터")
    print("=" * 70)

    for market, file, currency in [("한국", "portfolio.json", "원"), ("미국", "portfolio_us.json", "$")]:
        set_portfolio_file(file)

        weeks = get_available_weeks()
        if not weeks:
            continue

        if week_start is None:
            week_start_use = weeks[0]
        else:
            week_start_use = week_start

        wr = get_weekly_review(week_start_use)
        if not wr:
            continue

        ws = wr["week_start"]
        we = wr["week_end"]

        print(f"\n{'─'*60}")
        print(f"■ {market} ({ws} ~ {we})")
        print(f"{'─'*60}")

        # 1. 포트폴리오 현황
        print(f"\n[1. 포트폴리오 현황]")
        print(f"  주초평가: {wr['week_start_val']:,.0f}{currency}" if currency == "원" else f"  주초평가: ${wr['week_start_val']:,.2f}")
        print(f"  주말평가: {wr['week_end_val']:,.0f}{currency}" if currency == "원" else f"  주말평가: ${wr['week_end_val']:,.2f}")
        print(f"  주간수익률: {wr['weekly_return_pct']:+.2f}%")

        # 2. 거래현황 요약
        s = wr.get("summary")
        if s:
            print(f"\n[2. 거래현황 요약 (거래별)]")
            print(f"  {s['총거래수']}건, {s['승']}승 {s['패']}패, 승률 {s['승률(%)']:.1f}%")
            print(f"  승리평균: {s['승리평균수익률(%)']:+.2f}%, 패배평균: {s['패배평균손실률(%)']:+.2f}%")
            print(f"  주간실현: {s['주간실현수익']:+,.0f}{currency}" if currency == "원" else f"  주간실현: ${s['주간실현수익']:+,.2f}")

        # 3. 종목별 성과 (청산 건)
        df_pos = get_position_pnl()
        if df_pos is not None and not df_pos.empty:
            df_pos["_date"] = pd.to_datetime(df_pos["청산일"])
            week_pos = df_pos[(df_pos["_date"] >= ws) & (df_pos["_date"] <= we)]
            if not week_pos.empty:
                kpi = _calc_kpi(week_pos, "종목별")
                print(f"\n[2b. 종목별 기준]")
                print(f"  {kpi['count']}종목, {kpi['wins']}승 {kpi['losses']}패, 승률 {kpi['win_rate']:.1f}%")
                print(f"  승리평균: {kpi['avg_win']:+.2f}%, 패배평균: {kpi['avg_loss']:+.2f}%")

        # 4. 진입/청산 상세
        print(f"\n[3. 진입 ({len(wr['entries'])}건)]")
        for e in wr["entries"]:
            for b in e["매수"]:
                price = f"{b['가격']:,.0f}원" if currency == "원" else f"${b['가격']:,.2f}"
                print(f"  {e['종목명']} ({e['종목코드']}) {b['날짜']} {price} x{b['수량']} 근거:{b.get('진입근거','')}")

        print(f"\n[4. 청산 ({len(wr['exits'])}건)]")
        for e in wr["exits"]:
            for s_t in e["매도"]:
                price = f"{s_t['가격']:,.0f}원" if currency == "원" else f"${s_t['가격']:,.2f}"
                print(f"  {e['종목명']} ({e['종목코드']}) {s_t['날짜']} {price} x{s_t['수량']} 사유:{s_t.get('사유','')}")

        print(f"\n[5. 진입+청산 ({len(wr['both'])}건)]")
        for e in wr["both"]:
            print(f"  {e['종목명']} ({e['종목코드']})")
            for b in e["매수"]:
                price = f"{b['가격']:,.0f}원" if currency == "원" else f"${b['가격']:,.2f}"
                print(f"    매수 {b['날짜']} {price} x{b['수량']} 근거:{b.get('진입근거','')}")
            for s_t in e["매도"]:
                price = f"{s_t['가격']:,.0f}원" if currency == "원" else f"${s_t['가격']:,.2f}"
                print(f"    매도 {s_t['날짜']} {price} x{s_t['수량']} 사유:{s_t.get('사유','')}")

        # 6. 현재 보유현황
        pos = get_open_positions()
        if not pos.empty:
            print(f"\n[6. 현재 보유 ({len(pos)}종목)]")
            for _, r in pos.iterrows():
                price = f"{r['평균매수가']:,.0f}" if currency == "원" else f"${r['평균매수가']:,.2f}"
                stop = f"{r.get('손절가',0):,.0f}" if currency == "원" else f"${r.get('손절가',0):,.2f}"
                print(f"  {r['종목명']} ({r['종목코드']}) 매수:{price} 손절:{stop} 경과:{r.get('경과일',0):.0f}일")

    set_portfolio_file("portfolio.json")


def extract_monthly_report(year_month=None):
    """월간 리포트 데이터 추출"""
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    year, month = year_month.split("-")
    start = f"{year_month}-01"
    # 월말 계산
    if int(month) == 12:
        end = f"{int(year)+1}-01-01"
    else:
        end = f"{year}-{int(month)+1:02d}-01"
    end_dt = pd.to_datetime(end) - timedelta(days=1)
    end = end_dt.strftime("%Y-%m-%d")

    # 전월
    prev_dt = pd.to_datetime(start) - timedelta(days=1)
    prev_month = prev_dt.strftime("%Y-%m")
    prev_start = f"{prev_month}-01"
    prev_end = prev_dt.strftime("%Y-%m-%d")

    print("=" * 70)
    print(f"📊 SEPA Scanner 월간 리포트 데이터 ({year_month})")
    print("=" * 70)

    for market, file, currency in [("한국", "portfolio.json", "원"), ("미국", "portfolio_us.json", "$")]:
        set_portfolio_file(file)
        capital = get_total_capital()

        print(f"\n{'='*60}")
        print(f"■ {market} (원금: {capital:,.0f}{currency})" if currency == "원" else f"■ {market} (원금: ${capital:,.2f})")
        print(f"{'='*60}")

        # ── 거래별 ──
        df_trade = get_realized_pnl()
        if not df_trade.empty:
            df_trade["_date"] = pd.to_datetime(df_trade["날짜"])
            cur_trade = df_trade[(df_trade["_date"] >= start) & (df_trade["_date"] <= end)]
            prev_trade = df_trade[(df_trade["_date"] >= prev_start) & (df_trade["_date"] <= prev_end)]

            print(f"\n[거래별 성과]")
            for label, data in [(prev_month, prev_trade), (year_month, cur_trade)]:
                kpi = _calc_kpi(data, label)
                if kpi["count"] == 0:
                    print(f"  {label}: 거래 없음")
                    continue
                # 당일매매
                d0 = len(data[data["보유일수"] == 0]) if "보유일수" in data.columns else 0
                print(f"  {label}: {kpi['count']}건, {kpi['wins']}승{kpi['losses']}패, 승률{kpi['win_rate']}%, "
                      f"승리{kpi['avg_win']:+.2f}%, 패배{kpi['avg_loss']:+.2f}%, RR{kpi['avg_rr']:.2f}, "
                      f"당일{d0}건({d0/kpi['count']*100:.0f}%), 실현{kpi['total_pnl']:+,}{currency}")

            # 당월 진입근거별
            if not cur_trade.empty:
                print(f"\n  [진입근거별 — 거래별]")
                for reason, kpi in _by_reason(cur_trade).items():
                    print(f"    {reason}: {kpi['count']}건, {kpi['wins']}승{kpi['losses']}패, 승률{kpi['win_rate']}%, 평균{kpi['avg_all']:+.2f}%")

                print(f"\n  [보유기간별]")
                for period, kpi in _by_hold_period(cur_trade).items():
                    print(f"    {period}: {kpi['count']}건, 승률{kpi['win_rate']}%, 평균{kpi['avg_all']:+.2f}%")

                # 주간별 추이
                print(f"\n  [주간별 추이]")
                cur_trade_c = cur_trade.copy()
                cur_trade_c["_week"] = cur_trade_c["_date"].dt.isocalendar().week
                for week, wdf in cur_trade_c.groupby("_week"):
                    wkpi = _calc_kpi(wdf)
                    d0 = len(wdf[wdf["보유일수"] == 0]) if "보유일수" in wdf.columns else 0
                    print(f"    W{week}: {wkpi['count']}건, 승률{wkpi['win_rate']}%, 평균{wkpi['avg_all']:+.2f}%, 당일{d0}건, 실현{wkpi['total_pnl']:+,}{currency}")

        # ── 종목별 ──
        df_pos = get_position_pnl()
        if df_pos is not None and not df_pos.empty:
            df_pos["_date"] = pd.to_datetime(df_pos["청산일"])
            cur_pos = df_pos[(df_pos["_date"] >= start) & (df_pos["_date"] <= end)]
            prev_pos = df_pos[(df_pos["_date"] >= prev_start) & (df_pos["_date"] <= prev_end)]

            print(f"\n[종목별 성과]")
            for label, data in [(prev_month, prev_pos), (year_month, cur_pos)]:
                kpi = _calc_kpi(data, label)
                if kpi["count"] == 0:
                    print(f"  {label}: 청산종목 없음")
                    continue
                print(f"  {label}: {kpi['count']}종목, {kpi['wins']}승{kpi['losses']}패, 승률{kpi['win_rate']}%, "
                      f"승리{kpi['avg_win']:+.2f}%, 패배{kpi['avg_loss']:+.2f}%, RR{kpi['avg_rr']:.2f}, "
                      f"실현{kpi['total_pnl']:+,}{currency}")

            if not cur_pos.empty:
                print(f"\n  [진입근거별 — 종목별]")
                for reason, kpi in _by_reason(cur_pos).items():
                    print(f"    {reason}: {kpi['count']}종목, {kpi['wins']}승{kpi['losses']}패, 승률{kpi['win_rate']}%, 평균{kpi['avg_all']:+.2f}%, 실현{kpi['total_pnl']:+,}{currency}")

                print(f"\n  [개별 종목 (수익률순)]")
                pnl_col = [c for c in cur_pos.columns if "비용차감손익" in c][0]
                for _, r in cur_pos.sort_values("수익률(%)", ascending=False).iterrows():
                    print(f"    {r['종목명']:15s} {r.get('진입근거',''):6s} {r['수익률(%)']:+6.2f}% {r['보유일수']:.0f}일 {r[pnl_col]:+,.0f}{currency}")

        # ── 현재 보유 ──
        pos = get_open_positions()
        if not pos.empty:
            print(f"\n[현재 보유 ({len(pos)}종목)]")
            for _, r in pos.iterrows():
                price = f"{r['평균매수가']:,.0f}" if currency == "원" else f"${r['평균매수가']:,.2f}"
                stop = f"{r.get('손절가',0):,.0f}" if currency == "원" else f"${r.get('손절가',0):,.2f}"
                print(f"  {r['종목명']:15s} ({r['종목코드']}) 매수:{price} 손절:{stop} 경과:{r.get('경과일',0):.0f}일")

    set_portfolio_file("portfolio.json")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SEPA Scanner 리포트 데이터 추출")
    parser.add_argument("type", choices=["weekly", "monthly"], help="리포트 유형")
    parser.add_argument("--period", "-p", help="기간 (weekly: 2026-04-20, monthly: 2026-04)")
    args = parser.parse_args()

    if args.type == "weekly":
        extract_weekly_report(args.period)
    else:
        extract_monthly_report(args.period)
