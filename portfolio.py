"""
SEPA Scanner - 포트폴리오 관리 모듈
- 로컬 모드: JSON 파일 기반 (기존 방식)
- 클라우드 모드: Supabase DB 기반 (사용자별 분리)
"""
import json
import os
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

# ─────────────────────────────────────────────
# 모드 판별 + Supabase 헬퍼
# ─────────────────────────────────────────────
_CURRENT_MARKET = "KR"  # set_portfolio_file 에서 갱신


def _is_cloud() -> bool:
    """Supabase 클라우드 모드 여부"""
    env_val = os.environ.get("SEPA_LOCAL")
    if env_val is not None:
        return env_val != "1"
    try:
        import streamlit as st
        return st.secrets.get("app", {}).get("SEPA_LOCAL", "1") != "1"
    except Exception:
        return False


def _get_user_id() -> str:
    """현재 로그인 사용자 ID (클라우드 전용)"""
    try:
        import streamlit as st
        return st.session_state.get("user_id", "")
    except Exception:
        return ""


def _get_supabase():
    """Supabase 클라이언트 반환"""
    try:
        import streamlit as st
        return st.session_state.get("supabase_client")
    except Exception:
        return None


def set_portfolio_file(path: str):
    """포트폴리오 파일 경로 전환 (한국/미국 탭 전환용)"""
    global PORTFOLIO_FILE, _CURRENT_MARKET
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / path
    PORTFOLIO_FILE = p
    _CURRENT_MARKET = "US" if "us" in p.stem.lower() else "KR"


def _is_kr() -> bool:
    """현재 포트폴리오가 한국(KR) 시장인지 여부"""
    if _is_cloud():
        return _CURRENT_MARKET == "KR"
    return "us" not in PORTFOLIO_FILE.stem.lower()


def _calc_fees(buy_amount: float, sell_amount: float) -> float:
    """매수/매도 금액 기준 거래비용 합계 (수수료 + 세금)"""
    if _is_kr():
        return buy_amount * _FEE_KR + sell_amount * (_FEE_KR + _TAX_KR)
    else:
        return (buy_amount + sell_amount) * _FEE_US


# ─────────────────────────────────────────────
# 내부 유틸 — 데이터 로드/저장
# ─────────────────────────────────────────────

def _load() -> dict:
    """데이터 로드 (로컬: JSON, 클라우드: Supabase)"""
    if _is_cloud():
        return _load_supabase()
    # 로컬 모드: 기존 JSON
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
    """데이터 저장 (로컬: JSON, 클라우드: Supabase)"""
    if _is_cloud():
        _save_supabase(data)
        return
    # 로컬 모드: 기존 JSON
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# Supabase CRUD (클라우드 모드)
# ─────────────────────────────────────────────

def _load_supabase() -> dict:
    """Supabase에서 현재 사용자의 포트폴리오 데이터 로드"""
    sb = _get_supabase()
    uid = _get_user_id()
    market = _CURRENT_MARKET
    if not sb or not uid:
        return {"positions": [], "trade_log": []}

    try:
        # positions
        pos_res = sb.table("positions").select("*").eq("user_id", uid).eq("market", market).execute()
        positions = []
        for row in (pos_res.data or []):
            positions.append({
                "id": row["id"],
                "ticker": row["ticker"],
                "name": row["name"],
                "status": row["status"],
                "trades": row.get("trades", []),
                "stop_loss_history": row.get("stop_loss_history", []),
            })

        # trade_log
        log_res = sb.table("trade_log").select("*").eq("user_id", uid).eq("market", market).execute()
        trade_log = []
        for row in (log_res.data or []):
            trade_log.append({
                "date": row["date"],
                "ticker": row["ticker"],
                "name": row["name"],
                "type": row["type"],
                "price": float(row["price"]),
                "quantity": int(row["quantity"]),
                "entry_reason": row.get("entry_reason", ""),
                "reason": row.get("reason", ""),
                "memo": row.get("memo", ""),
                "position_id": row.get("position_id", ""),
                "trade_id": row.get("id", ""),
            })

        # capital_flows
        cf_res = sb.table("capital_flows").select("*").eq("user_id", uid).eq("market", market).execute()
        capital_flows = []
        for row in (cf_res.data or []):
            capital_flows.append({
                "id": row["id"],
                "date": row["date"],
                "amount": float(row["amount"]),
                "note": row.get("memo", ""),
            })

        return {
            "positions": positions,
            "trade_log": trade_log,
            "capital_flows": capital_flows,
        }
    except Exception as e:
        print(f"[Supabase 로드 실패] {e}")
        return {"positions": [], "trade_log": []}


def _save_supabase(data: dict):
    """Supabase에 현재 사용자의 포트폴리오 데이터 저장 (전체 동기화)"""
    sb = _get_supabase()
    uid = _get_user_id()
    market = _CURRENT_MARKET
    if not sb or not uid:
        return

    try:
        # positions: 기존 삭제 후 전체 재삽입
        sb.table("positions").delete().eq("user_id", uid).eq("market", market).execute()
        for pos in data.get("positions", []):
            sb.table("positions").insert({
                "id": pos["id"],
                "user_id": uid,
                "market": market,
                "ticker": pos["ticker"],
                "name": pos["name"],
                "status": pos["status"],
                "trades": pos.get("trades", []),
                "stop_loss_history": pos.get("stop_loss_history", []),
            }).execute()

        # trade_log: 기존 삭제 후 전체 재삽입
        sb.table("trade_log").delete().eq("user_id", uid).eq("market", market).execute()
        for log in data.get("trade_log", []):
            sb.table("trade_log").insert({
                "user_id": uid,
                "market": market,
                "position_id": log.get("position_id"),
                "ticker": log.get("ticker", ""),
                "name": log.get("name", ""),
                "type": log.get("type", ""),
                "date": log.get("date", ""),
                "price": log.get("price", 0),
                "quantity": log.get("quantity", 0),
                "stop_loss": log.get("stop_loss"),
                "take_profit": log.get("take_profit"),
                "entry_reason": log.get("entry_reason", ""),
                "reason": log.get("reason", ""),
                "memo": log.get("memo", ""),
            }).execute()

        # capital_flows: 기존 삭제 후 전체 재삽입
        sb.table("capital_flows").delete().eq("user_id", uid).eq("market", market).execute()
        for cf in data.get("capital_flows", []):
            sb.table("capital_flows").insert({
                "id": cf.get("id", str(uuid.uuid4())),
                "user_id": uid,
                "market": market,
                "date": cf["date"],
                "amount": cf["amount"],
                "memo": cf.get("note", ""),
            }).execute()

    except Exception as e:
        print(f"[Supabase 저장 실패] {e}")


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
    take_profit: float = 0,
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

    trade = {
        "id":           str(uuid.uuid4()),
        "type":         "buy",
        "date":         date,
        "price":        price,
        "quantity":     quantity,
        "stop_loss":    stop_loss,
        "entry_reason": entry_reason,
        "memo":         memo,
    }
    if take_profit and take_profit > 0:
        trade["take_profit"] = take_profit
    pos["trades"].append(trade)

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


def update_take_profit(position_id: str, price: float) -> bool:
    """1차 익절가 수동 수정. 마지막 매수 거래의 take_profit을 업데이트."""
    data = _load()
    pos  = next((p for p in data["positions"] if p["id"] == position_id), None)
    if pos is None:
        return False
    buy_trades = [t for t in pos["trades"] if t["type"] == "buy"]
    if not buy_trades:
        return False
    buy_trades[-1]["take_profit"] = price
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

        # 1차 익절가: 마지막 매수의 take_profit
        take_profit = 0
        if buy_trades:
            take_profit = buy_trades[-1].get("take_profit", 0)

        rows.append({
            "position_id": pos["id"],
            "종목코드":    pos["ticker"],
            "종목명":      pos["name"],
            "매수일":      entry_date,
            "경과일":      days,
            "평균매수가":  round(avg, 2),
            "수량":        qty,
            "손절가":      stop_loss,
            "1차익절가":   take_profit,
            "진입근거":    entry_reason,
            "메모":        memo,
        })

    cols = ["position_id", "종목코드", "종목명", "매수일", "경과일",
            "평균매수가", "수량", "손절가", "1차익절가", "진입근거", "메모"]
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

            # 진입근거
            entry_reason = buys[0].get("entry_reason", "") if buys else ""

            rows.append({
                "날짜":         sell["date"],
                "종목명":       pos["name"],
                "종목코드":     pos["ticker"],
                "진입근거":     entry_reason,
                "구분":         "부분청산" if pos["status"] == "open" else "전체청산",
                "매도가":       round(sell_price, 2),
                "평균매수가":   round(avg_buy, 2),
                "최초손절가":   round(initial_stop, 2),
                "수량":         sell_qty,
                "보유일수":     hold_days,
                "수익률(%)":    round(pnl_pct, 2),
                "실현손익(원)": round(pnl_amt),
                "거래비용(원)": round(fees),
                "비용차감수익률(%)": round(net_pct, 2),
                "비용차감손익(원)": round(net_pnl),
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
            "수익률(%)":    round(pnl_pct, 2),
            "실현손익(원)": round(pnl_amt, 2),
            "거래비용(원)": round(fees, 2),
            "비용차감수익률(%)": round(net_pct, 2),
            "비용차감손익(원)": round(net_pnl, 2),
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
            "quantity": int, "label": str, "position_status": str}, ...]
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
                "position_status": pos["status"],
                "stop_loss": t.get("stop_loss", 0),
                "take_profit": t.get("take_profit", 0),
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
    capital = get_total_capital()

    def stats_for(subset):
        if not subset:
            return None
        wins   = [r for r in subset if r["pnl_pct"] > 0]
        losses = [r for r in subset if r["pnl_pct"] <= 0]
        n      = len(subset)
        total_inv = sum(r["total_buy_cost"] for r in subset)

        # 금액 가중 평균수익률
        if total_inv > 0:
            avg_win  = sum(r["pnl_pct"] * r["total_buy_cost"] for r in wins)   / sum(r["total_buy_cost"] for r in wins)   if wins   else 0
            avg_loss = sum(r["pnl_pct"] * r["total_buy_cost"] for r in losses) / sum(r["total_buy_cost"] for r in losses) if losses else 0
            avg_ret  = sum(r["pnl_pct"] * r["total_buy_cost"] for r in subset) / total_inv
        else:
            avg_win = avg_loss = avg_ret = 0

        # 단순 평균 (참고용)
        simple_avg_ret = sum(r["pnl_pct"] for r in subset) / n if n else 0

        # 총 실현손익
        total_pnl = sum(r["total_buy_cost"] * r["pnl_pct"] / 100 for r in subset)

        # 회전율: 총 매수금액 / 투입 자본
        turnover = total_inv / capital if capital > 0 else None

        # 원금 대비 실현수익률
        capital_ret = (total_pnl / capital * 100) if capital > 0 else None

        return {
            "총거래수":             n,
            "승률(%)":              round(len(wins) / n * 100, 1),
            "승리 평균수익률(%)":   round(avg_win,    2),
            "패배 평균손실률(%)":   round(avg_loss,   2),
            "전체 평균수익률(%)":   round(avg_ret,    2),
            "단순 평균수익률(%)":   round(simple_avg_ret, 2),
            "자산회전율":           round(turnover,   2) if turnover is not None else None,
            "회전율 조정수익률(%)": round(avg_ret * turnover, 2) if turnover is not None else None,
            "총실현손익(원)":       int(total_pnl),
            "원금대비수익률(%)":    round(capital_ret, 2) if capital_ret is not None else None,
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


def _get_closed_positions_detail() -> pd.DataFrame:
    """종목별 완전청산 기준 실현손익 (비용차감 포함)"""
    data = _load()
    rows = []

    for pos in data["positions"]:
        if pos["status"] != "closed":
            continue
        buys = [t for t in pos["trades"] if t["type"] == "buy"]
        sells = [t for t in pos["trades"] if t["type"] == "sell"]
        if not buys or not sells:
            continue

        buy_cost = sum(t["price"] * t["quantity"] for t in buys)
        buy_qty = sum(t["quantity"] for t in buys)
        sell_rev = sum(t["price"] * t["quantity"] for t in sells)
        avg_buy = buy_cost / buy_qty if buy_qty > 0 else 0

        pnl_amt = sell_rev - buy_cost
        fees = _calc_fees(buy_cost, sell_rev)
        net_pnl = pnl_amt - fees
        net_pct = net_pnl / buy_cost * 100 if buy_cost > 0 else 0

        # 최초 손절가
        history = pos.get("stop_loss_history", [])
        first_h = next((h for h in history if h.get("price", 0) > 0), None)
        initial_stop = first_h["price"] if first_h else (buys[0].get("stop_loss", 0) if buys else 0)

        # RR
        risk = avg_buy - initial_stop if initial_stop > 0 else 0
        avg_sell = sell_rev / sum(t["quantity"] for t in sells) if sells else 0
        reward = avg_sell - avg_buy
        rr = round(reward / risk, 2) if risk > 0 else None

        try:
            entry_dt = datetime.strptime(buys[0]["date"], "%Y-%m-%d")
            exit_dt = datetime.strptime(sells[-1]["date"], "%Y-%m-%d")
            hold_days = (exit_dt - entry_dt).days
        except Exception:
            hold_days = None

        entry_reason = buys[0].get("entry_reason", "") if buys else ""

        rows.append({
            "청산일": sells[-1]["date"],
            "종목명": pos["name"],
            "종목코드": pos["ticker"],
            "진입근거": entry_reason,
            "매수금액": round(buy_cost),
            "매도금액": round(sell_rev),
            "실현손익(원)": round(pnl_amt),
            "거래비용(원)": round(fees),
            "비용차감손익(원)": round(net_pnl),
            "수익률(%)": round(net_pct, 2),
            "보유일수": hold_days,
            "RR": rr,
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("청산일", ascending=False).reset_index(drop=True)


def get_monthly_review(month: str = None) -> dict:
    """
    월별 성과 리뷰 리포트 (종목별 완전청산 기준).
    month: "2026-03" 형식. None이면 최근 월.
    """
    df = _get_closed_positions_detail()
    if df.empty:
        return {}
    df = df.copy()
    df["월"] = pd.to_datetime(df["청산일"]).dt.to_period("M").astype(str)

    if month is None:
        month = df["월"].max()

    mdf = df[df["월"] == month]
    if mdf.empty:
        return {"month": month, "summary": None, "by_reason": {}, "trades": pd.DataFrame()}

    def _calc_summary(data):
        n = len(data)
        wins = data[data["수익률(%)"] > 0]
        losses = data[data["수익률(%)"] <= 0]
        return {
            "거래수": n,
            "승률(%)": round(len(wins) / n * 100, 1) if n > 0 else 0,
            "평균수익률(%)": round(data["수익률(%)"].mean(), 2),
            "평균보유일수": round(data["보유일수"].dropna().mean(), 1) if data["보유일수"].dropna().any() else 0,
            "승리 평균(%)": round(wins["수익률(%)"].mean(), 2) if len(wins) > 0 else 0,
            "패배 평균(%)": round(losses["수익률(%)"].mean(), 2) if len(losses) > 0 else 0,
            "최대수익(%)": round(data["수익률(%)"].max(), 2),
            "최대손실(%)": round(data["수익률(%)"].min(), 2),
            "총실현손익(원)": int(data["비용차감손익(원)"].sum()),
            "거래비용(원)": int(data["거래비용(원)"].sum()),
            "평균RR": round(data["RR"].dropna().mean(), 2) if data["RR"].dropna().any() else None,
        }

    summary = _calc_summary(mdf)

    # 진입근거별 분석
    by_reason = {}
    if "진입근거" in mdf.columns:
        for reason, grp in mdf.groupby("진입근거"):
            if not reason:
                continue
            by_reason[reason] = _calc_summary(grp)

    return {
        "month": month,
        "summary": summary,
        "by_reason": by_reason,
        "trades": mdf.reset_index(drop=True),
    }


def get_available_weeks() -> list:
    """거래가 있는 주간 목록 반환 (월요일 날짜 리스트, 내림차순)"""
    data = _load()
    dates = set()
    for pos in data["positions"]:
        for t in pos["trades"]:
            dates.add(t["date"])
    if not dates:
        return []
    # 각 날짜의 해당 주 월요일 계산
    weeks = set()
    for d in dates:
        dt = pd.to_datetime(d)
        monday = dt - pd.Timedelta(days=dt.weekday())
        weeks.add(monday.strftime("%Y-%m-%d"))
    return sorted(weeks, reverse=True)


def get_weekly_review(week_start: str = None) -> dict:
    """
    주간 리뷰 데이터 반환.
    week_start: "2026-04-14" (월요일). None이면 최근 주.
    """
    data = _load()
    if not data["positions"]:
        return {}

    # 주간 범위 설정
    if week_start is None:
        weeks = get_available_weeks()
        if not weeks:
            return {}
        week_start = weeks[0]

    ws = pd.to_datetime(week_start)
    we = ws + pd.Timedelta(days=6)  # 일요일
    ws_str = ws.strftime("%Y-%m-%d")
    we_str = we.strftime("%Y-%m-%d")

    # 주간 진입/청산 분류
    entries = []   # 진입만
    exits = []     # 청산만
    both = []      # 진입+청산

    for pos in data["positions"]:
        ticker = pos["ticker"]
        name = pos["name"]

        week_buys = [t for t in pos["trades"] if t["type"] == "buy" and ws_str <= t["date"] <= we_str]
        week_sells = [t for t in pos["trades"] if t["type"] == "sell" and ws_str <= t["date"] <= we_str]

        if not week_buys and not week_sells:
            continue

        entry_info = {
            "종목코드": ticker,
            "종목명": name,
            "매수": [{
                "날짜": b["date"],
                "가격": b["price"],
                "수량": b["quantity"],
                "진입근거": b.get("entry_reason", ""),
                "손절가": b.get("stop_loss", 0),
            } for b in week_buys],
            "매도": [{
                "날짜": s["date"],
                "가격": s["price"],
                "수량": s["quantity"],
                "사유": s.get("reason", ""),
            } for s in week_sells],
        }

        if week_buys and not week_sells:
            entries.append(entry_info)
        elif week_sells and not week_buys:
            exits.append(entry_info)
        else:
            both.append(entry_info)

    # 주간 거래 요약 (청산 건 기준)
    df_pnl = get_realized_pnl()
    summary = None
    weekly_pnl_df = pd.DataFrame()
    if not df_pnl.empty:
        df_pnl["_date"] = pd.to_datetime(df_pnl["날짜"])
        weekly_pnl_df = df_pnl[(df_pnl["_date"] >= ws) & (df_pnl["_date"] <= we)].copy()

        if not weekly_pnl_df.empty:
            n = len(weekly_pnl_df)
            wins = weekly_pnl_df[weekly_pnl_df["수익률(%)"] > 0]
            losses = weekly_pnl_df[weekly_pnl_df["수익률(%)"] <= 0]

            # 실현손익 컬럼명 (원 또는 $)
            _pnl_col = [c for c in weekly_pnl_df.columns if "비용차감손익" in c]
            _pnl_col = _pnl_col[0] if _pnl_col else "실현손익(원)"
            weekly_realized = weekly_pnl_df[_pnl_col].sum() if _pnl_col in weekly_pnl_df.columns else 0

            summary = {
                "총거래수": n,
                "승": len(wins),
                "패": len(losses),
                "승률(%)": round(len(wins) / n * 100, 1) if n > 0 else 0,
                "승리평균수익률(%)": round(wins["수익률(%)"].mean(), 2) if len(wins) > 0 else 0,
                "패배평균손실률(%)": round(losses["수익률(%)"].mean(), 2) if len(losses) > 0 else 0,
                "주간실현수익": round(weekly_realized),
            }

    # 포트폴리오 평가금액 (주초/주말)
    capital = get_total_capital()
    import FinanceDataReader as _fdr

    def _eval_portfolio_at(eval_date_str: str) -> float:
        """특정 날짜 기준 보유종목 평가금액 (현금 + 보유주식 평가)"""
        eval_dt = pd.to_datetime(eval_date_str)
        total = capital  # 원금
        # 누적 실현손익 (해당 날짜까지)
        if not df_pnl.empty:
            _pnl_cols = [c for c in df_pnl.columns if "비용차감손익" in c]
            if _pnl_cols:
                _cum = df_pnl[df_pnl["_date"] <= eval_dt][_pnl_cols[0]].sum()
                total += _cum
        # 보유종목 평가손익 (해당 날짜 기준)
        for pos in data["positions"]:
            buys_before = [t for t in pos["trades"] if t["type"] == "buy" and t["date"] <= eval_date_str]
            sells_before = [t for t in pos["trades"] if t["type"] == "sell" and t["date"] <= eval_date_str]
            buy_qty = sum(t["quantity"] for t in buys_before)
            sell_qty = sum(t["quantity"] for t in sells_before)
            hold_qty = buy_qty - sell_qty
            if hold_qty <= 0:
                continue
            avg_buy = sum(t["price"] * t["quantity"] for t in buys_before) / buy_qty if buy_qty > 0 else 0
            # 해당 날짜 종가 조회
            try:
                _pdf = _fdr.DataReader(pos["ticker"], (eval_dt - pd.Timedelta(days=7)).strftime("%Y-%m-%d"), eval_date_str)
                if _pdf is not None and not _pdf.empty:
                    _close = float(_pdf["Close"].iloc[-1])
                    total += (_close - avg_buy) * hold_qty
            except:
                pass
        return total

    # 주초 = 월요일, 주말 = 금요일 (또는 전일)
    _fri = ws + pd.Timedelta(days=4)  # 금요일
    _prev_fri = ws - pd.Timedelta(days=3)  # 이전 주 금요일
    _fri_str = _fri.strftime("%Y-%m-%d")
    _prev_fri_str = _prev_fri.strftime("%Y-%m-%d")

    week_end_val = _eval_portfolio_at(_fri_str)
    week_start_val = _eval_portfolio_at(_prev_fri_str)
    weekly_return_pct = round((week_end_val / week_start_val - 1) * 100, 2) if week_start_val > 0 else 0

    return {
        "week_start": ws_str,
        "week_end": we_str,
        "week_start_val": round(week_start_val),
        "week_end_val": round(week_end_val),
        "weekly_return_pct": weekly_return_pct,
        "capital": capital,
        "summary": summary,
        "entries": entries,
        "exits": exits,
        "both": both,
        "trades_df": weekly_pnl_df,
    }
