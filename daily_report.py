#!/usr/bin/env python3
"""
SEPA Scanner Daily Report
- 한국 시장: 매일 오전 7:30 (KST)
- 미국 시장: 매일 오후 2:00 (KST)
"""

import sys
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import FinanceDataReader as fdr

from portfolio import (
    set_portfolio_file, get_open_positions, get_realized_pnl,
    get_total_capital, _current_stop_loss,
)

# ── 로그 설정 ──
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "daily_report.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("daily_report")

CACHE_DIR = Path(__file__).parent / "cache"
REPORT_DIR = Path(__file__).parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════
# 유틸리티
# ═══════════════════════════════════════════

def _fetch_index(code: str, days: int = 10) -> pd.DataFrame:
    """지수 데이터 조회"""
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        return fdr.DataReader(code, start, end)
    except Exception as e:
        log.error(f"지수 조회 실패 ({code}): {e}")
        return pd.DataFrame()


def _fetch_current_price(ticker: str) -> float:
    """현재가 조회 (최근 종가, NaN 제외)"""
    try:
        end = datetime.now()
        start = end - timedelta(days=10)
        df = fdr.DataReader(ticker, start, end)
        df = df.dropna(subset=["Close"])
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def _load_cache(filename: str) -> dict:
    """캐시 파일 로드"""
    path = CACHE_DIR / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _cache_to_df(cache: dict) -> pd.DataFrame:
    """캐시 JSON → DataFrame"""
    if not cache or "columns" not in cache or "rows" not in cache:
        return pd.DataFrame()
    return pd.DataFrame(cache["rows"], columns=cache["columns"])


def _find_latest_cache(prefix: str, market: str, period: int = 60) -> str:
    """최신 캐시 파일명 찾기 (최근 7일까지 탐색)"""
    for i in range(8):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        filename = f"{prefix}_{market}_{period}d_{d}.json"
        if (CACHE_DIR / filename).exists():
            return filename
    return ""


def _find_prev_cache(prefix: str, market: str, period: int = 60) -> str:
    """전일 캐시 파일명 찾기 (신규 편입 비교용)"""
    today = datetime.now().strftime("%Y%m%d")
    # 최근 7일까지 탐색 (주말/공휴일 고려)
    for i in range(1, 8):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        filename = f"{prefix}_{market}_{period}d_{d}.json"
        if (CACHE_DIR / filename).exists():
            # 오늘 캐시와 같은 파일이면 스킵
            today_file = f"{prefix}_{market}_{period}d_{today}.json"
            if filename != today_file:
                return filename
    return ""


# ═══════════════════════════════════════════
# 리포트 섹션 생성 (HTML 포맷)
# ═══════════════════════════════════════════

def _chg_arrow(pct: float) -> str:
    """등락률에 화살표 + 부호"""
    if pct >= 0:
        return f"▲ +{pct:.2f}%"
    else:
        return f"▼ {pct:.2f}%"


def _display_width(s: str) -> int:
    """문자열의 모노스페이스 표시 너비 (한글=2, ASCII=1)"""
    w = 0
    for c in s:
        if ord(c) > 0x7F:
            w += 2
        else:
            w += 1
    return w


def _pad_right(s: str, width: int) -> str:
    """한글 고려하여 오른쪽 공백 패딩 (좌측 정렬)"""
    pad = width - _display_width(s)
    return s + " " * max(pad, 0)


def _pad_left(s: str, width: int) -> str:
    """한글 고려하여 왼쪽 공백 패딩 (우측 정렬)"""
    pad = width - _display_width(s)
    return " " * max(pad, 0) + s


def _section_market_index(markets: list, index_codes: dict) -> str:
    """1. 시장 지수 현황"""
    lines = ["<b>📊 시장 지수</b>"]

    for market in markets:
        code = index_codes[market]
        df = _fetch_index(code, days=15)
        if df.empty or len(df) < 2:
            lines.append(f"  {market}: 데이터 없음")
            continue

        latest = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        daily_chg = (latest - prev) / prev * 100

        if len(df) >= 6:
            week_ago = float(df["Close"].iloc[-6])
            weekly_chg = (latest - week_ago) / week_ago * 100
        else:
            weekly_chg = 0.0

        lines.append(
            f"<code>{market:8s} {latest:>10,.2f}</code>\n"
            f"  전일 {_chg_arrow(daily_chg)}  │  1주 {_chg_arrow(weekly_chg)}"
        )

    return "\n".join(lines)


def _section_portfolio(portfolio_file: str, is_kr: bool) -> str:
    """2. 포트폴리오 현황"""
    set_portfolio_file(portfolio_file)
    lines = ["\n<b>💼 포트폴리오</b>"]

    positions = get_open_positions()
    if positions.empty:
        lines.append("  보유 종목 없음")
        return "\n".join(lines)

    total_eval = 0.0
    total_cost = 0.0
    stop_alerts = []

    for _, row in positions.iterrows():
        ticker = row["종목코드"]
        avg_price = float(row["평균매수가"])
        qty = int(row["수량"])
        stop_loss = float(row["손절가"]) if row["손절가"] else 0.0

        cur_price = _fetch_current_price(ticker)
        if cur_price <= 0:
            continue

        cost = avg_price * qty
        eval_amt = cur_price * qty
        total_cost += cost
        total_eval += eval_amt

        if stop_loss > 0:
            dist_pct = (cur_price - stop_loss) / stop_loss * 100
            if dist_pct <= 1.0:
                name = row["종목명"]
                if is_kr:
                    stop_alerts.append(
                        f"  ⚠️ <b>{name}</b>  {cur_price:,.0f} / 손절 {stop_loss:,.0f}  ({dist_pct:+.2f}%)"
                    )
                else:
                    stop_alerts.append(
                        f"  ⚠️ <b>{name}</b>  ${cur_price:,.2f} / 손절 ${stop_loss:,.2f}  ({dist_pct:+.2f}%)"
                    )

    unrealized = total_eval - total_cost
    unrealized_pct = (unrealized / total_cost * 100) if total_cost > 0 else 0

    realized = get_realized_pnl()
    now = datetime.now()
    monthly_pnl = 0.0
    yearly_pnl = 0.0

    if not realized.empty and "날짜" in realized.columns:
        realized["날짜_dt"] = pd.to_datetime(realized["날짜"])
        pnl_col = "비용차감손익(원)" if "비용차감손익(원)" in realized.columns else "실현손익(원)"
        monthly = realized[
            (realized["날짜_dt"].dt.year == now.year) &
            (realized["날짜_dt"].dt.month == now.month)
        ]
        monthly_pnl = float(monthly[pnl_col].sum()) if not monthly.empty else 0.0
        yearly = realized[realized["날짜_dt"].dt.year == now.year]
        yearly_pnl = float(yearly[pnl_col].sum()) if not yearly.empty else 0.0

    if is_kr:
        lines.append("<pre>")
        lines.append(f"  평가금액    {total_eval:>14,.0f}원")
        lines.append(f"  평가손익    {unrealized:>14,.0f}원  ({unrealized_pct:+.2f}%)")
        lines.append(f"  당월 실현   {monthly_pnl:>14,.0f}원")
        lines.append(f"  연간 실현   {yearly_pnl:>14,.0f}원")
        lines.append("</pre>")
    else:
        lines.append("<pre>")
        lines.append(f"  평가금액    ${total_eval:>12,.2f}")
        lines.append(f"  평가손익    ${unrealized:>12,.2f}  ({unrealized_pct:+.2f}%)")
        lines.append(f"  당월 실현   ${monthly_pnl:>12,.2f}")
        lines.append(f"  연간 실현   ${yearly_pnl:>12,.2f}")
        lines.append("</pre>")

    if stop_alerts:
        lines.append("\n🚨 <b>손절선 근접</b>")
        lines.extend(stop_alerts)
    else:
        lines.append("✅ 손절선 근접 종목 없음")

    return "\n".join(lines)


def _section_vcp_scanner(markets: list) -> str:
    """3. RS스캐너 — VCP 필터 상위 10개 + 신규 편입"""
    lines = ["\n<b>🔍 RS스캐너 (VCP 필터)</b>"]

    for market in markets:
        lines.append(f"\n<b>[{market}] 상위 10</b>")

        today_file = _find_latest_cache("vcp", market)
        if not today_file:
            lines.append("  캐시 없음")
            continue

        today_cache = _load_cache(today_file)
        today_df = _cache_to_df(today_cache)
        if today_df.empty:
            lines.append("  데이터 없음")
            continue

        top10 = today_df.head(10)
        # 한국: 종목명 짧음, 미국: 종목명 길음
        is_us_market = market in ("NASDAQ", "NYSE")
        nm_width = 20 if is_us_market else 12
        nm_cut = 18 if is_us_market else 6
        pr_width = 8 if is_us_market else 10
        table = "<pre>"
        table += _pad_right("종목명", nm_width) + _pad_left("RS", 7) + _pad_left("현재가", pr_width) + "\n"
        table += "─" * (nm_width + 7 + pr_width) + "\n"
        for _, row in top10.iterrows():
            name = str(row.get("종목명", ""))[:nm_cut]
            rs_s = f"{row.get('RS Score', 0):.1f}"
            price = row.get("현재가", 0)
            price_s = f"{price:,.2f}" if is_us_market else f"{price:,.0f}"
            table += _pad_right(name, nm_width) + _pad_left(rs_s, 7) + _pad_left(price_s, pr_width) + "\n"
        table += "</pre>"
        lines.append(table)

        # 신규 편입
        prev_file = _find_prev_cache("vcp", market)
        if prev_file:
            prev_cache = _load_cache(prev_file)
            prev_df = _cache_to_df(prev_cache)
            if not prev_df.empty:
                today_tickers = set(today_df["종목코드"].values)
                prev_tickers = set(prev_df["종목코드"].values)
                new_tickers = today_tickers - prev_tickers
                if new_tickers:
                    new_df = today_df[today_df["종목코드"].isin(new_tickers)]
                    new_names = [f"{r['종목명']}(RS:{r['RS Score']:.0f})" for _, r in new_df.iterrows()]
                    lines.append(f"🆕 신규 {len(new_df)}개: " + ", ".join(new_names))
                else:
                    lines.append("  신규 편입 없음")

    return "\n".join(lines)


def _section_pattern_scanner(markets: list) -> str:
    """4. 패턴스캐너 — VCP 패턴 감지 종목"""
    lines = ["\n<b>📐 패턴스캐너 (VCP 패턴)</b>"]

    for market in markets:
        cache_file = _find_latest_cache("vcp_pattern", market)
        if not cache_file:
            lines.append(f"\n[{market}] 캐시 없음")
            continue

        cache = _load_cache(cache_file)
        df = _cache_to_df(cache)
        if df.empty:
            lines.append(f"\n[{market}] 감지 종목 없음")
            continue

        lines.append(f"\n<b>[{market}] {len(df)}개 감지</b>")
        is_us_market = market in ("NASDAQ", "NYSE")
        nm_width = 20 if is_us_market else 12
        nm_cut = 18 if is_us_market else 6
        pv_width = 10 if is_us_market else 9
        table = "<pre>"
        table += _pad_right("종목명", nm_width) + _pad_left("수축", 8) + _pad_left("피벗", pv_width) + _pad_left("거리", 6) + "\n"
        table += "─" * (nm_width + 8 + pv_width + 6) + "\n"
        for _, row in df.iterrows():
            name = str(row.get("종목명", ""))[:nm_cut]
            t_count = row.get("수축(T)", 0)
            strength = row.get("수축강도(%)", 0)
            contraction = f"{t_count}T/{strength:.0f}%"
            pivot = row.get("피벗", 0)
            pivot_s = f"{pivot:,.2f}" if is_us_market else f"{pivot:,.0f}"
            dist_s = f"{row.get('피벗거리(%)', 0):.1f}%"
            table += _pad_right(name, nm_width) + _pad_left(contraction, 8) + _pad_left(pivot_s, pv_width) + _pad_left(dist_s, 6) + "\n"
        table += "</pre>"
        lines.append(table)

    return "\n".join(lines)


# ═══════════════════════════════════════════
# 텔레그램 발송
# ═══════════════════════════════════════════

import os as _os
from dotenv import load_dotenv as _load_env
_load_env(Path(__file__).parent / ".env")
TELEGRAM_TOKEN = _os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = _os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(text: str):
    """텔레그램으로 리포트 발송 (4096자 제한 분할 전송)"""
    import urllib.request
    import urllib.parse

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000  # 여유 두고 4000자

    chunks = []
    if len(text) <= max_len:
        chunks = [text]
    else:
        lines = text.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > max_len:
                chunks.append(chunk)
                chunk = line
            else:
                chunk = chunk + "\n" + line if chunk else line
        if chunk:
            chunks.append(chunk)

    for chunk in chunks:
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=30)
        except Exception as e:
            log.error(f"텔레그램 발송 실패: {e}")


# ═══════════════════════════════════════════
# 리포트 생성
# ═══════════════════════════════════════════

def generate_report(region: str) -> str:
    """
    리포트 텍스트 생성
    region: 'kr' 또는 'us'
    """
    now = datetime.now()

    if region == "kr":
        title = f"🇰🇷 한국 시장 Daily Report — {now.strftime('%Y-%m-%d %H:%M')}"
        markets = ["KOSPI", "KOSDAQ"]
        index_codes = {"KOSPI": "KS11", "KOSDAQ": "KQ11"}
        portfolio_file = "portfolio.json"
        is_kr = True
    else:
        title = f"🇺🇸 미국 시장 Daily Report — {now.strftime('%Y-%m-%d %H:%M')}"
        markets = ["NASDAQ", "NYSE"]
        index_codes = {"NASDAQ": "^IXIC", "NYSE": "^GSPC"}
        portfolio_file = "portfolio_us.json"
        is_kr = False

    sections = [
        f"<b>{title}</b>",
        _section_market_index(markets, index_codes),
        _section_portfolio(portfolio_file, is_kr),
        _section_vcp_scanner(markets),
        _section_pattern_scanner(markets),
        f"\n<i>SEPA Scanner  {now.strftime('%H:%M:%S')}</i>",
    ]

    return "\n".join(sections)


def run_report(region: str):
    """리포트 생성 → 파일 저장 + 로그"""
    log.info(f"[{region.upper()}] 리포트 생성 시작")

    try:
        report = generate_report(region)
    except Exception as e:
        log.error(f"[{region.upper()}] 리포트 생성 실패: {e}")
        return

    # 파일 저장
    today = datetime.now().strftime("%Y%m%d")
    filename = f"daily_{region}_{today}.txt"
    filepath = REPORT_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    log.info(f"[{region.upper()}] 리포트 저장: {filepath}")

    # 텔레그램 발송
    try:
        send_telegram(report)
        log.info(f"[{region.upper()}] 텔레그램 발송 완료")
    except Exception as e:
        log.error(f"[{region.upper()}] 텔레그램 발송 실패: {e}")

    print(report)
    print(f"\n저장: {filepath}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SEPA Scanner Daily Report")
    parser.add_argument("target", choices=["kr", "us", "all"], default="all", nargs="?",
                        help="리포트 대상: kr(한국), us(미국), all(전체)")
    args = parser.parse_args()

    if args.target in ("kr", "all"):
        run_report("kr")
    if args.target in ("us", "all"):
        run_report("us")
