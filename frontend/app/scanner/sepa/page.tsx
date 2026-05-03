"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { fetchSSE } from "@/lib/api";
import DataTable from "@/components/tables/DataTable";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

const COLUMNS = [
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "RS Score", label: "RS Score", align: "right" as const, format: "number" as const },
  { key: "RS순위(%)", label: "RS순위(%)", align: "right" as const, format: "number" as const },
  { key: "최종피벗", label: "최종피벗", align: "right" as const, format: "price" as const },
  { key: "직전피벗", label: "직전피벗", align: "right" as const, format: "price" as const },
  { key: "현재가", label: "현재가", align: "right" as const, format: "price" as const },
  { key: "피벗거리(%)", label: "피벗거리(%)", align: "right" as const, format: "percent" as const },
  { key: "수축(T)", label: "수축(T)", align: "center" as const },
  { key: "수축강도(%)", label: "수축강도(%)", align: "right" as const, format: "number" as const },
  { key: "베이스기간(일)", label: "베이스(일)", align: "center" as const },
  { key: "거래량비율(%)", label: "거래량비율(%)", align: "right" as const, format: "number" as const },
  { key: "ATR(20)", label: "ATR(20)", align: "right" as const, format: "price" as const },
  { key: "ATR(%)", label: "ATR(%)", align: "right" as const, format: "number" as const },
];

interface ScanResult {
  market: string;
  period: number;
  count: number;
  data: Record<string, any>[];
}

interface MarketState {
  result: ScanResult | null;
  loading: boolean;
  progress: { done: number; total: number } | null;
}

export default function SEPAScannerPage() {
  return (
    <Suspense fallback={<LoadingSpinner text="로딩 중" />}>
      <SEPAScannerInner />
    </Suspense>
  );
}

function SEPAScannerInner() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const initRegion = (searchParams.get("region") === "US" ? "US" : "KR") as "KR" | "US";
  const [region, setRegion] = useState<"KR" | "US">(initRegion);

  // URL 쿼리 파라미터 동기화
  useEffect(() => {
    router.replace(`?region=${region}`, { scroll: false });
  }, [region]);
  const [marketState, setMarketState] = useState<Record<string, MarketState>>({});

  const marketGroups = region === "KR"
    ? ["KOSPI", "KOSDAQ"]
    : ["NASDAQ", "NYSE"];

  const loadMarket = (market: string, force: boolean = false) => {
    setMarketState((prev) => ({
      ...prev,
      [market]: { result: null, loading: true, progress: null },
    }));

    fetchSSE<ScanResult>(
      `/scanner/sepa/${market}/stream?period=60&force=${force}`,
      (done, total) => {
        setMarketState((prev) => ({
          ...prev,
          [market]: { ...prev[market], progress: { done, total } },
        }));
      },
    )
      .then((result) => {
        setMarketState((prev) => ({
          ...prev,
          [market]: { result, loading: false, progress: null },
        }));
      })
      .catch(() => {
        setMarketState((prev) => ({
          ...prev,
          [market]: { result: null, loading: false, progress: null },
        }));
      });
  };

  const loadAll = (force: boolean = false) => {
    marketGroups.forEach((m) => loadMarket(m, force));
  };

  useEffect(() => {
    loadAll();
  }, [region]);

  const anyLoading = marketGroups.some((m) => marketState[m]?.loading);

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-1">SEPA Scanner</h1>
      <p className="text-xs text-gray-600 mb-4">Breakout Entry (VCP / BO) · RS 60일 기준 · RS 상위 40% · 당일 캐시 자동 로드</p>

      <div className="flex items-center gap-4 mb-4">
        <div className="flex gap-1">
          {(["KR", "US"] as const).map((r) => (
            <button key={r} onClick={() => setRegion(r)}
              className={`px-3 py-1 rounded text-sm ${region === r ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
              {r === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}
            </button>
          ))}
        </div>

        <button onClick={() => loadAll(true)}
          disabled={anyLoading}
          className="px-3 py-1 rounded text-sm bg-[#1f2937] text-gray-400 hover:text-white disabled:opacity-50">
          {anyLoading ? "스캔 중..." : "강제 재스캔"}
        </button>
      </div>

      {/* 각 시장별 테이블 */}
      {marketGroups.map((market) => {
        const ms = marketState[market];
        const isLoading = !ms || ms.loading;
        const result = ms?.result;
        const progress = ms?.progress;

        return (
          <div key={market} className="mb-6">
            <h2 className="text-base font-bold text-white mb-2">{market}</h2>

            {isLoading && (
              <div className="py-4">
                {progress ? (
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <p className="text-sm text-gray-400">
                        스캔 중... {progress.done}/{progress.total}종목
                        ({Math.round((progress.done / progress.total) * 100)}%)
                      </p>
                    </div>
                    <div className="w-full bg-gray-800 rounded-full h-1.5">
                      <div
                        className="bg-blue-500 h-1.5 rounded-full transition-all"
                        style={{ width: `${(progress.done / progress.total) * 100}%` }}
                      />
                    </div>
                  </div>
                ) : (
                  <LoadingSpinner text="캐시 확인 중" />
                )}
              </div>
            )}

            {!isLoading && result && result.count > 0 && (
              <>
                <p className="text-xs text-gray-500 mb-1">{result.count}종목 발견</p>
                <DataTable columns={COLUMNS} data={result.data} tickerKey="종목코드" showRowNumber />
              </>
            )}

            {!isLoading && (!result || result.count === 0) && (
              <p className="text-xs text-gray-600 py-3">VCP 패턴 종목 없음</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
