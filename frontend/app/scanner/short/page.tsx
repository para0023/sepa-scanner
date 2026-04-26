"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import DataTable from "@/components/tables/DataTable";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

const COLUMNS = [
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "상태", label: "상태", align: "center" as const },
  { key: "현재가", label: "현재가", align: "right" as const, format: "price" as const },
  { key: "200일선대비(%)", label: "200MA대비", align: "right" as const, format: "percent" as const },
  { key: "고점대비(%)", label: "고점대비", align: "right" as const, format: "percent" as const },
  { key: "돌파경과(일)", label: "경과(일)", align: "center" as const },
  { key: "거래량비율(%)", label: "거래량비율", align: "right" as const, format: "number" as const },
  { key: "인버스ETF", label: "인버스ETF", align: "left" as const },
];

const ETF_COLUMNS = [
  { key: "종목코드", label: "코드", align: "left" as const },
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "원본종목", label: "원본종목", align: "left" as const },
  { key: "타입", label: "타입", align: "center" as const },
];

interface ShortResult {
  market: string;
  count: number;
  data: Record<string, any>[];
  inverse_etf: Record<string, any>[];
}

export default function ShortScannerPage() {
  const [result, setResult] = useState<ShortResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [showEtf, setShowEtf] = useState(false);

  const load = (force: boolean = false) => {
    setLoading(true);
    fetchApi<ShortResult>(`/scanner/short/KOSPI?force=${force}`)
      .then(setResult)
      .catch(() => setResult(null))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-1">Short Scanner</h1>
      <p className="text-xs text-gray-600 mb-4">Stage 4 하락 추세 종목 + 인버스 ETF 매핑 · 200일선 하방 · MA 역배열</p>

      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => load(true)} disabled={loading}
          className="px-3 py-1 rounded text-sm bg-[#1f2937] text-gray-400 hover:text-white disabled:opacity-50">
          {loading ? "스캔 중..." : "강제 재스캔"}
        </button>
      </div>

      {loading && <LoadingSpinner text="Short 스캐닝 중" />}

      {!loading && result && (
        <>
          {result.count > 0 ? (
            <>
              <p className="text-xs text-gray-500 mb-2">{result.count}종목 Stage 4 감지</p>
              <DataTable columns={COLUMNS} data={result.data} tickerKey="종목코드" showRowNumber />
            </>
          ) : (
            <p className="text-sm text-green-400 py-4">Stage 4 진입 종목이 없습니다. (모든 대상 종목이 200일선 위)</p>
          )}

          {/* 인버스 ETF 매핑 */}
          <div className="mt-6">
            <button onClick={() => setShowEtf(!showEtf)}
              className="text-sm text-gray-400 hover:text-white">
              {showEtf ? "▼" : "▶"} 인버스 ETF 매핑 ({result.inverse_etf.length})
            </button>
            {showEtf && (
              <div className="mt-2">
                <DataTable columns={ETF_COLUMNS} data={result.inverse_etf} tickerKey="종목코드" />
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
