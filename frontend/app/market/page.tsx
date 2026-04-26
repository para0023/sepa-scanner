"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { fetchApi } from "@/lib/api";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const PERIODS = [
  { value: 30, label: "1개월" },
  { value: 60, label: "2개월" },
  { value: 90, label: "3개월" },
  { value: 180, label: "6개월" },
  { value: 365, label: "1년" },
];

interface ChartData {
  dates: string[];
  values: number[];
}

function IndicatorChart({ data, title, decimal = 2, unit = "", height = 260 }: {
  data: ChartData | null; title: string; decimal?: number; unit?: string; height?: number;
}) {
  if (!data || data.values.length === 0) {
    return (
      <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl p-4 mb-4" style={{ minHeight: height }}>
        <p className="text-sm text-gray-600">{title} — 데이터 없음</p>
      </div>
    );
  }

  const last = data.values[data.values.length - 1];
  const first = data.values[0];
  const chgPct = first !== 0 ? ((last / first) - 1) * 100 : 0;
  const isUp = last >= first;
  const lineColor = isUp ? "#ef5350" : "#42a5f5";
  const areaTop = isUp ? "rgba(239,83,80,0.15)" : "rgba(66,165,245,0.15)";

  const yMin = Math.min(...data.values);
  const yMax = Math.max(...data.values);
  const margin = yMax !== yMin ? (yMax - yMin) * 0.05 : Math.abs(yMax) * 0.02;

  return (
    <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl overflow-hidden mb-4">
      <ReactECharts style={{ height }} option={{
        animation: false,
        backgroundColor: "transparent",
        title: {
          text: title,
          subtext: `현재 ${unit}${last.toLocaleString(undefined, { maximumFractionDigits: decimal })}  |  변동 ${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%`,
          left: "center",
          textStyle: { color: "#ccc", fontSize: 13, fontWeight: "bold" },
          subtextStyle: { color: "#888", fontSize: 11 },
        },
        tooltip: {
          trigger: "axis",
          backgroundColor: "rgba(20,20,30,0.9)",
          borderColor: "#555",
          textStyle: { color: "#eee", fontSize: 12 },
        },
        grid: { left: "12%", right: "5%", top: "22%", bottom: "15%" },
        xAxis: {
          type: "category", data: data.dates,
          axisLine: { lineStyle: { color: "#444" } },
          axisLabel: { color: "#888", fontSize: 10 },
          axisTick: { show: false },
        },
        yAxis: {
          type: "value", min: Number((yMin - margin).toFixed(decimal)), max: Number((yMax + margin).toFixed(decimal)),
          splitNumber: 5,
          axisLine: { show: false },
          axisLabel: { color: "#888", fontSize: 10 },
          splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
        },
        dataZoom: [{ type: "inside", start: 0, end: 100 }],
        series: [{
          type: "line", data: data.values, symbol: "none",
          lineStyle: { color: lineColor, width: 2 },
          areaStyle: {
            color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: areaTop }, { offset: 1, color: "rgba(0,0,0,0)" }],
            },
          },
          markLine: {
            silent: true, symbol: "none",
            data: [{
              yAxis: last,
              lineStyle: { color: lineColor, type: "dashed", width: 1 },
              label: { show: true, position: "insideEndTop", formatter: `${unit}${last.toLocaleString(undefined, { maximumFractionDigits: decimal })}`, color: lineColor, fontSize: 11 },
            }],
          },
        }],
      }} />
    </div>
  );
}

function VixStatus({ value }: { value: number }) {
  const level = value > 30 ? "극도 공포" : value > 20 ? "공포" : value > 15 ? "보통" : "탐욕";
  const color = value > 30 ? "text-red-500" : value > 20 ? "text-orange-400" : value > 15 ? "text-gray-400" : "text-green-400";
  return <p className={`text-xs ${color} mt-1`}>현재 수준: {level}</p>;
}

function SpreadStatus({ value }: { value: number }) {
  return <p className={`text-xs ${value > 0 ? "text-green-400" : "text-red-400"} mt-1`}>{value > 0 ? "정상 (양수)" : "역전 (경기침체 경고)"}</p>;
}

export default function MarketPage() {
  const [period, setPeriod] = useState(90);
  const [data, setData] = useState<Record<string, ChartData>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchApi<any>(`/market/indicators?days=${period}`)
      .then((r) => setData(r?.data || {}))
      .catch(() => setData({}))
      .finally(() => setLoading(false));
  }, [period]);

  const d = (key: string) => data[key] || null;
  const lastVal = (key: string) => {
    const v = d(key);
    return v && v.values.length > 0 ? v.values[v.values.length - 1] : null;
  };

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-1">시장 지표</h1>
      <p className="text-xs text-gray-600 mb-4">주요 거시경제 지표 추이</p>

      {/* 기간 선택 */}
      <div className="flex gap-1 mb-4">
        {PERIODS.map((p) => (
          <button key={p.value} onClick={() => setPeriod(p.value)}
            className={`px-3 py-1 rounded text-sm ${period === p.value ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
            {p.label}
          </button>
        ))}
      </div>

      {loading && <LoadingSpinner text="시장 데이터 로딩 중" />}

      {!loading && (
        <div>
          {/* 주요 지수 */}
          <h2 className="text-sm text-gray-500 mb-2">주요 지수</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <IndicatorChart data={d("코스피")} title="코스피" decimal={2} />
              <IndicatorChart data={d("코스닥")} title="코스닥" decimal={2} />
            </div>
            <div>
              <IndicatorChart data={d("S&P500")} title="S&P500" decimal={2} />
              <IndicatorChart data={d("나스닥")} title="나스닥" decimal={2} />
            </div>
          </div>

          {/* 외국인 수급 */}
          {(d("외국인(유가)") || d("외국인(코스닥)")) && (
            <>
              <h2 className="text-sm text-gray-500 mb-2 mt-6">외국인 수급</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <IndicatorChart data={d("외국인(유가)")} title="외국인 순매수 - 유가증권 (억원)" decimal={0} />
                  <IndicatorChart data={d("외국인(유가)_cum")} title="외국인 누적 순매수 - 유가증권 (억원)" decimal={0} />
                </div>
                <div>
                  <IndicatorChart data={d("외국인(코스닥)")} title="외국인 순매수 - 코스닥 (억원)" decimal={0} />
                  <IndicatorChart data={d("외국인(코스닥)_cum")} title="외국인 누적 순매수 - 코스닥 (억원)" decimal={0} />
                </div>
              </div>
            </>
          )}

          {/* 금리 */}
          <h2 className="text-sm text-gray-500 mb-2 mt-6">금리</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <IndicatorChart data={d("KR10Y")} title="한국 국고채 10년물" decimal={3} />
              <IndicatorChart data={d("KR2Y")} title="한국 국고채 2년물" decimal={3} />
              <IndicatorChart data={d("KR_spread")} title="한국 장단기 금리차 (10Y-2Y)" decimal={3} />
              {lastVal("KR_spread") !== null && <SpreadStatus value={lastVal("KR_spread")!} />}
            </div>
            <div>
              <IndicatorChart data={d("US10Y")} title="미국 국채 10년물" decimal={3} />
              <IndicatorChart data={d("US2Y")} title="미국 국채 2년물" decimal={3} />
              <IndicatorChart data={d("US_spread")} title="미국 장단기 금리차 (10Y-2Y)" decimal={3} />
              {lastVal("US_spread") !== null && <SpreadStatus value={lastVal("US_spread")!} />}
            </div>
          </div>

          {/* 변동성 */}
          <h2 className="text-sm text-gray-500 mb-2 mt-6">변동성</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <IndicatorChart data={d("VIX")} title="VIX (S&P500 변동성)" decimal={2} />
              {lastVal("VIX") !== null && <VixStatus value={lastVal("VIX")!} />}
            </div>
            <div />
          </div>

          {/* 환율 */}
          <h2 className="text-sm text-gray-500 mb-2 mt-6">환율</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <IndicatorChart data={d("USD/KRW")} title="USD/KRW (원/달러)" decimal={2} />
            <IndicatorChart data={d("DXY")} title="달러 인덱스 (DXY)" decimal={2} />
          </div>

          {/* 원자재 */}
          <h2 className="text-sm text-gray-500 mb-2 mt-6">원자재</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <IndicatorChart data={d("WTI")} title="WTI 원유 ($/bbl)" unit="$" decimal={2} />
              <IndicatorChart data={d("Gold")} title="금 ($/oz)" unit="$" decimal={2} />
              <IndicatorChart data={d("Copper")} title="구리 ($/lb)" unit="$" decimal={2} />
            </div>
            <div>
              <IndicatorChart data={d("Silver")} title="은 ($/oz)" unit="$" decimal={2} />
              <IndicatorChart data={d("NatGas")} title="천연가스 ($/MMBtu)" unit="$" decimal={2} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
