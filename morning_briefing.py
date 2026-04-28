#!/usr/bin/env python3
"""
매일 아침 매매 브리핑 — 텔레그램 자동 발송
보유종목 상태 테이블 + 손절 근접 경고 + OTI
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(text: str):
    """텔레그램 메시지 전송 (MarkdownV2)"""
    import urllib.request
    import json
    url = "https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_TOKEN
    data = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("텔레그램 전송 실패: %s" % e)


def fetch_price(ticker):
    """현재가 조회"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker if not ticker.isdigit() else "%s.KS" % ticker)
        h = t.history(period="2d")
        if h is not None and not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return 0


def calc_signals(ticker):
    """진입/분배 신호 계산"""
    try:
        from relative_strength import (
            detect_market, get_benchmark, fetch_data, align_data,
            calculate_mas, trim_to_period, calculate_ibd_rs,
            calc_entry_signal, calc_sell_signal,
        )
        mkt = detect_market(ticker)
        bench_code, _ = get_benchmark(ticker, mkt)
        stock_df, index_df = fetch_data(ticker, bench_code, 60)
        stock_df, index_df = align_data(stock_df, index_df)

        entry = calc_entry_signal(stock_df)
        sell = calc_sell_signal(stock_df)

        mas = calculate_mas(stock_df['Close'])
        s_trim, i_trim, _ = trim_to_period(stock_df, index_df, mas, 60)
        _, rs_score, _, _ = calculate_ibd_rs(s_trim, i_trim)

        return {
            "entry": round(float(entry.iloc[-1]), 2),
            "sell": round(float(sell.iloc[-1]), 2),
            "rs": round(float(rs_score), 1),
        }
    except Exception:
        return {"entry": None, "sell": None, "rs": None}


def signal_label(val):
    if val is None:
        return "?"
    if val <= 0.33:
        return "녹"
    if val <= 0.66:
        return "황"
    return "적"


def status_emoji(sell_val, ret_pct):
    """분배신호 + 수익률 기반 상태 판정"""
    if sell_val is not None and sell_val > 0.66:
        return "🟠"
    if sell_val is not None and sell_val > 0.33:
        return "🟡"
    return "🟢"


def build_briefing():
    from portfolio import set_portfolio_file, get_open_positions, calc_oti
    from concurrent.futures import ThreadPoolExecutor

    lines = []
    lines.append("📋 <b>아침 매매 브리핑</b> %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append("")

    for market, pf in [("KR", "portfolio.json"), ("US", "portfolio_us.json")]:
        set_portfolio_file(pf)
        df = get_open_positions()
        oti = calc_oti(days=3)

        flag = "🇰🇷" if market == "KR" else "🇺🇸"
        lines.append("%s <b>%s</b> | OTI: %d %s" % (flag, market, oti["oti"], oti["level"]))

        if df.empty:
            lines.append("  보유종목 없음")
            lines.append("")
            continue

        # 현재가 + 신호 병렬 조회
        tickers = df["종목코드"].tolist()
        with ThreadPoolExecutor(max_workers=6) as pool:
            prices = dict(zip(tickers, pool.map(fetch_price, tickers)))
            signals = dict(zip(tickers, pool.map(calc_signals, tickers)))

        rows = []
        for _, r in df.iterrows():
            tk = r["종목코드"]
            nm = r["종목명"]
            avg = float(r["평균매수가"])
            sl = float(r["손절가"])
            cur = prices.get(tk, 0)

            ret = round((cur / avg - 1) * 100, 1) if cur > 0 and avg > 0 else 0
            sl_dist = round((cur - sl) / cur * 100, 1) if cur > 0 and sl > 0 else 0

            sig = signals.get(tk, {})
            entry_val = sig.get("entry")
            sell_val = sig.get("sell")
            rs = sig.get("rs")

            status = status_emoji(sell_val, ret)

            if market == "KR":
                price_str = "{:,.0f}".format(cur) if cur > 0 else "-"
                sl_str = "{:,.0f}".format(sl)
            else:
                price_str = "${:.2f}".format(cur) if cur > 0 else "-"
                sl_str = "${:.2f}".format(sl)

            # 행동 자동 판정
            if sell_val is not None and sell_val > 0.66:
                action = "경계"
            elif sl_dist < 3:
                action = "손절주의⚠️"
            elif r["경과일"] <= 5:
                action = "관찰"
            else:
                action = "홀딩"

            rows.append({
                "status": status,
                "name": nm[:6],
                "ret": ret,
                "action": action,
                "sl_dist": sl_dist,
                "entry": entry_val,
                "sell": sell_val,
                "rs": rs,
                "price": price_str,
                "sl": sl_str,
            })

        # 손절거리 오름차순 정렬 (위험한 것 위로)
        rows.sort(key=lambda x: x["sl_dist"])

        for row in rows:
            line = "%s %s %+.1f%% | %s | 손절 %s(%.1f%%) | 진%s 분%s | RS%+.1f" % (
                row["status"],
                row["name"],
                row["ret"],
                row["action"],
                row["sl"],
                row["sl_dist"],
                signal_label(row["entry"]),
                signal_label(row["sell"]),
                row["rs"] if row["rs"] is not None else 0,
            )
            lines.append(line)

        lines.append("")

    # 손절 근접 경고 (3% 이내)
    alert_lines = []
    for market, pf in [("KR", "portfolio.json"), ("US", "portfolio_us.json")]:
        set_portfolio_file(pf)
        df = get_open_positions()
        if df.empty:
            continue
        for _, r in df.iterrows():
            tk = r["종목코드"]
            cur = prices.get(tk, 0) if tk in prices else fetch_price(tk)
            sl = float(r["손절가"])
            if cur > 0 and sl > 0:
                dist = (cur - sl) / cur * 100
                if dist < 3:
                    alert_lines.append("⚠️ <b>%s</b> 손절 %.1f%% 근접!" % (r["종목명"], dist))

    if alert_lines:
        lines.append("━━━ 손절 근접 경고 ━━━")
        lines.extend(alert_lines)
        lines.append("")

    lines.append("💡 과매매 주의 | 기존 포지션 안정화 우선")

    return "\n".join(lines)


if __name__ == "__main__":
    msg = build_briefing()
    print(msg)
    print("\n--- 전송 중 ---")
    send_telegram(msg)
    print("완료!")
