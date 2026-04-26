"""Position Review generator — 기보유 종목 심층 리뷰.

Usage:
    python3 position_review.py 457190                # 한국 주식
    python3 position_review.py CAVA                  # 미국 주식
    python3 position_review.py --all-open            # 모든 열린 포지션 일괄

Output:
    reports/analysis/<YYYY-MM-DD>_<TICKER>_review.md

실행 조건: fdr(FinanceDataReader) 설치된 로컬 Python 환경에서 실행.
(venv39 또는 시스템 Python 중 fdr 설치된 쪽)
"""
from __future__ import annotations
import argparse, json, os, sys, datetime as dt
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "reports", "analysis")
FX = 1450


def load_portfolios():
    kr = json.load(open(os.path.join(ROOT, "portfolio.json")))
    us = json.load(open(os.path.join(ROOT, "portfolio_us.json")))
    return kr, us


def find_position(ticker: str):
    kr, us = load_portfolios()
    ticker_norm = ticker.strip().upper()
    for market, pf in [("KR", kr), ("US", us)]:
        for p in pf["positions"]:
            if str(p["ticker"]).upper() == ticker_norm:
                return market, p
    return None, None


OHLCV_CACHE_DIR = os.path.join(ROOT, "cache", "ohlcv")


def _cache_path(ticker: str) -> str:
    safe = str(ticker).replace("/", "_").replace("\\", "_")
    return os.path.join(OHLCV_CACHE_DIR, f"{safe}.parquet")


def fetch_ohlcv(ticker: str, market: str, days: int = 400, max_age_hours: int = 20):
    """OHLCV 가져오기.

    1) 공통 디스크 캐시(`cache/ohlcv/<TICKER>.parquet`) 우선 사용.
       앱이 차트 열면서 저장해둔 캐시가 있으면 네트워크 건너뜀.
    2) 캐시 없거나 오래됐으면 fdr로 fetch 후 캐시 저장.
       (Cowork 샌드박스 환경에서는 fetch가 네트워크 차단으로 실패할 수 있음 — None 반환)
    """
    import pandas as pd
    path = _cache_path(ticker)
    # 1단계: 캐시 사용
    if os.path.exists(path):
        age_sec = dt.datetime.now().timestamp() - os.path.getmtime(path)
        if age_sec <= max_age_hours * 3600:
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    return df
            except Exception:
                pass  # 손상 캐시 무시, fetch로 폴백
    # 2단계: fdr fetch
    try:
        import FinanceDataReader as fdr
        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        df = fdr.DataReader(ticker, start, end)
        df = df[~df.index.duplicated(keep='last')]
        df = df.dropna(subset=["Close"])
        if not df.empty:
            os.makedirs(OHLCV_CACHE_DIR, exist_ok=True)
            try:
                df.to_parquet(path)
            except Exception:
                pass
        return df
    except Exception as e:
        print(f"[!] {ticker} fetch 실패 (네트워크 차단 등): {e}", file=sys.stderr)
        # 오래된 캐시라도 있으면 반환 (없는 것보단 나음)
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    print(f"[i] {ticker} — 오래된 캐시 사용 ({int((dt.datetime.now().timestamp() - os.path.getmtime(path))/3600)}시간 전)", file=sys.stderr)
                    return df
            except Exception:
                pass
        return None


def compute_position_stats(p: dict, current_price: float, fx: float = 1.0):
    """포지션 상태 계산 (평균단가, 미실현 P&L, 총 투입, 수량)."""
    buys = [t for t in p["trades"] if t["type"] == "buy"]
    sells = [t for t in p["trades"] if t["type"] == "sell"]
    buy_qty = sum(t["quantity"] for t in buys)
    sell_qty = sum(t["quantity"] for t in sells)
    open_qty = buy_qty - sell_qty
    buy_val = sum(t["quantity"] * t["price"] for t in buys)
    avg_cost = buy_val / buy_qty if buy_qty else 0
    sell_val = sum(t["quantity"] * t["price"] for t in sells)
    realized = sell_val - avg_cost * sell_qty
    unrealized = (current_price - avg_cost) * open_qty if open_qty else 0
    unrealized_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost else 0
    return {
        "buy_qty": buy_qty, "sell_qty": sell_qty, "open_qty": open_qty,
        "avg_cost": avg_cost, "buy_val": buy_val, "sell_val": sell_val,
        "realized": realized, "unrealized": unrealized, "unrealized_pct": unrealized_pct,
    }


def latest_stop(p: dict, as_of: dt.date | None = None):
    sh = p.get("stop_loss_history", [])
    if as_of:
        sh = [s for s in sh if dt.date.fromisoformat(s["date"]) <= as_of]
    return sh[-1] if sh else None


def check_hb100_conditions(df, primary_reason: str):
    """HB100 신규 진입 조건 체크 (playbook §1)."""
    if primary_reason != "HB100":
        return None
    if df is None or df.empty:
        return {"applicable": True, "checks": {"data_missing": True}}
    close = df["Close"]
    high_52w = close.tail(252).max() if len(close) >= 252 else close.max()
    cur = close.iloc[-1]
    pct_from_high = (cur - high_52w) / high_52w * 100
    # MA 계산
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    return {
        "applicable": True,
        "current_price": cur,
        "high_52w": high_52w,
        "pct_from_high": pct_from_high,
        "ma20": ma20,
        "ma60": ma60,
        "price_above_ma20": cur > ma20,
        "price_above_ma60": cur > ma60,
        "within_5pct_of_high": pct_from_high >= -5,
    }


def render_markdown(market: str, p: dict, df, current_price: float,
                     stats: dict, stop: dict | None, hb100_check: dict | None) -> str:
    today = dt.date.today()
    unit = "원" if market == "KR" else "$"
    fx = FX if market == "US" else 1.0
    ticker = p["ticker"]
    name = p.get("name", "")

    # 기술지표
    ma20 = ma60 = high_52w = None
    if df is not None and not df.empty:
        close = df["Close"]
        ma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else None
        ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
        high_52w = close.tail(252).max() if len(close) >= 1 else None

    buys = sorted([t for t in p["trades"] if t["type"] == "buy"], key=lambda t: t["date"])
    sells = sorted([t for t in p["trades"] if t["type"] == "sell"], key=lambda t: t["date"])
    first_buy = dt.date.fromisoformat(buys[0]["date"]) if buys else None
    hold_days = (today - first_buy).days if first_buy else 0

    lines = []
    lines.append(f"# Position Review: {name} ({ticker})")
    lines.append(f"_Generated: {today.isoformat()} · Market: {market} · Status: {p['status'].upper()}_\n")

    # ─────────── §1 포지션 현황 ───────────
    lines.append("## 1. 포지션 현황\n")
    lines.append("| 항목 | 값 |")
    lines.append("|---|---:|")
    lines.append(f"| 평균 단가 | {unit}{stats['avg_cost']:,.2f} |")
    lines.append(f"| 현재가 | {unit}{current_price:,.2f} |")
    lines.append(f"| 수량 (open) | {stats['open_qty']} |")
    lines.append(f"| 평가 금액 | {unit}{current_price * stats['open_qty']:,.0f} |")
    lines.append(f"| 투입 원금 (누적 매수) | {unit}{stats['buy_val']:,.0f} |")
    lines.append(f"| 미실현 P&L | **{unit}{stats['unrealized']:+,.0f} ({stats['unrealized_pct']:+.2f}%)** |")
    lines.append(f"| 실현 손익 (부분 매도) | {unit}{stats['realized']:+,.0f} |")
    if first_buy:
        lines.append(f"| 최초 진입일 / 보유일 | {first_buy} / **{hold_days}일** |")
    if stop:
        dist = (current_price - stop['price']) / stop['price'] * 100
        lines.append(f"| 활성 손절선 | {unit}{stop['price']:,.0f} ({stop['date']}, 이탈까지 {dist:+.2f}%) |")
    lines.append("")

    # ─────────── §2 진입 이력 ───────────
    lines.append("## 2. 진입·청산 이력\n")
    lines.append("| 일자 | 구분 | 가격 | 수량 | entry_reason | entry_type | 메모 |")
    lines.append("|---|---|---:|---:|---|---|---|")
    for t in sorted(p["trades"], key=lambda x: x["date"]):
        kind = "매수" if t["type"] == "buy" else "매도"
        etype = t.get("entry_type", "initial" if t["type"] == "buy" else "")
        reason = t.get("entry_reason", t.get("reason", ""))
        memo = t.get("memo", "") or t.get("reason", "")
        lines.append(f"| {t['date']} | {kind} | {unit}{t['price']:,} | {t['quantity']} | {reason} | {etype} | {memo} |")
    lines.append("")

    # ─────────── §3 기술적 상태 ───────────
    lines.append("## 3. 기술적 상태\n")
    if df is None or df.empty:
        lines.append("_가격 데이터 수집 실패 — fdr 연결 확인 필요._\n")
    else:
        # 이탈까지의 거리
        def dist(val, target, is_below=False):
            if val is None or target is None: return "-"
            pct = (target - val) / val * 100
            return f"{pct:+.2f}%"
        lines.append("| 지표 | 값 | 현재가 대비 |")
        lines.append("|---|---:|---:|")
        lines.append(f"| 20일 이평선 | {unit}{ma20:,.2f} | {dist(current_price, ma20)} |" if ma20 else "| 20일 이평선 | — | — |")
        lines.append(f"| 60일 이평선 | {unit}{ma60:,.2f} | {dist(current_price, ma60)} |" if ma60 else "| 60일 이평선 | — | — |")
        if stop:
            lines.append(f"| 손절선 | {unit}{stop['price']:,.0f} | {dist(current_price, stop['price'])} |")
        if high_52w:
            lines.append(f"| 52주 고점 | {unit}{high_52w:,.2f} | {dist(current_price, high_52w)} |")
        # 20% 목표 (1차 익절)
        target_20 = stats["avg_cost"] * 1.20
        gap = (target_20 - current_price) / current_price * 100
        if current_price >= target_20:
            lines.append(f"| +20% 1차 익절 트리거 | {unit}{target_20:,.2f} | **✅ 이미 도달** |")
        else:
            lines.append(f"| +20% 1차 익절 트리거 | {unit}{target_20:,.2f} | 도달까지 {gap:+.2f}% |")
        lines.append("")

    # ─────────── §4 Playbook 정합성 ───────────
    lines.append("## 4. Playbook 정합성 체크\n")
    # primary entry reason
    reasons = Counter(t.get("entry_reason") for t in buys if t.get("entry_reason"))
    primary = reasons.most_common(1)[0][0] if reasons else None
    lines.append(f"- **진입 신호**: {primary or '(미기록)'}")

    if hb100_check and hb100_check.get("applicable"):
        lines.append("- **HB100 신규 진입 조건** (playbook §1):")
        c = hb100_check
        if not c.get("data_missing"):
            lines.append(f"  - 52주 고점 대비: {c['pct_from_high']:+.2f}% ({'✅ -5% 이내' if c['within_5pct_of_high'] else '❌ -5% 이탈'})")
            lines.append(f"  - 현재가가 MA20 {'위 ✅' if c['price_above_ma20'] else '아래 ❌'}")
            lines.append(f"  - 현재가가 MA60 {'위 ✅' if c['price_above_ma60'] else '아래 ❌'}")
            lines.append("  - (컵 패턴 저점 형성 완료 여부는 육안 확인 필요 — 스크리너 판정 로직 미구현)")

    # 4단계 청산 트리거 상태
    if df is not None and not df.empty and ma20 and ma60:
        lines.append("- **4단계 청산 트리거 상태** (playbook §3):")
        avg = stats["avg_cost"]
        lines.append(f"  - +20% 1차 익절: {'✅ 도달' if current_price >= avg * 1.20 else f'⏸ 미도달 (+{(current_price/avg - 1)*100:.1f}%)'}")
        lines.append(f"  - MA20 이탈: {'✅ 안전 (위)' if current_price > ma20 else '⚠️ 발동 (아래)'}")
        lines.append(f"  - MA60 이탈: {'✅ 안전 (위)' if current_price > ma60 else '❌ 발동 (아래)'}")
    lines.append("")

    # ─────────── §5 시나리오 ───────────
    if df is not None and not df.empty and stats["open_qty"] > 0:
        lines.append("## 5. 시나리오별 손익 예측\n")
        avg = stats["avg_cost"]
        qty = stats["open_qty"]
        lines.append("| 시나리오 | 예상 단가 | 영향 수량 | 예상 손익 |")
        lines.append("|---|---:|---:|---:|")
        # +20% 도달
        price_20 = avg * 1.20
        qty_20 = int(qty * 0.20)
        pnl_20 = (price_20 - avg) * qty_20
        lines.append(f"| +20% 도달 → 20% 익절 | {unit}{price_20:,.2f} | {qty_20} | {unit}{pnl_20:+,.0f} |")
        # MA20 이탈 (이전 +20% 이미 빠졌다고 가정, 남은 80% 중 30%)
        if ma20:
            qty_ma20 = int((qty - qty_20) * 0.30)
            pnl_ma20 = (ma20 - avg) * qty_ma20
            lines.append(f"| MA20 이탈 → 30% 추가 청산 | {unit}{ma20:,.2f} | {qty_ma20} | {unit}{pnl_ma20:+,.0f} |")
        # 손절선 도달
        if stop:
            pnl_stop = (stop['price'] - avg) * qty
            lines.append(f"| 손절선 도달 → 전량 청산 | {unit}{stop['price']:,.0f} | {qty} (전량) | {unit}{pnl_stop:+,.0f} |")
        lines.append("")

    # ─────────── §6 결정 권고 ───────────
    lines.append("## 6. 결정 권고 (자동 초안)\n")
    lines.append("> 아래는 룰 기반 자동 제안입니다. 최종 판단은 사용자가 내립니다.\n")
    # 단순 룰: MA 이탈 여부 + 손절선 여력 + 수익률로 판정
    if df is None or df.empty:
        lines.append("- **데이터 부족** — 수동 판단 필요.")
    else:
        verdict = []
        if stats["unrealized_pct"] >= 20:
            verdict.append("**Trim (20% 1차 익절 조건 충족)** — 20% 비중 부분 매도")
        elif ma20 and current_price < ma20:
            verdict.append("**Trim (MA20 이탈)** — 30% 추가 청산")
        elif ma60 and current_price < ma60:
            verdict.append("**Exit (MA60 이탈)** — 잔여 전량 청산")
        elif stop and current_price <= stop['price']:
            verdict.append("**Exit (손절선 도달)** — 전량 청산")
        else:
            # Hold 또는 Add 후보
            if primary == "HB100" and ma20 and current_price > ma20 and stats["unrealized_pct"] > 0:
                verdict.append("**Hold** — 핸들 상단 돌파 시 추가매수 30% 이내 고려")
            else:
                verdict.append("**Hold** — 트리거 없음")
        for v in verdict:
            lines.append(f"- {v}")
    lines.append("")

    # ─────────── §7 관찰 포인트 ───────────
    lines.append("## 7. 다음 며칠 관찰 포인트\n")
    if df is not None and not df.empty and ma20:
        lines.append(f"- **MA20({unit}{ma20:,.0f}) 이탈 여부** — 이탈 시 30% 청산 트리거")
        if ma60:
            lines.append(f"- **MA60({unit}{ma60:,.0f}) 이탈 여부** — 이탈 시 잔여 전량 청산")
        if stats["unrealized_pct"] < 20:
            lines.append(f"- **+20% 터치 여부** — {unit}{stats['avg_cost']*1.20:,.0f}")
        if stop:
            lines.append(f"- **손절선({unit}{stop['price']:,.0f}) 접근 여부**")
    lines.append("")

    lines.append("---")
    lines.append(f"_Generated by position_review.py · {dt.datetime.now().isoformat(timespec='seconds')}_")
    return "\n".join(lines)


def review_ticker(ticker: str):
    market, p = find_position(ticker)
    if p is None:
        print(f"[!] {ticker} — 포트폴리오에서 찾을 수 없음. 후보 평가는 별도 스크립트 필요.", file=sys.stderr)
        return None
    fx = FX if market == "US" else 1.0
    # 가격 가져오기 (캐시 우선 → fdr fetch)
    df = fetch_ohlcv(ticker, market)
    if df is None or df.empty:
        print(f"[!] {ticker} — 캐시와 네트워크 모두 실패. 앱에서 차트 한 번 열어 주세요. 현재가 0으로 리포트 생성.", file=sys.stderr)
        df = None
        current_price = 0.0
    else:
        current_price = float(df["Close"].iloc[-1])
    stats = compute_position_stats(p, current_price, fx=1.0)
    stop = latest_stop(p)
    buys = [t for t in p["trades"] if t["type"] == "buy"]
    reasons = Counter(t.get("entry_reason") for t in buys if t.get("entry_reason"))
    primary = reasons.most_common(1)[0][0] if reasons else None
    hb100_check = check_hb100_conditions(df, primary) if primary == "HB100" else None
    md = render_markdown(market, p, df, current_price, stats, stop, hb100_check)
    os.makedirs(OUT_DIR, exist_ok=True)
    today_str = dt.date.today().isoformat()
    out_path = os.path.join(OUT_DIR, f"{today_str}_{ticker}_review.md")
    with open(out_path, "w") as f:
        f.write(md)
    print(f"wrote {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?")
    ap.add_argument("--all-open", action="store_true")
    args = ap.parse_args()

    if args.all_open:
        kr, us = load_portfolios()
        tickers = [p["ticker"] for pf in [kr, us] for p in pf["positions"] if p["status"] == "open"]
        for t in tickers:
            review_ticker(t)
    elif args.ticker:
        review_ticker(args.ticker)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
