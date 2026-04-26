"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import DataTable from "@/components/tables/DataTable";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

// ── 시장순위 컬럼 ──
const LISTING_COLUMNS = [
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "현재가", label: "현재가", align: "right" as const, format: "price" as const },
  { key: "전일대비", label: "전일대비", align: "right" as const, format: "price" as const },
  { key: "등락률(%)", label: "등락률(%)", align: "right" as const, format: "percent" as const },
  { key: "거래량", label: "거래량", align: "right" as const, format: "price" as const },
  { key: "시가총액(억)", label: "시총(억)", align: "right" as const, format: "price" as const },
];

// ── 52주 신고가 컬럼 ──
const HIGH_COLUMNS = [
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "현재가", label: "현재가", align: "right" as const, format: "price" as const },
  { key: "52주고가", label: "52주고가", align: "right" as const, format: "price" as const },
  { key: "고가대비(%)", label: "고가대비(%)", align: "right" as const, format: "percent" as const },
  { key: "등락률(%)", label: "등락률(%)", align: "right" as const, format: "percent" as const },
  { key: "시가총액(억)", label: "시총(억)", align: "right" as const, format: "price" as const },
];

const SORT_OPTIONS = [
  { value: "marcap", label: "시가총액" },
  { value: "change", label: "등락률" },
  { value: "volume", label: "거래량" },
];

export default function UniversePage() {
  const [tab, setTab] = useState<"listing" | "high">("listing");
  const [market, setMarket] = useState("KOSPI");

  // ── 시장순위 상태 ──
  const [sortBy, setSortBy] = useState("marcap");
  const [topN, setTopN] = useState(100);
  const [listingData, setListingData] = useState<any>(null);
  const [listingLoading, setListingLoading] = useState(false);

  // ── 52주 신고가 상태 ──
  const [highData, setHighData] = useState<Record<string, any>>({});
  const [highLoading, setHighLoading] = useState<Record<string, boolean>>({});

  // 시장순위 로드
  useEffect(() => {
    if (tab !== "listing") return;
    setListingLoading(true);
    fetchApi(`/scanner/universe/${market}/listing?sort_by=${sortBy}&top_n=${topN}`)
      .then(setListingData)
      .catch(() => setListingData(null))
      .finally(() => setListingLoading(false));
  }, [market, sortBy, topN, tab]);

  // 52주 신고가 로드 (KOSPI + KOSDAQ 동시)
  const loadHigh = (force: boolean = false) => {
    ["KOSPI", "KOSDAQ"].forEach((m) => {
      setHighLoading((prev) => ({ ...prev, [m]: true }));
      fetchApi(`/scanner/universe/${m}?force=${force}`)
        .then((result) => setHighData((prev) => ({ ...prev, [m]: result })))
        .catch(() => setHighData((prev) => ({ ...prev, [m]: null })))
        .finally(() => setHighLoading((prev) => ({ ...prev, [m]: false })));
    });
  };

  useEffect(() => {
    if (tab === "high") loadHigh();
  }, [tab]);

  const anyHighLoading = highLoading["KOSPI"] || highLoading["KOSDAQ"];

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-4">기타순위목록</h1>

      {/* 탭 */}
      <div className="flex gap-1 mb-4">
        <button onClick={() => setTab("listing")}
          className={`px-4 py-1.5 rounded text-sm ${tab === "listing" ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
          시장순위
        </button>
        <button onClick={() => setTab("high")}
          className={`px-4 py-1.5 rounded text-sm ${tab === "high" ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
          52주 신고가
        </button>
      </div>

      {/* ═══ 시장순위 탭 ═══ */}
      {tab === "listing" && (
        <div>
          <div className="flex items-center gap-4 mb-4">
            {/* 시장 선택 */}
            <div className="flex gap-1">
              {["KOSPI", "KOSDAQ"].map((m) => (
                <button key={m} onClick={() => setMarket(m)}
                  className={`px-3 py-1 rounded text-sm ${market === m ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
                  {m}
                </button>
              ))}
            </div>

            {/* 정렬 */}
            <div className="flex gap-1">
              {SORT_OPTIONS.map((opt) => (
                <button key={opt.value} onClick={() => setSortBy(opt.value)}
                  className={`px-3 py-1 rounded text-sm ${sortBy === opt.value ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
                  {opt.label}
                </button>
              ))}
            </div>

            {/* 표시 수 */}
            <div className="flex gap-1">
              {[50, 100, 200, 500].map((n) => (
                <button key={n} onClick={() => setTopN(n)}
                  className={`px-2 py-1 rounded text-xs ${topN === n ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
                  {n}
                </button>
              ))}
            </div>
          </div>

          {listingLoading && <LoadingSpinner text="시장 데이터 로딩 중" />}
          {!listingLoading && listingData && (
            <>
              <p className="text-xs text-gray-500 mb-2">{listingData.market} · {listingData.count}종목</p>
              <DataTable columns={LISTING_COLUMNS} data={listingData.data || []} tickerKey="종목코드" showRowNumber />
            </>
          )}
        </div>
      )}

      {/* ═══ 52주 신고가 탭 ═══ */}
      {tab === "high" && (
        <div>
          <div className="flex items-center gap-3 mb-4">
            <button onClick={() => loadHigh(true)}
              disabled={anyHighLoading}
              className="px-3 py-1 rounded text-sm bg-[#1f2937] text-gray-400 hover:text-white disabled:opacity-50">
              {anyHighLoading ? "스캔 중..." : "강제 재스캔"}
            </button>
          </div>

          {["KOSPI", "KOSDAQ"].map((m) => {
            const data = highData[m];
            const loading = highLoading[m];
            const rows = data?.data || [];

            const breakout = rows.filter((r: any) => r["고가대비(%)"] != null && r["고가대비(%)"] >= 0);
            const near = rows.filter((r: any) => r["고가대비(%)"] != null && r["고가대비(%)"] < 0 && r["고가대비(%)"] >= -10);

            return (
              <div key={m} className="mb-8">
                <h2 className="text-base font-bold text-white mb-3">{m}</h2>

                {loading && <p className="text-gray-500 py-4 text-center text-sm">{m} 스캔 중...</p>}

                {!loading && rows.length === 0 && (
                  <p className="text-xs text-gray-600 py-2">52주 신고가 근접 종목 없음</p>
                )}

                {!loading && rows.length > 0 && (
                  <div className="space-y-4">
                    {/* 신고가 돌파 */}
                    <div>
                      <p className="text-sm text-gray-400 mb-1 font-medium">신고가 돌파 ({breakout.length})</p>
                      {breakout.length > 0
                        ? <DataTable columns={HIGH_COLUMNS} data={breakout} tickerKey="종목코드" showRowNumber />
                        : <p className="text-xs text-gray-600 py-2">해당 종목 없음</p>}
                    </div>

                    {/* 신고가 근접 -10% 이내 */}
                    <div>
                      <p className="text-sm text-gray-400 mb-1 font-medium">신고가 근접 -10% 이내 ({near.length})</p>
                      {near.length > 0
                        ? <DataTable columns={HIGH_COLUMNS} data={near} tickerKey="종목코드" showRowNumber />
                        : <p className="text-xs text-gray-600 py-2">해당 종목 없음</p>}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
