"""
/api/market/* — 시장 지표 API
"""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/indicators")
def get_market_indicators(days: int = Query(90, ge=30, le=365)):
    """모든 시장 지표 한 번에 조회"""
    import FinanceDataReader as fdr
    import pandas as pd
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor

    end = datetime.now()
    start = end - timedelta(days=days)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    codes = {
        "코스피": "KS11", "코스닥": "KQ11",
        "S&P500": "^GSPC", "나스닥": "^IXIC",
        "USD/KRW": "USD/KRW", "DXY": "DX-Y.NYB",
        "US10Y": "^TNX", "US2Y": "2YY=F", "VIX": "^VIX",
        "WTI": "CL=F", "Gold": "GC=F", "Silver": "SI=F",
        "Copper": "HG=F", "NatGas": "NG=F",
    }

    def _fetch_one(item):
        label, code = item
        try:
            df = fdr.DataReader(code, s, e)
            if df is not None and len(df) > 0:
                df = df[["Close"]].dropna()
                dates = [d.strftime("%Y-%m-%d") for d in df.index]
                values = [round(float(v), 4) for v in df["Close"]]
                return label, {"dates": dates, "values": values}
        except Exception:
            pass
        return label, None

    result = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for label, data in pool.map(_fetch_one, codes.items()):
            if data:
                result[label] = data

    # ECOS API (한국 금리, 외국인 수급)
    import os, json
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
    ecos_key = os.getenv("ECOS_API_KEY", "")

    if ecos_key:
        ecos_start = start.strftime("%Y%m%d")
        ecos_end = end.strftime("%Y%m%d")

        ecos_items = {
            "KR10Y": ("817Y002", "010210000", "D", ecos_start, ecos_end),
            "KR2Y": ("817Y002", "010195000", "D", ecos_start, ecos_end),
            "외국인(유가)": ("802Y001", "0030000", "D", ecos_start, ecos_end),
            "외국인(코스닥)": ("802Y001", "0113000", "D", ecos_start, ecos_end),
        }

        def _fetch_ecos(label, stat_code, item_code, cycle, s_date, e_date):
            import urllib.request
            try:
                url = f"https://ecos.bok.or.kr/api/StatisticSearch/{ecos_key}/json/kr/1/1000/{stat_code}/{cycle}/{s_date}/{e_date}/{item_code}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                rows = data.get("StatisticSearch", {}).get("row", [])
                if not rows:
                    return label, None
                dates = [r["TIME"] for r in rows]
                # 날짜 포맷 통일
                fmt_dates = []
                for d in dates:
                    if len(d) == 8:
                        fmt_dates.append(f"{d[:4]}-{d[4:6]}-{d[6:]}")
                    elif len(d) == 6:
                        fmt_dates.append(f"{d[:4]}-{d[4:]}-01")
                    else:
                        fmt_dates.append(d)
                values = [float(r["DATA_VALUE"]) for r in rows]
                return label, {"dates": fmt_dates, "values": values}
            except Exception:
                return label, None

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_fetch_ecos, label, *args) for label, args in ecos_items.items()]
            for f in futures:
                label, data = f.result()
                if data:
                    result[label] = data

        # 외국인 누적
        for key in ["외국인(유가)", "외국인(코스닥)"]:
            if key in result:
                vals = result[key]["values"]
                cum = []
                s_val = 0
                for v in vals:
                    s_val += v
                    cum.append(round(s_val, 0))
                result[f"{key}_cum"] = {"dates": result[key]["dates"], "values": cum}

    # 장단기 금리차
    for prefix, k10, k2 in [("KR", "KR10Y", "KR2Y"), ("US", "US10Y", "US2Y")]:
        d10 = result.get(k10)
        d2 = result.get(k2)
        if d10 and d2:
            # 날짜 교집합
            date_set = set(d10["dates"]) & set(d2["dates"])
            if date_set:
                map10 = dict(zip(d10["dates"], d10["values"]))
                map2 = dict(zip(d2["dates"], d2["values"]))
                common = sorted(date_set)
                result[f"{prefix}_spread"] = {
                    "dates": common,
                    "values": [round(map10[d] - map2[d], 4) for d in common],
                }

    return {"days": days, "data": result}
