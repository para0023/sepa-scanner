#!/usr/bin/env python3
"""
SEPA Scanner 포트폴리오 알림
- 정기 알림: 장중 매시간 보유종목 현재가/수익률 요약
- 급변 알림: 3% 이상 변동 시 즉시 발송
- 한국장: 09:00~15:30 (KST)
- 미국장: 23:30~06:00 (KST) — 서머타임 기준 조정 필요
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
from concurrent.futures import ThreadPoolExecutor

from portfolio import set_portfolio_file, get_open_positions

# ── 로그 설정 ──
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "portfolio_alert.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── 텔레그램 설정 ──
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── 상태 파일 (급변 알림 중복 방지) ──
STATE_FILE = Path(__file__).parent / "cache" / "alert_state.json"


def send_telegram(text: str):
    """텔레그램 발송"""
    import urllib.request
    import urllib.parse

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("텔레그램 토큰/채팅ID 미설정")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000
    chunks = [text] if len(text) <= max_len else []
    if not chunks:
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
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            log.error(f"텔레그램 발송 실패: {e}")


def _fetch_price_with_prev(ticker: str) -> tuple:
    """현재가 + 전일 종가 조회 → (현재가, 전일종가)"""
    try:
        end = datetime.now()
        start = end - timedelta(days=10)
        df = fdr.DataReader(ticker, start, end)
        if df is not None and len(df) >= 2:
            return float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
        elif df is not None and len(df) == 1:
            return float(df["Close"].iloc[-1]), 0.0
    except:
        pass
    return 0.0, 0.0


def _load_state() -> dict:
    """이전 알림 상태 로드"""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}


def _save_state(state: dict):
    """알림 상태 저장"""
    try:
        STATE_FILE.parent.mkdir(exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except:
        pass


def _get_holdings(market: str) -> pd.DataFrame:
    """보유종목 조회"""
    if market == "US":
        set_portfolio_file("portfolio_us.json")
    else:
        set_portfolio_file("portfolio.json")
    df = get_open_positions()
    set_portfolio_file("portfolio.json")  # 원복
    return df


def run_alert():
    """메인 알림 로직"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # 장 시간 체크
    kr_market_open = 9 <= hour < 16  # 09:00~15:30 (여유 있게 16시까지)
    us_market_open = hour >= 23 or hour < 7  # 23:30~06:00 (KST)

    is_regular_kr = (hour == 10 or hour == 14) and minute < 10  # 한국장: 오전 10시, 오후 2시
    is_regular_us = (hour == 0 or hour == 5) and minute < 10   # 미국장: 자정 12시, 새벽 5시

    all_alerts = []
    state = _load_state()

    for market, is_open, label, currency in [
        ("KR", kr_market_open, "🇰🇷 한국", "원"),
        ("US", us_market_open, "🇺🇸 미국", "$"),
    ]:
        if not is_open:
            continue

        df = _get_holdings(market)
        if df.empty:
            continue

        # 현재가 + 전일종가 일괄 조회
        tickers = df["종목코드"].tolist()
        with ThreadPoolExecutor(max_workers=8) as pool:
            price_data = dict(zip(tickers, pool.map(_fetch_price_with_prev, tickers)))

        # 종목별 수익률 계산
        rows = []
        for _, row in df.iterrows():
            ticker = row["종목코드"]
            name = row["종목명"]
            avg_buy = row["평균매수가"]
            stop_loss = row.get("손절가", 0)
            cur, prev_close = price_data.get(ticker, (0, 0))

            if cur <= 0 or avg_buy <= 0:
                continue

            pnl_pct = (cur / avg_buy - 1) * 100
            daily_chg = ((cur / prev_close - 1) * 100) if prev_close > 0 else 0

            rows.append({
                "ticker": ticker,
                "name": name,
                "cur": cur,
                "prev_close": prev_close,
                "avg_buy": avg_buy,
                "stop_loss": stop_loss,
                "pnl_pct": round(pnl_pct, 2),
                "daily_chg": round(daily_chg, 2),
            })

        if not rows:
            continue

        # ── 급변 알림 (전일 대비 3% 이상 변동) ──
        _alerted_today = state.get(f"_alerted_{market}_{now.strftime('%Y%m%d')}", [])
        for r in rows:
            if abs(r["daily_chg"]) >= 3 and r["ticker"] not in _alerted_today:
                direction = "📈 급등" if r["daily_chg"] > 0 else "📉 급락"
                if currency == "$":
                    price_str = f"${r['cur']:,.2f}"
                else:
                    price_str = f"{int(r['cur']):,}원"
                alert_msg = (
                    f"{direction} {label} <b>{r['name']}</b>\n"
                    f"현재가: {price_str} (전일대비: {r['daily_chg']:+.2f}%)\n"
                    f"매수가대비: {r['pnl_pct']:+.2f}%"
                )
                all_alerts.append(alert_msg)
                _alerted_today.append(r["ticker"])
        state[f"_alerted_{market}_{now.strftime('%Y%m%d')}"] = _alerted_today

        # ── 정기 알림 (한국 10시/14시, 미국 0시/5시) ──
        _is_regular = is_regular_kr if market == "KR" else is_regular_us
        if _is_regular:
            lines = [f"⏰ {label} 보유현황 ({now.strftime('%H:%M')})"]
            lines.append("─" * 25)
            total_buy = 0
            total_eval = 0
            for r in sorted(rows, key=lambda x: x["pnl_pct"], reverse=True):
                emoji = "🔴" if r["pnl_pct"] >= 0 else "🔵"
                if currency == "$":
                    price_str = f"${r['cur']:,.2f}"
                else:
                    price_str = f"{int(r['cur']):,}"
                daily_str = f" 전일{r['daily_chg']:+.1f}%" if r["daily_chg"] != 0 else ""
                lines.append(f"{emoji} {r['name']}: {price_str} ({r['pnl_pct']:+.2f}%){daily_str}")
            lines.append("─" * 25)
            lines.append(f"종목 수: {len(rows)}")
            all_alerts.append("\n".join(lines))

    # 발송
    if all_alerts:
        for msg in all_alerts:
            send_telegram(msg)
            log.info(f"알림 발송: {msg[:50]}...")
    else:
        log.info("발송할 알림 없음")

    # 상태 저장
    _save_state(state)


if __name__ == "__main__":
    log.info("포트폴리오 알림 시작")
    run_alert()
    log.info("포트폴리오 알림 완료")
