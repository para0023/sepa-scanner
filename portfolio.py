"""
SEPA Scanner - 포트폴리오 관리 모듈
"""
import json
import uuid
from pathlib import Path
from datetime import datetime

import pandas as pd

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

# ─────────────────────────────────────────────
# 거래비용 상수 (삼성증권 기준)
# ─────────────────────────────────────────────
_FEE_KR   = 0.001439   # 국내 수수료 (매수/매도 각각)
_TAX_KR   = 0.0018     # 증권거래세 (매도 시만, KOSPI/KOSDAQ 공통)
_FEE_US   = 0.0025     # 미국 수수료 (매수/매도 각각)


def set_portfolio_file(path: str):
    """포트폴리오 파일 경로 전환 (한국/미국 탭 전환용)"""
    global PORTFOLIO_FILE
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / path
    PORTFOLIO_FILE = p


def _is_kr() -> bool:
    """현재 포트폴리오 파일이 한국(KR) 시장인지 여부"""
    return "us" not in PORTFOLIO_FILE.stem.lower()


def _calc_fees(buy_amount: float, sell_amount: float) -> float:
    """매수/매도 금액 기준 거래비용 합계 (수수료 + 세금)"""
    if _is_kr():
        return buy_amount * _FEE_KR + sell_amount * (_FEE_KR + _TAX_KR)
    else:
        return (buy_amount + sell_amount) * _FEE_US


# ─────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────

def _load() -> dict:
    if not PORTFOLIO_FILE.exists():
        return {"positions": [], "trade_log": []}
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("positions", [])
        data.setdefault("trade_log", [])
        return data
    except Exception:
        return {"positions": [], "trade_log": []}


def _save(data: dict):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _remaining_qty(pos: dict) -> int:
    bought = sum(t["quantity"] for t in pos["trades"] if t["type"] == "buy")
    sold   = sum(t["quantity"] for t in pos["trades"] if t["type"] == "sell")
    return bought - sold


def _avg_price(pos: dict) -> float:
    """현재 보유 평균단가 (FIFO 근사)"""
    cost = 0.0
    qty  = 0
    for t in pos["trades"]:
        if t["type"] == "buy":
            cost += t["price"] * t["quantity"]
            qty  += t["quantity"]
        elif t["type"] == "sell" and qty > 0:
            avg   = cost / qty
            sold  = min(t["quantity"], qty)
            cost -= avg * sold
            qty  -= sold
    return cost / qty if qty > 0 else 0.0


def _current_stop_loss(pos: dict) -> float:
    """현재 유효 손절가: stop_loss_history 마지막 값 (없으면 마지막 매수의 손절가)"""
    history = pos.get("stop_loss_history", [])
    if history:
        return history[-1]["price"]
    buy_trades = [t for t in pos["trades"] if t["type"] == "buy"]
    if buy_trades:
        return buy_trades[-1].get("stop_loss", 0)
    return 0.0


def _add_stop_loss_record(pos: dict, date: str, price: float, source: str, note: str = ""):
    """손절가 이력에 항목 추가"""
    pos.setdefault("stop_loss_history", [])
    pos["stop_loss_history"].append({
        "date":   date,
        "price":  price,
        "source": source,   # "최초매수" / "추가매수" / "수동수정"
        "note":   note,
    })


# ─────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────

def add_buy(
    ticker: str, name: str, date: str,
    price: float, quantity: int,
    stop_loss: float, entry_reason: str, memo: str = "",
) -> str:
    """매수 기록. 동일 종목 오픈 포지션이 있으면 추가매수(피라미딩)."""
    data = _load()
    pos  = next(
        (p for p in data["positions"] if p["ticker"] == ticker and p["status"] == "open"),
        None,
    )

    is_new = pos is None
    if is_new:
        pos = {"id": str(uuid.uuid4()), "ticker": ticker,
               "name": name, "status": "open", "trades": [],
               "stop_loss_history": []}
        data["positions"].append(pos)

    pos["trades"].append({
        "id":           str(uuid.uuid4()),
        "type":         "buy",
        "date":         date,
        "price":        price,
        "quantity":     quantity,
        "stop_loss":    stop_loss,
        "entry_reason": entry_reason,
        "memo":         memo,
    })

    # 손절가 이력 자동 기록
    source = "최초매수" if is_new else "추가매수"
    _add_stop_loss_record(pos, date, stop_loss, source, note=memo)

    data["trade_log"].append({
        "date": date, "ticker": ticker, "name": name,
        "type": "매수", "price": price, "quantity": quantity,
        "entry_reason": entry_reason, "memo": memo,
        "position_id": pos["id"],
        "trade_id": pos["trades"][-1]["id"],
    })

    _save(data)
    return pos["id"]


def add_sell(
    position_id: str, date: str,
    price: float, quantity: int, reason: str = "",
) -> bool:
    """매도 기록. 잔여 수량 0이 되면 status=closed."""
    data = _load()
    pos  = next((p for p in data["positions"] if p["id"] == position_id), None)
    if pos is None:
        return False

    pos["trades"].append({
        "id": str(uuid.uuid4()), "type": "sell",
        "date": date, "price": price,
        "quantity": quantity, "reason": reason,
    })

    if _remaining_qty(pos) <= 0:
        pos["status"] = "closed"

    data["trade_log"].append({
        "date": date, "ticker": pos["ticker"], "name": pos["name"],
        "type": "매도", "price": price, "quantity": quantity,
        "reason": reason, "position_id": position_id,
        "trade_id": pos["trades"][-1]["id"],
    })

    _save(data)
    return True


def add_capital_flow(date: str, amount: float, note: str = ""):
    """
    입출금 기록.
    amount 양수 = 입금, 음수 = 출금
    """
    data = _load()
    data.setdefault("capital_flows", [])
    data["capital_flows"].append({
        "id":     str(uuid.uuid4()),
        "date":   date,
        "amount": amount,
        "note":   note,
    })
    _save(data)


def delete_capital_flow(flow_id: str) -> bool:
    """입출금 항목 삭제"""
    data = _load()
    flows = data.get("capital_flows", [])
    new_flows = [f for f in flows if f.get("id") != flow_id]
    if len(new_flows) == len(flows):
        return False
    data["capital_flows"] = new_flows
    _save(data)
    return True


def get_capital_flows() -> pd.DataFrame:
    """입출금 이력 반환"""
    data = _load()
    flows = data.get("capital_flows", [])
    if not flows:
        return pd.DataFrame()
    df = pd.DataFrame(flows).sort_values("date", ascending=False).reset_index(drop=True)
    df.columns = [{"date": "날짜", "amount": "금액(원)", "note": "메모", "id": "id"}.get(c, c) for c in df.columns]
    return df


def get_total_capital() -> float:
    """현재 원금 합계 (입금 합계 - 출금 합계)"""
    data = _load()
    flows = data.get("capital_flows", [])
    return sum(f["amount"] for f in flows)


# 하위 호환 유지
def get_initial_capital() -> float:
    return get_total_capital()


def set_initial_capital(amount: float):
    """기존 입출금 이력 없을 때 초기값 설정용"""
    data = _load()
    if not data.get("capital_flows"):
        add_capital_flow(
            datetime.now().strftime("%Y-%m-%d"),
            amount, "초기 원금 설정"
        )


def delete_trade(position_id: str, trade_id: str) -> bool:
    """거래 내역 삭제. 잔여수량 재계산 후 status 업데이트."""
    data = _load()
    pos  = next((p for p in data["positions"] if p["id"] == position_id), None)
    if pos is None:
        return False

    original = next((t for t in pos["trades"] if t["id"] == trade_id), None)
    if original is None:
        return False

    pos["trades"] = [t for t in pos["trades"] if t["id"] != trade_id]

    # status 재계산
    remaining = _remaining_qty(pos)
    if remaining > 0:
        pos["status"] = "open"
    elif remaining == 0 and any(t["type"] == "sell" for t in pos["trades"]):
        pos["status"] = "closed"

    # trade_log에서도 동일 항목 제거 (trade_id 우선, 없으면 position_id+type+date+price+qty 매칭)
    ttype  = "매수" if original["type"] == "buy" else "매도"
    removed = False
    new_log = []
    for t in data["trade_log"]:
        if not removed:
            if t.get("trade_id") == trade_id:
                removed = True
                continue
            if (
                t.get("position_id") == position_id
                and t.get("type")     == ttype
                and t.get("date")     == original["date"]
                and t.get("price")    == original["price"]
                and t.get("quantity") == original["quantity"]
            ):
                removed = True
                continue
        new_log.append(t)
    data["trade_log"] = new_log

    _save(data)
    return True


def update_trade(position_id: str, trade_id: str, fields: dict) -> bool:
    """거래 내역 수정. fields에 수정할 키-값만 전달."""
    data = _load()
    pos  = next((p for p in data["positions"] if p["id"] == position_id), None)
    if pos is None:
        return False

    trade = next((t for t in pos["trades"] if t["id"] == trade_id), None)
    if trade is None:
        return False

    old_price = trade["price"]
    old_qty   = trade["quantity"]
    old_date  = trade["date"]
    ttype     = "매수" if trade["type"] == "buy" else "매도"

    trade.update(fields)

    # status 재계산
    remaining = _remaining_qty(pos)
    if remaining > 0:
        pos["status"] = "open"
    elif remaining == 0 and any(t["type"] == "sell" for t in pos["trades"]):
        pos["status"] = "closed"

    # trade_log 동기화 (trade_id 우선, 없으면 position_id+type+date+price+qty 매칭)
    for t in data["trade_log"]:
        match = (t.get("trade_id") == trade_id) or (
            not t.get("trade_id")
            and t.get("position_id") == position_id
            and t.get("type")        == ttype
            and t.get("date")        == old_date
            and t.get("price")       == old_price
            and t.get("quantity")    == old_qty
        )
        if match:
            if "date"         in fields: t["date"]         = fields["date"]
            if "price"        in fields: t["price"]        = fields["price"]
            if "quantity"     in fields: t["quantity"]     = fields["quantity"]
            if "entry_reason" in fields: t["entry_reason"] = fields["entry_reason"]
            if "memo"         in fields: t["memo"]         = fields["memo"]
            if "reason"       in fields: t["reason"]       = fields["reason"]
            break

    _save(data)
    return True


def update_stop_loss(position_id: str, date: str, price: float, note: str = "") -> bool:
    """손절가 수동 수정. 이력에 기록."""
    data = _load()
    pos  = next((p for p in data["positions"] if p["id"] == position_id), None)
    if pos is None:
        return False
    _add_stop_loss_record(pos, date, price, source="수동수정", note=note)
    _save(data)
    return True


def get_stop_loss_history(position_id: str) -> pd.DataFrame:
    """특정 포지션의 손절가 변경 이력"""
    data = _load()
    pos  = next((p for p in data["positions"] if p["id"] == position_id), None)
    if pos is None:
        return pd.DataFrame()
    history = pos.get("stop_loss_history", [])
    if not history:
        return pd.DataFrame()
    df = pd.DataFrame(history)
    df.columns = [{"date": "날짜", "price": "손절가", "source": "구분", "note": "메모"}.get(c, c)
                  for c in df.columns]
    return df


def get_open_positions() -> pd.DataFrame:
    data = _load()
    rows = []
    for pos in data["positions"]:
        if pos["status"] != "open":
            continue
        qty          = _remaining_qty(pos)
        avg          = _avg_price(pos)
        buy_trades   = [t for t in pos["trades"] if t["type"] == "buy"]
        first_buy    = buy_trades[0] if buy_trades else {}
        entry_date   = first_buy.get("date", "")
        entry_reason = first_buy.get("entry_reason", "")
        memo         = first_buy.get("memo", "")
        stop_loss    = _current_stop_loss(pos)   # 항상 최신 손절가

        try:
            days = (datetime.now().date() -
                    datetime.strptime(entry_date, "%Y-%m-%d").date()).days
        except Exception:
            days = 0

        rows.append({
            "position_id": pos["id"],
            "종목코드":    pos["ticker"],
            "종목명":      pos["name"],
            "매수일":      entry_date,
            "경과일":      days,
            "평균매수가":  round(avg, 2),
            "수량":        qty,
            "손절가":      stop_loss,
            "진입근거":    entry_reason,
            "메모":        memo,
        })

    cols = ["position_id", "종목코드", "종목명", "매수일", "경과일",
            "평균매수가", "수량", "손절가", "진입근거", "메모"]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def get_realized_pnl() -> pd.DataFrame:
    """
    매도가 발생한 모든 건의 실현손익.
    매도 시점 평균단가(FIFO) 기준으로 손익 계산.
    부분 청산 포함.
    """
    data = _load()
    rows = []

    for pos in data["positions"]:
        buys  = [t for t in pos["trades"] if t["type"] == "buy"]
        sells = [t for t in pos["trades"] if t["type"] == "sell"]
        if not sells:
            continue

        # 최초 손절가: stop_loss_history 첫 항목 우선, 없으면 첫 매수의 stop_loss
        history = pos.get("stop_loss_history", [])
        first_history = next((h for h in history if h.get("price", 0) > 0), None)
        if first_history:
            initial_stop = first_history["price"]
        else:
            initial_stop = buys[0].get("stop_loss", 0) if buys else 0

        # FIFO로 매수 큐 구성
        buy_queue = [[t["price"], t["quantity"]] for t in buys]  # [price, remaining_qty]

        for sell in sells:
            sell_qty   = sell["quantity"]
            sell_price = sell["price"]
            cost       = 0.0
            remaining  = sell_qty

            for b in buy_queue:
                if remaining <= 0:
                    break
                used = min(b[1], remaining)
                cost += b[0] * used
                b[1] -= used
                remaining -= used

            avg_buy   = cost / sell_qty if sell_qty > 0 else 0
            pnl_amt   = (sell_price - avg_buy) * sell_qty
            pnl_pct   = (sell_price / avg_buy - 1) * 100 if avg_buy > 0 else 0
            fees      = _calc_fees(avg_buy * sell_qty, sell_price * sell_qty)
            net_pnl   = pnl_amt - fees
            net_pct   = net_pnl / (avg_buy * sell_qty) * 100 if avg_buy > 0 else 0

            # RR ratio = (매도가 - 매수가) / (매수가 - 최초손절가)
            risk   = avg_buy - initial_stop if initial_stop > 0 else 0
            reward = sell_price - avg_buy
            rr     = round(reward / risk, 2) if risk > 0 else None

            # 보유일수: 최초 매수일 → 매도일
            try:
                entry_dt  = datetime.strptime(buys[0]["date"], "%Y-%m-%d")
                sell_dt   = datetime.strptime(sell["date"],    "%Y-%m-%d")
                hold_days = (sell_dt - entry_dt).days
            except Exception:
                hold_days = None

            # 목표손절률: (최초손절가 - 평균매수가) / 평균매수가 * 100
            target_stop_pct = round((initial_stop - avg_buy) / avg_buy * 100, 2) if avg_buy > 0 and initial_stop > 0 else None

            rows.append({
                "날짜":         sell["date"],
                "종목명":       pos["name"],
                "종목코드":     pos["ticker"],
                "구분":         "부분청산" if pos["status"] == "open" else "전체청산",
                "매도가":       round(sell_price, 2),
                "평균매수가":   round(avg_buy, 2),
                "최초손절가":   round(initial_stop, 2),
                "수량":         sell_qty,
                "보유일수":     hold_days,
                "실현손익(원)": round(pnl_amt),
                "거래비용(원)": round(fees),
                "비용차감손익(원)": round(net_pnl),
                "수익률(%)":    round(pnl_pct, 2),
                "비용차감수익률(%)": round(net_pct, 2),
                "목표손절률(%)": target_stop_pct,
                "RR":           rr,
                "사유":         sell.get("reason", ""),
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("날짜", ascending=False).reset_index(drop=True)
    return df


def get_position_pnl() -> pd.DataFrame:
    """
    종목(포지션)별 실현손익 집계.
    매도가 발생한 포지션만 포함 (부분청산 포함).
    """
    data = _load()
    rows = []

    for pos in data["positions"]:
        if pos["status"] != "closed":
            continue
        buys  = [t for t in pos["trades"] if t["type"] == "buy"]
        sells = [t for t in pos["trades"] if t["type"] == "sell"]
        if not sells:
            continue

        # 최초 손절가
        history = pos.get("stop_loss_history", [])
        first_h = next((h for h in history if h.get("price", 0) > 0), None)
        initial_stop = first_h["price"] if first_h else (buys[0].get("stop_loss", 0) if buys else 0)

        # FIFO로 전체 매도에 대한 평균매수가 계산
        buy_queue = [[t["price"], t["quantity"]] for t in buys]
        total_sell_qty = sum(t["quantity"] for t in sells)
        total_sell_rev = sum(t["price"] * t["quantity"] for t in sells)
        total_cost = 0.0
        remaining  = total_sell_qty

        for b in buy_queue:
            if remaining <= 0:
                break
            used = min(b[1], remaining)
            total_cost += b[0] * used
            b[1]       -= used
            remaining  -= used

        avg_buy  = total_cost / total_sell_qty if total_sell_qty > 0 else 0
        avg_sell = total_sell_rev / total_sell_qty if total_sell_qty > 0 else 0
        pnl_amt  = total_sell_rev - total_cost
        pnl_pct  = (pnl_amt / total_cost * 100) if total_cost > 0 else 0
        fees     = _calc_fees(total_cost, total_sell_rev)
        net_pnl  = pnl_amt - fees
        net_pct  = net_pnl / total_cost * 100 if total_cost > 0 else 0

        # RR: (avg_sell - avg_buy) / (avg_buy - initial_stop)
        risk   = avg_buy - initial_stop if initial_stop > 0 else 0
        reward = avg_sell - avg_buy
        rr     = round(reward / risk, 2) if risk > 0 else None

        # 보유일수: 최초매수 → 마지막매도
        try:
            entry_dt  = datetime.strptime(buys[0]["date"], "%Y-%m-%d")
            last_sell = datetime.strptime(sells[-1]["date"], "%Y-%m-%d")
            hold_days = (last_sell - entry_dt).days
        except Exception:
            hold_days = None

        target_stop_pct = round((initial_stop - avg_buy) / avg_buy * 100, 2) if avg_buy > 0 and initial_stop > 0 else None

        rows.append({
            "종목코드":     pos["ticker"],
            "종목명":       pos["name"],
            "진입근거":     buys[0].get("entry_reason", "") if buys else "",
            "매수일":       buys[0]["date"] if buys else "",
            "청산일":       sells[-1]["date"],
            "보유일수":     hold_days,
            "평균매수가":   round(avg_buy, 2),
            "평균매도가":   round(avg_sell, 2),
            "청산수량":     total_sell_qty,
            "최초손절가":   round(initial_stop, 2),
            "실현손익(원)": round(pnl_amt, 2),
            "거래비용(원)": round(fees, 2),
            "비용차감손익(원)": round(net_pnl, 2),
            "수익률(%)":    round(pnl_pct, 2),
            "비용차감수익률(%)": round(net_pct, 2),
            "목표손절률(%)": target_stop_pct,
            "RR":           rr,
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("청산일", ascending=False).reset_index(drop=True)


def get_trade_log() -> pd.DataFrame:
    data = _load()
    if not data["trade_log"]:
        return pd.DataFrame()
    df = pd.DataFrame(data["trade_log"])
    return df.sort_values("date", ascending=False).reset_index(drop=True)


def get_trades_by_ticker(ticker: str) -> list:
    """
    특정 종목의 매수/매도 내역을 리스트로 반환.
    차트 마커 표시용.
    반환: [{"type": "buy"|"sell", "date": str, "price": float,
            "quantity": int, "label": str}, ...]
    """
    data = _load()
    result = []
    for pos in data["positions"]:
        if pos["ticker"] != ticker:
            continue
        for t in pos["trades"]:
            if t["type"] == "buy":
                label = t.get("entry_reason", "") or t.get("memo", "") or "매수"
            else:
                label = t.get("reason", "") or "매도"
            result.append({
                "type":     t["type"],
                "date":     t["date"],
                "price":    t["price"],
                "quantity": t["quantity"],
                "label":    label,
            })
    result.sort(key=lambda x: x["date"])
    return result


def calculate_performance() -> dict:
    data   = _load()
    closed = [p for p in data["positions"] if p["status"] == "closed"]
    results = []

    for pos in closed:
        buys  = [t for t in pos["trades"] if t["type"] == "buy"]
        sells = [t for t in pos["trades"] if t["type"] == "sell"]
        if not buys or not sells:
            continue

        buy_cost = sum(t["price"] * t["quantity"] for t in buys)
        sell_rev = sum(t["price"] * t["quantity"] for t in sells)
        pnl_pct  = (sell_rev - buy_cost) / buy_cost * 100 if buy_cost > 0 else 0

        try:
            entry_dt = datetime.strptime(buys[0]["date"],   "%Y-%m-%d")
            exit_dt  = datetime.strptime(sells[-1]["date"], "%Y-%m-%d")
            holding  = (exit_dt - entry_dt).days
        except Exception:
            holding = 0

        results.append({
            "ticker":         pos["ticker"],
            "name":           pos["name"],
            "entry_reason":   buys[0].get("entry_reason", "기타"),
            "pnl_pct":        pnl_pct,
            "total_buy_cost": buy_cost,
            "holding_days":   holding,
        })

    return _calc_stats(results)


def _calc_stats(results: list) -> dict:
    def stats_for(subset):
        if not subset:
            return None
        wins   = [r for r in subset if r["pnl_pct"] > 0]
        losses = [r for r in subset if r["pnl_pct"] <= 0]
        n      = len(subset)
        avg_win  = sum(r["pnl_pct"] for r in wins)   / len(wins)   if wins   else 0
        avg_loss = sum(r["pnl_pct"] for r in losses) / len(losses) if losses else 0
        avg_ret  = sum(r["pnl_pct"] for r in subset) / n
        total_inv = sum(r["total_buy_cost"] for r in subset)
        base_inv  = results[0]["total_buy_cost"] if results else 1
        turnover  = total_inv / base_inv if base_inv > 0 else 0
        return {
            "총거래수":             n,
            "승률(%)":              round(len(wins) / n * 100, 1),
            "승리 평균수익률(%)":   round(avg_win,    2),
            "패배 평균손실률(%)":   round(avg_loss,   2),
            "전체 평균수익률(%)":   round(avg_ret,    2),
            "자산회전율":           round(turnover,   2),
            "회전율 조정수익률(%)": round(avg_ret * turnover, 2),
        }

    overall   = stats_for(results)
    by_reason = {}
    for prefix in ["PB", "HB", "BO"]:
        s = stats_for([r for r in results if r["entry_reason"].startswith(prefix)])
        if s:
            by_reason[prefix] = s

    return {"전체": overall, "진입근거별": by_reason}


def get_equity_curve() -> pd.DataFrame:
    """날짜별 누적 실현손익 (당일 합산, 첫 거래월 1일부터 시작)"""
    df = get_realized_pnl()
    if df.empty:
        return pd.DataFrame(columns=["날짜", "누적손익(원)"])
    df = df[["날짜", "실현손익(원)"]].copy()
    df = df.groupby("날짜", as_index=False)["실현손익(원)"].sum()
    df = df.sort_values("날짜").reset_index(drop=True)
    df["누적손익(원)"] = df["실현손익(원)"].cumsum()

    # 시작점: 첫 거래월 1일, 누적손익 0
    first_dt   = pd.to_datetime(df["날짜"].iloc[0])
    start_date = first_dt.replace(day=1).strftime("%Y-%m-%d")
    start_row  = pd.DataFrame([{"날짜": start_date, "누적손익(원)": 0}])
    df = pd.concat([start_row, df[["날짜", "누적손익(원)"]]], ignore_index=True)
    return df


def get_monthly_performance() -> pd.DataFrame:
    """월별 성과 집계 (누적손익 컬럼 포함)"""
    df = get_realized_pnl()
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["월"] = pd.to_datetime(df["날짜"]).dt.to_period("M").astype(str)

    rows = []
    for month, grp in df.groupby("월"):
        n    = len(grp)
        wins = (grp["수익률(%)"] > 0).sum()
        rows.append({
            "월":            month,
            "거래수":        n,
            "승률(%)":       round(wins / n * 100, 1),
            "평균수익률(%)":  round(grp["수익률(%)"].mean(), 2),
            "총실현손익(원)": int(grp["실현손익(원)"].sum()),
        })

    result = pd.DataFrame(rows).sort_values("월").reset_index(drop=True)

    # 해당 연도 1월부터 빈 월 채우기
    if not result.empty:
        first_year = result["월"].iloc[0][:4]
        last_month = result["월"].iloc[-1]
        all_months = pd.period_range(f"{first_year}-01", last_month, freq="M").astype(str)
        result = (
            pd.DataFrame({"월": all_months})
            .merge(result, on="월", how="left")
            .fillna({"거래수": 0, "총실현손익(원)": 0})
        )
        result["누적손익(원)"] = result["총실현손익(원)"].cumsum().astype(int)

    return result.sort_values("월", ascending=False).reset_index(drop=True)
