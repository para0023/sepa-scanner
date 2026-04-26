"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchApi } from "@/lib/api";
import CandlestickChart from "@/components/charts/CandlestickChart";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

interface ChartResponse {
  info: {
    ticker: string;
    name: string;
    market: string;
    benchmark: string;
    period: number;
  };
  ohlcv: {
    dates: string[];
    open: number[];
    high: number[];
    low: number[];
    close: number[];
    volume: number[];
  };
  ma: Record<string, (number | null)[]>;
  rs: {
    line: (number | null)[];
    score: number;
    stock_return: number;
    index_return: number;
  };
  signals: {
    entry: number[];
    sell: number[];
    pressure: number[];
  };
  atr: (number | null)[];
  benchmark_line: (number | null)[];
  trades: { date: string; type: string; price: number; quantity: number }[];
}

// 지표 카드용 (기간별 RS/신호)
interface MetricsResponse {
  rs: { score: number; stock_return: number; index_return: number };
  signals: { entry: number[]; sell: number[] };
}

const PERIOD_OPTIONS = [20, 40, 60, 120, 250];

export default function ChartPage() {
  const params = useParams();
  const ticker = params.ticker as string;

  const [data, setData] = useState<ChartResponse | null>(null);
  const [period, setPeriod] = useState(60);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 3년치(750거래일) 차트 데이터 — 한 번만 로딩
  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError("");
    fetchApi<ChartResponse>(`/chart/${ticker}?period=750`)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker]);

  // 기간별 지표 카드 — period 변경 시 재계산
  useEffect(() => {
    if (!ticker) return;
    fetchApi<MetricsResponse>(`/chart/${ticker}?period=${period}`)
      .then(setMetrics)
      .catch(() => {});
  }, [ticker, period]);

  const signalColor = (val: number) => {
    if (val <= 0.33) return "text-green-400";
    if (val <= 0.66) return "text-yellow-400";
    return "text-red-400";
  };

  const signalLabel = (val: number) => {
    if (val <= 0.33) return "🟢";
    if (val <= 0.66) return "🟡";
    return "🔴";
  };

  // 지표 카드에 표시할 값 (metrics가 있으면 period 기준, 없으면 전체 데이터 기준)
  const m = metrics || (data ? data : null);
  const lastEntry = m ? m.signals.entry[m.signals.entry.length - 1] : 0;
  const lastSell = m ? m.signals.sell[m.signals.sell.length - 1] : 0;

  return (
    <div>
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-white">
            {data ? `${data.info.name} (${data.info.ticker})` : ticker}
          </h1>
          {data && (
            <p className="text-sm text-gray-500 mt-1">
              {data.info.market} · 벤치마크: {data.info.benchmark}
            </p>
          )}
        </div>

        {/* 기간 선택 — RS/신호 지표만 연동 */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">지표 기간</span>
          <div className="flex gap-1">
            {PERIOD_OPTIONS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1 rounded text-sm transition ${
                  period === p
                    ? "bg-blue-600 text-white"
                    : "bg-[#1f2937] text-gray-400 hover:text-white"
                }`}
              >
                {p}일
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 지표 카드 — period 기준 */}
      {m && (
        <div className="grid grid-cols-4 gap-3 mb-4">
          <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
            <p className="text-xs text-gray-500">RS Score ({period}일)</p>
            <p className={`text-xl font-bold ${m.rs.score >= 0 ? "text-red-400" : "text-blue-400"}`}>
              {m.rs.score > 0 ? "+" : ""}{m.rs.score}
            </p>
          </div>
          <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
            <p className="text-xs text-gray-500">종목 수익률 ({period}일)</p>
            <p className={`text-xl font-bold ${m.rs.stock_return >= 0 ? "text-red-400" : "text-blue-400"}`}>
              {m.rs.stock_return > 0 ? "+" : ""}{m.rs.stock_return}%
            </p>
          </div>
          <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
            <p className="text-xs text-gray-500">진입신호</p>
            <p className={`text-xl font-bold ${signalColor(lastEntry)}`}>
              {signalLabel(lastEntry)}
              <span className="text-sm ml-1">{(lastEntry * 100).toFixed(0)}</span>
            </p>
          </div>
          <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
            <p className="text-xs text-gray-500">분배신호</p>
            <p className={`text-xl font-bold ${signalColor(lastSell)}`}>
              {signalLabel(lastSell)}
              <span className="text-sm ml-1">{(lastSell * 100).toFixed(0)}</span>
            </p>
          </div>
        </div>
      )}

      {/* 로딩/에러 */}
      {loading && <LoadingSpinner text="차트 로딩 중" />}
      {error && (
        <div className="flex items-center justify-center h-96 bg-[#161b22] rounded-lg border border-red-900">
          <p className="text-red-400">{error}</p>
        </div>
      )}

      {/* 차트 — 독립적으로 줌/스크롤 가능, RS는 period 기준 재정규화 */}
      {data && !loading && (
        <CandlestickChart data={{
          ...data,
          rs: {
            ...data.rs,
            line: (() => {
              // period 시작점 = 100으로 RS line 재정규화
              const anchorIdx = Math.max(0, data.rs.line.length - period);
              const anchor = data.rs.line[anchorIdx];
              if (anchor == null || anchor === 0) return data.rs.line;
              return data.rs.line.map((v) => v != null ? (v / anchor) * 100 : null);
            })(),
          },
        }} />
      )}
    </div>
  );
}
