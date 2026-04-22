"""Generate a weekly portfolio review report.

Usage:
    python3 weekly_report.py 2026 16          # specific ISO week
    python3 weekly_report.py --all            # backfill all weeks with trades
    python3 weekly_report.py --last-complete  # most recent complete ISO week

Output: reports/weekly/weekly_<YYYY>-W<NN>.md
"""

from __future__ import annotations
import argparse, json, os, sys, datetime as dt
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "reports", "weekly")
FX = 1450  # USD -> KRW for aggregation


def load_portfolio(path):
    with open(os.path.join(ROOT, path)) as f:
        return json.load(f)


def week_bounds(iso_year: int, iso_week: int):
    """Return (monday_date, sunday_date) for the given ISO week."""
    monday = dt.date.fromisocalendar(iso_year, iso_week, 1)
    sunday = monday + dt.timedelta(days=6)
    return monday, sunday


def iter_positions(flag_market: bool = True):
    for market, path in [("KR", "portfolio.json"), ("US", "portfolio_us.json")]:
        pf = load_portfolio(path)
        initial = pf.get("initial_capital", 0)
        for p in pf["positions"]:
            if flag_market:
                yield market, p, initial
            else:
                yield p


def position_avg_cost(p, up_to_date: dt.date | None = None):
    """Average cost per share at end of up_to_date (inclusive), KRW per share."""
    buys = [t for t in p["trades"] if t["type"] == "buy" and (up_to_date is None or dt.date.fromisoformat(t["date"]) <= up_to_date)]
    sells = [t for t in p["trades"] if t["type"] == "sell" and (up_to_date is None or dt.date.fromisoformat(t["date"]) <= up_to_date)]
    buy_qty = sum(t["quantity"] for t in buys)
    sell_qty = sum(t["quantity"] for t in sells)
    if buy_qty == 0:
        return 0, 0, 0
    buy_val = sum(t["quantity"] * t["price"] for t in buys)
    avg = buy_val / buy_qty
    open_qty = buy_qty - sell_qty
    return avg, open_qty, buy_val


def realized_pnl_up_to(p, up_to_date: dt.date | None = None, fx: float = 1.0):
    """Average-cost realized P&L in KRW up to end of date (inclusive)."""
    buys = [t for t in p["trades"] if t["type"] == "buy" and (up_to_date is None or dt.date.fromisoformat(t["date"]) <= up_to_date)]
    sells = [t for t in p["trades"] if t["type"] == "sell" and (up_to_date is None or dt.date.fromisoformat(t["date"]) <= up_to_date)]
    buy_qty = sum(t["quantity"] for t in buys)
    if buy_qty == 0:
        return 0.0, 0
    buy_val = sum(t["quantity"] * t["price"] for t in buys) * fx
    avg = buy_val / buy_qty
    sell_qty = sum(t["quantity"] for t in sells)
    sell_val = sum(t["quantity"] * t["price"] for t in sells) * fx
    realized = sell_val - avg * sell_qty
    return realized, sell_qty


def week_trades(mon: dt.date, sun: dt.date):
    """Yield (market, position, trade, fx)."""
    for market, p, _ in iter_positions():
        fx = FX if market == "US" else 1.0
        for t in p["trades"]:
            td = dt.date.fromisoformat(t["date"])
            if mon <= td <= sun:
                yield market, p, t, fx


def format_krw(x: float) -> str:
    return f"{x:+,.0f}"


def compute_week(mon: dt.date, sun: dt.date):
    # Trades in the week
    trades = list(week_trades(mon, sun))
    # Per-position realized P&L delta: realized_up_to(sun) - realized_up_to(mon - 1 day)
    prev_end = mon - dt.timedelta(days=1)
    per_position = {}  # key = (market, ticker)
    opened_week = []   # new positions this week (first buy in week)
    closed_week = []   # positions that went to zero this week
    trade_records = []  # list of dicts for the trade table
    for market, p, _ in iter_positions():
        fx = FX if market == "US" else 1.0
        buys_all = [t for t in p["trades"] if t["type"] == "buy"]
        if not buys_all:
            continue
        first_buy_date = min(dt.date.fromisoformat(t["date"]) for t in buys_all)
        # status at week end
        _, qty_at_sun, _ = position_avg_cost(p, sun)
        _, qty_at_prev, _ = position_avg_cost(p, prev_end)
        r_sun, _ = realized_pnl_up_to(p, sun, fx)
        r_prev, _ = realized_pnl_up_to(p, prev_end, fx)
        delta_r = r_sun - r_prev
        key = (market, p["ticker"])
        per_position[key] = {
            "market": market,
            "ticker": p["ticker"],
            "name": p.get("name", ""),
            "delta_realized": delta_r,
            "qty_at_week_end": qty_at_sun,
        }
        # opened this week?
        if mon <= first_buy_date <= sun:
            opened_week.append((market, p, first_buy_date))
        # closed this week?
        if qty_at_prev > 0 and qty_at_sun == 0:
            closed_week.append((market, p))

    # Signal-by-signal stats for closures THIS week
    # For each position closed this week, classify by primary entry_reason, realized this week
    signal_agg = defaultdict(lambda: {"count": 0, "wins": 0, "pnl_delta": 0.0})
    closed_pnl_list = []
    for market, p in closed_week:
        fx = FX if market == "US" else 1.0
        buys = [t for t in p["trades"] if t["type"] == "buy"]
        reasons = Counter(t.get("entry_reason") for t in buys if t.get("entry_reason"))
        primary = reasons.most_common(1)[0][0] if reasons else "UNKNOWN"
        # total realized for this position (fully closed so equals sell_value - buy_value)
        buy_val = sum(t["quantity"] * t["price"] for t in buys) * fx
        sell_val = sum(t["quantity"] * t["price"] for t in p["trades"] if t["type"] == "sell") * fx
        pnl = sell_val - buy_val
        closed_pnl_list.append((market, p, pnl, primary))
        signal_agg[primary]["count"] += 1
        signal_agg[primary]["pnl_delta"] += pnl
        if pnl > 0:
            signal_agg[primary]["wins"] += 1

    # Week totals
    week_pnl = sum(v["delta_realized"] for v in per_position.values())
    n_trades = len(trades)
    n_buys = sum(1 for _, _, t, _ in trades if t["type"] == "buy")
    n_sells = sum(1 for _, _, t, _ in trades if t["type"] == "sell")
    # entry_type 세분화 (없는 과거 거래는 initial로 간주)
    n_buys_initial = sum(1 for _, _, t, _ in trades if t["type"] == "buy" and t.get("entry_type", "initial") == "initial")
    n_buys_add_on  = sum(1 for _, _, t, _ in trades if t["type"] == "buy" and t.get("entry_type") == "add_on")
    add_on_trades  = [(m, p, t) for m, p, t, _ in trades if t["type"] == "buy" and t.get("entry_type") == "add_on"]
    gross_buy = sum(t["quantity"] * t["price"] * fx for _, _, t, fx in trades if t["type"] == "buy")
    gross_sell = sum(t["quantity"] * t["price"] * fx for _, _, t, fx in trades if t["type"] == "sell")

    # Running cumulative realized up to end of week
    cum_realized = 0.0
    for market, p, _ in iter_positions():
        fx = FX if market == "US" else 1.0
        r, _ = realized_pnl_up_to(p, sun, fx)
        cum_realized += r

    # Open positions snapshot at week end
    open_snapshot = []
    for market, p, _ in iter_positions():
        fx = FX if market == "US" else 1.0
        avg, qty, _ = position_avg_cost(p, sun)
        if qty > 0:
            # latest stop_loss up to sun
            sh = [s for s in p.get("stop_loss_history", []) if dt.date.fromisoformat(s["date"]) <= sun]
            stop = sh[-1]["price"] if sh else None
            buys = [t for t in p["trades"] if t["type"] == "buy" and dt.date.fromisoformat(t["date"]) <= sun]
            reasons = Counter(t.get("entry_reason") for t in buys if t.get("entry_reason"))
            primary = reasons.most_common(1)[0][0] if reasons else ""
            first_buy_date = min(dt.date.fromisoformat(t["date"]) for t in buys)
            hold_days = (sun - first_buy_date).days
            open_snapshot.append({
                "market": market,
                "ticker": p["ticker"],
                "name": p.get("name", ""),
                "avg_cost": avg,
                "qty": qty,
                "stop": stop,
                "primary": primary,
                "hold_days": hold_days,
            })

    # Consecutive loss streak ending this week (chronological closed positions up to sun)
    closed_chrono = []
    for market, p, _ in iter_positions():
        fx = FX if market == "US" else 1.0
        _, qty_sun, _ = position_avg_cost(p, sun)
        sells = [t for t in p["trades"] if t["type"] == "sell"]
        if qty_sun == 0 and sells:
            last_sell = max(dt.date.fromisoformat(t["date"]) for t in sells)
            if last_sell <= sun:
                buys = [t for t in p["trades"] if t["type"] == "buy"]
                buy_val = sum(t["quantity"] * t["price"] for t in buys) * fx
                sell_val = sum(t["quantity"] * t["price"] for t in sells) * fx
                closed_chrono.append((last_sell, sell_val - buy_val))
    closed_chrono.sort()
    max_loss_streak = 0
    cur = 0
    for _, pnl in closed_chrono:
        if pnl < 0:
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            cur = 0
    ending_streak = 0
    for _, pnl in reversed(closed_chrono):
        if pnl < 0:
            ending_streak += 1
        else:
            break

    return {
        "week_pnl": week_pnl,
        "cum_realized": cum_realized,
        "n_trades": n_trades,
        "n_buys": n_buys,
        "n_sells": n_sells,
        "n_buys_initial": n_buys_initial,
        "n_buys_add_on": n_buys_add_on,
        "add_on_trades": add_on_trades,
        "gross_buy": gross_buy,
        "gross_sell": gross_sell,
        "opened_week": opened_week,
        "closed_week": closed_week,
        "signal_agg": dict(signal_agg),
        "open_snapshot": open_snapshot,
        "trades": trades,
        "closed_pnl_list": closed_pnl_list,
        "max_loss_streak_to_date": max_loss_streak,
        "ending_loss_streak": ending_streak,
    }


def render_markdown(iso_year: int, iso_week: int) -> str:
    mon, sun = week_bounds(iso_year, iso_week)
    d = compute_week(mon, sun)

    n_closed = len(d["closed_week"])
    wins = sum(1 for _, _, pnl, _ in d["closed_pnl_list"] if pnl > 0)
    losses = sum(1 for _, _, pnl, _ in d["closed_pnl_list"] if pnl < 0)
    win_rate = (wins / n_closed * 100) if n_closed else 0

    gross_win = sum(pnl for _, _, pnl, _ in d["closed_pnl_list"] if pnl > 0)
    gross_loss = sum(pnl for _, _, pnl, _ in d["closed_pnl_list"] if pnl < 0)
    avg_win = gross_win / wins if wins else 0
    avg_loss = gross_loss / losses if losses else 0
    payoff = avg_win / abs(avg_loss) if avg_loss else float("inf")

    lines = []
    lines.append(f"# 주간 리뷰 {iso_year}-W{iso_week:02d} ({mon.isoformat()} ~ {sun.isoformat()})")
    lines.append("")
    lines.append("## 1. 주간 요약")
    lines.append("")
    lines.append("| 항목 | 수치 |")
    lines.append("|---|---:|")
    lines.append(f"| 주간 실현손익 | **{format_krw(d['week_pnl'])} KRW** |")
    lines.append(f"| 누적 실현손익 (~{sun}) | {format_krw(d['cum_realized'])} KRW |")
    buy_breakdown = f"매수 {d['n_buys']}"
    if d.get('n_buys_add_on', 0) > 0:
        buy_breakdown += f" (신규 {d['n_buys_initial']} / 추가매수 {d['n_buys_add_on']})"
    lines.append(f"| 체결 건수 | {d['n_trades']}건 ({buy_breakdown} / 매도 {d['n_sells']}) |")
    lines.append(f"| 매수 금액 / 매도 금액 | ₩{d['gross_buy']:,.0f} / ₩{d['gross_sell']:,.0f} |")
    new_entry_line = f"| 신규 진입 / 완전 청산 | {len(d['opened_week'])}건 / {n_closed}건"
    if d.get('n_buys_add_on', 0) > 0:
        new_entry_line += f"  `+추가매수 {d['n_buys_add_on']}건`"
    new_entry_line += " |"
    lines.append(new_entry_line)
    if n_closed:
        lines.append(f"| 주간 승률 | {win_rate:.1f}% ({wins}W / {losses}L) |")
        lines.append(f"| 평균 수익 / 평균 손실 | ₩{avg_win:+,.0f} / ₩{avg_loss:+,.0f} (payoff {payoff:.2f}) |")
    lines.append(f"| 최장 연속 손실 (누적~이번주) | {d['max_loss_streak_to_date']}건 |")
    if d['ending_loss_streak'] >= 3:
        lines.append(f"| ⚠ 현재 연속 손실 진행 중 | {d['ending_loss_streak']}건 연속 |")
    lines.append("")

    # Section 2: new entries
    lines.append("## 2. 신규 진입")
    lines.append("")
    if not d["opened_week"]:
        lines.append("_이번 주 신규 진입 없음._")
    else:
        lines.append("| 시장 | 티커 | 종목명 | 최초 매수일 | 진입 사유 | 매수가 |")
        lines.append("|---|---|---|---|---|---:|")
        for market, p, fbd in sorted(d["opened_week"], key=lambda x: x[2]):
            buys_in_week = [t for t in p["trades"] if t["type"] == "buy" and mon <= dt.date.fromisoformat(t["date"]) <= sun]
            first = min(buys_in_week, key=lambda t: t["date"])
            reason = first.get("entry_reason", "")
            unit = "원" if market == "KR" else "$"
            lines.append(f"| {market} | {p['ticker']} | {p.get('name','')} | {first['date']} | {reason} | {unit}{first['price']:,} |")
    lines.append("")

    # Section 2b: add-on buys (pyramid adds to existing open positions)
    if d.get("add_on_trades"):
        lines.append("### 2b. 이번 주 추가매수 (기보유 포지션 스케일 업)")
        lines.append("")
        lines.append("> `entry_type=add_on` — 최초 진입 근거는 유지되며, 이 매수는 피라미드 추가 매수로 기록됩니다. 신규 진입 카운트와는 **별도**로 관리하세요.")
        lines.append("")
        lines.append("| 시장 | 티커 | 종목명 | 매수일 | 최초근거 | 매수가 | 수량 |")
        lines.append("|---|---|---|---|---|---:|---:|")
        for market, p, t in sorted(d["add_on_trades"], key=lambda x: x[2]["date"]):
            unit = "원" if market == "KR" else "$"
            price_fmt = f"{unit}{t['price']:,}"
            lines.append(
                f"| {market} | {p['ticker']} | {p.get('name','')} | "
                f"{t['date']} | {t.get('entry_reason','')} | {price_fmt} | {t['quantity']} |"
            )
        lines.append("")

    # Section 3: closed positions
    lines.append("## 3. 완전 청산 포지션")
    lines.append("")
    if not d["closed_pnl_list"]:
        lines.append("_이번 주 청산된 포지션 없음._")
    else:
        lines.append("| 시장 | 티커 | 종목명 | 진입 | 실현손익(KRW) | 수익률 | 보유일 | 주요 사유 |")
        lines.append("|---|---|---|---|---:|---:|---:|---|")
        for market, p, pnl, primary in sorted(d["closed_pnl_list"], key=lambda x: x[2]):
            fx = FX if market == "US" else 1.0
            buys = [t for t in p["trades"] if t["type"] == "buy"]
            sells = [t for t in p["trades"] if t["type"] == "sell"]
            buy_val = sum(t["quantity"] * t["price"] for t in buys) * fx
            pct = pnl / buy_val * 100 if buy_val else 0
            fb = min(dt.date.fromisoformat(t["date"]) for t in buys)
            ls = max(dt.date.fromisoformat(t["date"]) for t in sells) if sells else sun
            hold = (ls - fb).days
            exit_reasons = set(t.get("reason", "").split("—")[0].strip() for t in sells if t.get("reason"))
            exit_summary = ", ".join(sorted(exit_reasons)) if exit_reasons else ""
            lines.append(f"| {market} | {p['ticker']} | {p.get('name','')} | {primary} | {format_krw(pnl)} | {pct:+.2f}% | {hold}d | {exit_summary} |")
    lines.append("")

    # Section 4: signal breakdown this week
    lines.append("## 4. 진입 신호별 성과 (이번 주 청산 기준)")
    lines.append("")
    if not d["signal_agg"]:
        lines.append("_이번 주 청산된 포지션이 없어 신호별 집계 없음._")
    else:
        lines.append("| 진입 신호 | 청산 건수 | 승 / 패 | 승률 | 총 실현손익(KRW) | 평균 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for sig, s in sorted(d["signal_agg"].items(), key=lambda x: -x[1]["pnl_delta"]):
            n = s["count"]; w = s["wins"]
            wr = w / n * 100 if n else 0
            avg = s["pnl_delta"] / n if n else 0
            lines.append(f"| **{sig}** | {n} | {w}/{n - w} | {wr:.0f}% | {format_krw(s['pnl_delta'])} | {format_krw(avg)} |")
    lines.append("")

    # Section 5: open snapshot
    lines.append("## 5. 주말 기준 열린 포지션 스냅샷")
    lines.append("")
    if not d["open_snapshot"]:
        lines.append("_열린 포지션 없음._")
    else:
        lines.append("| 시장 | 티커 | 종목명 | 평균단가 | 수량 | 손절선 | 진입신호 | 보유일 |")
        lines.append("|---|---|---|---:|---:|---:|---|---:|")
        for s in sorted(d["open_snapshot"], key=lambda x: (x["market"], x["ticker"])):
            unit = "원" if s["market"] == "KR" else "$"
            avg_disp = f"{unit}{s['avg_cost']:,.0f}" if s["market"] == "KR" else f"{unit}{s['avg_cost']:.2f}"
            stop_disp = f"{unit}{s['stop']:,.0f}" if s["stop"] and s["market"] == "KR" else (f"{unit}{s['stop']:.2f}" if s["stop"] else "-")
            lines.append(f"| {s['market']} | {s['ticker']} | {s['name']} | {avg_disp} | {s['qty']} | {stop_disp} | {s['primary']} | {s['hold_days']}d |")
    lines.append("")

    # Section 6: week takeaways (automated heuristics)
    lines.append("## 6. 이번 주 교훈 (데이터 기반 자동 관찰)")
    lines.append("")
    obs = []
    if d["week_pnl"] > 0:
        obs.append(f"✅ 주간 실현손익 **플러스** ({format_krw(d['week_pnl'])} KRW). 이번 주 결정이 수익을 만들었습니다.")
    elif d["week_pnl"] < 0:
        obs.append(f"⚠️ 주간 실현손익 **마이너스** ({format_krw(d['week_pnl'])} KRW). 어느 신호가 주로 잃었는지 아래 4번 표 확인.")
    if d["n_trades"] > 30:
        obs.append(f"⚠️ 주간 체결 **{d['n_trades']}건**은 과매매 구간. 주 25건 이하를 권장.")
    if n_closed and win_rate < 30:
        obs.append(f"⚠️ 주간 승률 {win_rate:.0f}%로 낮음. 시장 레짐 필터 재점검 신호.")
    if d["ending_loss_streak"] >= 3:
        obs.append(f"⚠️ {d['ending_loss_streak']}건 연속 손실 진행 중 — 다음 주 신규 진입을 줄이고 신호 재검토.")
    # Signal outliers
    for sig, s in d["signal_agg"].items():
        if s["count"] >= 3 and s["wins"] == 0:
            obs.append(f"❌ **{sig}** 신호가 이번 주 {s['count']}건 모두 손실. 해당 신호 사용 여부 재검토.")
    if not d["opened_week"]:
        obs.append("ℹ️ 신규 진입이 없었던 주. 관망 주간 여부 확인.")
    if not obs:
        obs.append("이번 주 특이점 없음. 계획대로 진행 중.")
    for o in obs:
        lines.append(f"- {o}")
    lines.append("")

    lines.append("---")
    lines.append(f"_generated {dt.datetime.now().isoformat(timespec='seconds')}_")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("year", nargs="?", type=int)
    ap.add_argument("week", nargs="?", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--last-complete", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    weeks_to_run = []
    if args.all:
        # every ISO week that has at least 1 trade
        seen = set()
        for market, p, _ in iter_positions():
            for t in p["trades"]:
                td = dt.date.fromisoformat(t["date"])
                iy, iw, _ = td.isocalendar()
                seen.add((iy, iw))
        weeks_to_run = sorted(seen)
    elif args.last_complete:
        today = dt.date.today()
        monday = today - dt.timedelta(days=today.weekday())
        last_mon = monday - dt.timedelta(days=7)
        iy, iw, _ = last_mon.isocalendar()
        weeks_to_run = [(iy, iw)]
    elif args.year and args.week:
        weeks_to_run = [(args.year, args.week)]
    else:
        print("Specify year+week, --all, or --last-complete", file=sys.stderr)
        sys.exit(1)

    for iy, iw in weeks_to_run:
        md = render_markdown(iy, iw)
        path = os.path.join(OUT_DIR, f"weekly_{iy}-W{iw:02d}.md")
        with open(path, "w") as f:
            f.write(md)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
