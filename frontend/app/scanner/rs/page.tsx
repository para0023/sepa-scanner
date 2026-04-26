"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import DataTable from "@/components/tables/DataTable";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

const MARKETS_KR = ["KOSPI", "KOSDAQ"];
const MARKETS_US = ["NASDAQ", "NYSE"];
const PERIODS = [10, 20, 40, 60];

const COLUMNS = [
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "RS Score", label: "RS Score", align: "right" as const, format: "number" as const },
  { key: "종목수익률", label: "종목수익률", align: "right" as const, format: "percent" as const },
  { key: "현재가", label: "현재가", align: "right" as const, format: "price" as const },
  { key: "고가대비(%)", label: "전고점대비(종가)", align: "right" as const, format: "percent" as const },
  { key: "ATR(%)", label: "ATR(%)", align: "right" as const, format: "number" as const },
];

interface ScanResult {
  market: string;
  period: number;
  count: number;
  data: Record<string, any>[];
}

export default function RSScannerPage() {
  const [region, setRegion] = useState<"KR" | "US">("KR");
  const [market, setMarket] = useState("KOSPI");
  const [period, setPeriod] = useState(60);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(false);

  // VCP 필터
  const [vcpData, setVcpData] = useState<Record<string, any>[] | null>(null);
  const [vcpLoading, setVcpLoading] = useState(false);
  const [vcpOpen, setVcpOpen] = useState(false);

  const markets = region === "KR" ? MARKETS_KR : MARKETS_US;

  useEffect(() => {
    setMarket(markets[0]);
  }, [region]);

  useEffect(() => {
    setLoading(true);
    setVcpData(null);
    setVcpOpen(false);
    fetchApi<ScanResult>(`/scanner/rs/${market}?period=${period}&top_n=100`)
      .then((r) => {
        setResult(r);
        // RS 로드 후 VCP 캐시 자동 로드
        fetchApi<ScanResult>(`/scanner/rs/${market}/vcp?period=${period}`)
          .then((v) => { setVcpData(v.data); setVcpOpen(true); })
          .catch(() => {});
      })
      .catch(() => setResult(null))
      .finally(() => setLoading(false));
  }, [market, period]);

  const loadVcp = (force: boolean = false) => {
    setVcpLoading(true);
    fetchApi<ScanResult>(`/scanner/rs/${market}/vcp?period=${period}&force=${force}`)
      .then((r) => { setVcpData(r.data); setVcpOpen(true); })
      .catch(() => setVcpData(null))
      .finally(() => setVcpLoading(false));
  };

  // VCP 3단계 분류
  const vcpLowBase = vcpData?.filter((r) => r["고가대비(%)"] != null && r["고가대비(%)"] <= -20 && r["고가대비(%)"] >= -40) || [];
  const vcpHighBase = vcpData?.filter((r) => r["고가대비(%)"] != null && r["고가대비(%)"] > -20 && r["고가대비(%)"] < -5) || [];
  const vcpBreakout = vcpData?.filter((r) => r["고가대비(%)"] != null && r["고가대비(%)"] >= -5) || [];

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-4">RS Scanner — RS 강세 상위 종목</h1>

      {/* 컨트롤 */}
      <div className="flex items-center gap-4 mb-4">
        {/* 한국/미국 */}
        <div className="flex gap-1">
          {(["KR", "US"] as const).map((r) => (
            <button key={r} onClick={() => setRegion(r)}
              className={`px-3 py-1 rounded text-sm ${region === r ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
              {r === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}
            </button>
          ))}
        </div>

        {/* 시장 */}
        <div className="flex gap-1">
          {markets.map((m) => (
            <button key={m} onClick={() => setMarket(m)}
              className={`px-3 py-1 rounded text-sm ${market === m ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
              {m}
            </button>
          ))}
        </div>

        {/* 기간 */}
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`px-3 py-1 rounded text-sm ${period === p ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
              {p}일
            </button>
          ))}
        </div>
      </div>

      {/* RS 결과 */}
      {loading && <LoadingSpinner text="RS 스캐닝 중" />}
      {!loading && result && (
        <>
          <p className="text-xs text-gray-500 mb-2">{result.market} · {result.period}일 · {result.count}종목</p>
          <DataTable columns={COLUMNS} data={result.data} tickerKey="종목코드" showRowNumber />
        </>
      )}

      {/* VCP 필터 섹션 */}
      {!loading && result && result.count > 0 && (
        <div className="mt-8">
          <div className="flex items-center gap-3 mb-3">
            <h2 className="text-lg font-bold text-white">VCP 후보 필터</h2>
            <button onClick={() => loadVcp(true)}
              disabled={vcpLoading}
              className="px-3 py-1 rounded text-sm bg-[#1f2937] text-gray-400 hover:text-white disabled:opacity-50">
              {vcpLoading ? "재계산 중..." : "재계산"}
            </button>
          </div>

          {vcpOpen && vcpData && (
            <div className="space-y-6">
              <p className="text-xs text-gray-600">
                3일 평균 거래량 &lt; 60일 평균 × 80% · 3일 고저폭 ≤ 5%
              </p>

              {/* 전체 */}
              <div>
                <p className="text-sm text-gray-400 mb-1 font-medium">전체 VCP 후보 ({vcpData.length})</p>
                <DataTable columns={COLUMNS} data={vcpData} tickerKey="종목코드" showRowNumber />
              </div>

              {/* 낮은 베이스 */}
              <div>
                <p className="text-sm text-gray-400 mb-1 font-medium">낮은 베이스 -20%~-40% ({vcpLowBase.length})</p>
                {vcpLowBase.length > 0
                  ? <DataTable columns={COLUMNS} data={vcpLowBase} tickerKey="종목코드" showRowNumber />
                  : <p className="text-xs text-gray-600 py-2">해당 종목 없음</p>}
              </div>

              {/* 높은 베이스 */}
              <div>
                <p className="text-sm text-gray-400 mb-1 font-medium">높은 베이스 -5%~-20% ({vcpHighBase.length})</p>
                {vcpHighBase.length > 0
                  ? <DataTable columns={COLUMNS} data={vcpHighBase} tickerKey="종목코드" showRowNumber />
                  : <p className="text-xs text-gray-600 py-2">해당 종목 없음</p>}
              </div>

              {/* 신고가 근접 */}
              <div>
                <p className="text-sm text-gray-400 mb-1 font-medium">신고가 -5% 이내 ({vcpBreakout.length})</p>
                {vcpBreakout.length > 0
                  ? <DataTable columns={COLUMNS} data={vcpBreakout} tickerKey="종목코드" showRowNumber />
                  : <p className="text-xs text-gray-600 py-2">해당 종목 없음</p>}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
