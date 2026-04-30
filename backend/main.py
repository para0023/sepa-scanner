"""
SEPA Scanner — FastAPI Backend
기존 파이썬 모듈(portfolio.py, relative_strength.py 등)을 API로 래핑
"""
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가 (기존 모듈 import용)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import chart, scanner, dashboard, portfolio_api, journal, market, watchlist

app = FastAPI(
    title="SEPA Scanner API",
    version="1.0.0",
    docs_url="/docs",
)

# CORS — React 개발 서버(3000)에서 접근 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(chart.router, prefix="/api")
app.include_router(scanner.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(portfolio_api.router, prefix="/api")
app.include_router(journal.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# ── 종목 검색 (종목명/코드 자동완성) ──────────────────
_stock_cache = {"data": None}

def _load_stock_list():
    if _stock_cache["data"] is not None:
        return _stock_cache["data"]
    import FinanceDataReader as fdr
    items = []
    try:
        krx = fdr.StockListing("KRX")[["Code", "Name", "Market"]].dropna()
        for _, row in krx.iterrows():
            items.append({"code": row["Code"], "name": row["Name"], "market": row["Market"]})
    except Exception:
        pass
    try:
        for listing in ["NASDAQ", "NYSE"]:
            us = fdr.StockListing(listing)[["Symbol", "Name"]].dropna()
            for _, row in us.iterrows():
                items.append({"code": row["Symbol"], "name": row["Name"], "market": listing})
    except Exception:
        pass
    _stock_cache["data"] = items
    return items


@app.get("/api/stocks/search")
def search_stocks(q: str = "", limit: int = 20):
    """종목명 또는 코드로 검색"""
    if not q or len(q) < 1:
        return []
    items = _load_stock_list()
    q_upper = q.upper()
    q_lower = q.lower()
    # 1순위: 코드 정확 매칭
    exact = [item for item in items if item["code"].upper() == q_upper]
    # 2순위: 코드 시작 매칭
    starts = [item for item in items if item["code"].upper().startswith(q_upper) and item not in exact]
    # 3순위: 이름/코드 부분 매칭
    partial = [item for item in items if (q_upper in item["code"].upper() or q_lower in item["name"].lower()) and item not in exact and item not in starts]
    results = (exact + starts + partial)[:limit]
    return results
