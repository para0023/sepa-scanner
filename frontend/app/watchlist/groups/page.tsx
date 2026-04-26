"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchApi } from "@/lib/api";
import DataTable from "@/components/tables/DataTable";
import LoadingSpinner from "@/components/layout/LoadingSpinner";
import dynamic from "next/dynamic";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

const RS_COLUMNS = [
  { key: "그룹명", label: "그룹명", align: "left" as const },
  { key: "RS Score", label: "RS Score", align: "right" as const, format: "number" as const },
  { key: "그룹수익률(%)", label: "그룹수익률", align: "right" as const, format: "percent" as const },
  { key: "종목수", label: "종목수", align: "center" as const },
];

export default function WatchlistGroupsPage() {
  const router = useRouter();
  const [market, setMarket] = useState<"KR" | "US">("KR");
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [rsData, setRsData] = useState<any[]>([]);
  const [rsLoading, setRsLoading] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [newTicker, setNewTicker] = useState("");
  const [period, setPeriod] = useState(60);
  const [chartData, setChartData] = useState<any>(null);
  const [chartLoading, setChartLoading] = useState(false);

  const loadGroups = () => {
    fetchApi<any>(`/watchlist/groups?market=${market}`)
      .then((r) => {
        const g = r?.groups || {};
        setGroups(g);
        const names = Object.keys(g);
        if (names.length > 0 && !names.includes(selectedGroup)) {
          setSelectedGroup(names[0]);
        }
      })
      .catch(() => setGroups({}));
  };

  const loadRS = (force: boolean = false) => {
    setRsLoading(true);
    const endpoint = force ? "/watchlist/groups/rs/refresh" : "/watchlist/groups/rs";
    const method = force ? "POST" : "GET";
    fetch(`${API}${endpoint}?market=${market}&period=${period}`, { method })
      .then((r) => r.json())
      .then((r) => setRsData(r?.data || []))
      .catch(() => setRsData([]))
      .finally(() => setRsLoading(false));
  };

  useEffect(() => { loadGroups(); loadRS(); setChartData(null); }, [market, period]);

  const loadGroupChart = (gname: string) => {
    setChartLoading(true);
    setChartData(null);
    fetch(`${API}/watchlist/groups/${encodeURIComponent(gname)}/chart?market=${market}&period=${period}`)
      .then((r) => r.json())
      .then(setChartData)
      .catch(() => setChartData(null))
      .finally(() => setChartLoading(false));
  };

  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return;
    await fetch(`${API}/watchlist/groups?market=${market}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newGroupName.trim() }),
    });
    setNewGroupName("");
    loadGroups();
  };

  const handleDeleteGroup = async () => {
    if (!selectedGroup) return;
    await fetch(`${API}/watchlist/groups/${encodeURIComponent(selectedGroup)}?market=${market}`, { method: "DELETE" });
    setSelectedGroup("");
    loadGroups(); loadRS();
  };

  const handleAddTicker = async () => {
    if (!newTicker.trim() || !selectedGroup) return;
    await fetch(`${API}/watchlist/groups/${encodeURIComponent(selectedGroup)}/ticker?market=${market}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: newTicker.trim().toUpperCase() }),
    });
    setNewTicker("");
    loadGroups();
  };

  const handleRemoveTicker = async (ticker: string) => {
    await fetch(`${API}/watchlist/groups/${encodeURIComponent(selectedGroup)}/ticker/${encodeURIComponent(ticker)}?market=${market}`, { method: "DELETE" });
    loadGroups();
  };

  // 종목 상세 (종목명 + 현재가 + 수익률)
  const [tickerDetails, setTickerDetails] = useState<any[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (!selectedGroup || !groups[selectedGroup]?.length) {
      setTickerDetails([]);
      return;
    }
    setDetailLoading(true);
    fetch(`${API}/watchlist/groups/${encodeURIComponent(selectedGroup)}/detail?market=${market}&period=${period}`)
      .then((r) => r.json())
      .then((r) => setTickerDetails(r?.data || []))
      .catch(() => setTickerDetails([]))
      .finally(() => setDetailLoading(false));
  }, [selectedGroup, market, period, groups]);

  const tickers = groups[selectedGroup] || [];
  const groupNames = Object.keys(groups);

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-1">그룹 분석</h1>
      <p className="text-xs text-gray-600 mb-4">산업/테마별 종목 그룹 관리 및 RS 강도 비교</p>

      <div className="flex items-center gap-4 mb-4">
        <div className="flex gap-1">
          {(["KR", "US"] as const).map((m) => (
            <button key={m} onClick={() => setMarket(m)}
              className={`px-3 py-1 rounded text-sm ${market === m ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
              {m === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {[10, 20, 40, 60, 120, 252].map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`px-2 py-1 rounded text-xs ${period === p ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-500 hover:text-white"}`}>
              {p}일
            </button>
          ))}
        </div>
        <button onClick={() => loadRS(true)} disabled={rsLoading}
          className="px-3 py-1 rounded text-sm bg-[#1f2937] text-gray-400 hover:text-white disabled:opacity-50">
          {rsLoading ? "계산 중..." : "RS 재계산"}
        </button>
      </div>

      {/* 전체 그룹 RS 랭킹 */}
      {rsLoading && <LoadingSpinner text="그룹 RS 계산 중" />}
      {!rsLoading && rsData.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm text-gray-500 mb-2">전체 그룹 RS 랭킹</h2>
          <DataTable columns={RS_COLUMNS} data={rsData} showRowNumber
            defaultSortKey="RS Score" defaultSortDir="desc"
            onRowClick={(row) => loadGroupChart(row["그룹명"])} />
        </div>
      )}

      {/* 그룹 차트 */}
      {chartLoading && <LoadingSpinner text="그룹 차트 계산 중" />}
      {!chartLoading && chartData && !chartData.error && (
        <div className="mb-6">
          <h2 className="text-sm text-gray-500 mb-2">
            {chartData.group_name}
            <span className="ml-2 text-xs">RS Score: <span className="text-white">{chartData.rs_score}</span></span>
            <span className="ml-2 text-xs">그룹: <span className={chartData.group_ret >= 0 ? "text-red-400" : "text-teal-400"}>{chartData.group_ret >= 0 ? "+" : ""}{chartData.group_ret}%</span></span>
            <span className="ml-2 text-xs">벤치마크: <span className={chartData.bench_ret >= 0 ? "text-red-400" : "text-teal-400"}>{chartData.bench_ret >= 0 ? "+" : ""}{chartData.bench_ret}%</span></span>
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 그룹지수 vs 벤치마크 */}
            <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl overflow-hidden">
              <ReactECharts style={{ height: 280 }} option={{
                backgroundColor: "transparent",
                grid: { left: 45, right: 15, top: 35, bottom: 28 },
                tooltip: { trigger: "axis", backgroundColor: "rgba(22,27,34,0.95)", borderColor: "#333", textStyle: { color: "#ddd" } },
                legend: { show: true, data: ["그룹지수", "벤치마크"], textStyle: { color: "#777", fontSize: 10 }, right: 0, top: 0 },
                xAxis: { type: "category", data: chartData.dates.map((d: string) => d.slice(5)), axisLabel: { color: "#666", fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } }, boundaryGap: false },
                yAxis: { type: "value", axisLabel: { color: "#666", fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } } },
                series: [
                  { name: "그룹지수", type: "line", smooth: 0.4, data: chartData.group_idx, symbol: "none",
                    lineStyle: { color: "#F87171", width: 2.5 },
                    areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(248,113,113,0.15)" }, { offset: 1, color: "rgba(0,0,0,0)" }] } },
                  },
                  { name: "벤치마크", type: "line", smooth: 0.4, data: chartData.benchmark, symbol: "none",
                    lineStyle: { color: "#60A5FA", width: 1.5, type: "dashed" },
                  },
                  { type: "line", data: chartData.dates.map(() => 100), lineStyle: { color: "#444", width: 1, type: [4, 4] }, symbol: "none" },
                ],
              }} />
            </div>

            {/* RS Line */}
            <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl overflow-hidden">
              <ReactECharts style={{ height: 280 }} option={{
                backgroundColor: "transparent",
                grid: { left: 45, right: 15, top: 35, bottom: 28 },
                tooltip: { trigger: "axis", backgroundColor: "rgba(22,27,34,0.95)", borderColor: "#333", textStyle: { color: "#ddd" } },
                legend: { show: true, data: ["RS Line"], textStyle: { color: "#777", fontSize: 10 }, right: 0, top: 0 },
                xAxis: { type: "category", data: chartData.dates.map((d: string) => d.slice(5)), axisLabel: { color: "#666", fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } }, boundaryGap: false },
                yAxis: { type: "value", axisLabel: { color: "#666", fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } } },
                series: [
                  { name: "RS Line", type: "line", smooth: 0.4, data: chartData.rs_line, symbol: "none",
                    lineStyle: { color: "#FF6D00", width: 2.5 },
                    areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: "rgba(255,109,0,0.15)" }, { offset: 1, color: "rgba(0,0,0,0)" }] } },
                  },
                  { type: "line", data: chartData.dates.map(() => 100), lineStyle: { color: "#444", width: 1, type: [4, 4] }, symbol: "none" },
                ],
              }} />
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-4">
        {/* 좌측: 그룹 선택 + 종목 목록 */}
        <div className="col-span-2">
          {groupNames.length > 0 ? (
            <>
              <div className="flex items-center gap-3 mb-3">
                <select value={selectedGroup} onChange={(e) => setSelectedGroup(e.target.value)}
                  className="bg-[#0d1117] border border-gray-700 rounded px-3 py-1.5 text-sm text-white flex-1">
                  {groupNames.map((g) => <option key={g} value={g}>{g} ({groups[g].length})</option>)}
                </select>
              </div>

              {tickers.length > 0 ? (
                <div>
                  {detailLoading && <p className="text-xs text-blue-400 animate-pulse mb-2">종목 정보 로딩 중...</p>}
                  <div className="border border-gray-800 rounded-lg overflow-hidden">
                    <table className="w-full text-sm">
                      <thead><tr className="bg-[#161b22] border-b border-gray-800 text-gray-500 text-xs">
                        <th className="px-3 py-2 text-left">종목명</th>
                        <th className="px-3 py-2 text-right">현재가</th>
                        <th className="px-3 py-2 text-right">{period}일 수익률</th>
                        <th className="px-3 py-2 text-center w-12"></th>
                      </tr></thead>
                      <tbody>
                        {(tickerDetails.length > 0 ? tickerDetails : tickers.map((t) => ({ "종목코드": t, "종목명": t, "현재가": null, "수익률(%)": null }))).map((r: any) => (
                          <tr key={r["종목코드"]} className="border-b border-gray-800/50 hover:bg-[#1f2937] cursor-pointer"
                            onClick={() => router.push(`/chart/${r["종목코드"]}`)}>
                            <td className="px-3 py-1.5 text-gray-300">
                              {r["종목명"]}
                              <span className="text-gray-600 text-xs ml-1">({r["종목코드"]})</span>
                            </td>
                            <td className="px-3 py-1.5 text-right text-white">
                              {r["현재가"] != null ? (market === "KR" ? r["현재가"].toLocaleString() : `$${r["현재가"].toFixed(2)}`) : "—"}
                            </td>
                            <td className={`px-3 py-1.5 text-right font-medium ${r["수익률(%)"] != null ? (r["수익률(%)"] >= 0 ? "text-red-400" : "text-teal-400") : "text-gray-600"}`}>
                              {r["수익률(%)"] != null ? `${r["수익률(%)"] >= 0 ? "+" : ""}${r["수익률(%)"].toFixed(2)}%` : "—"}
                            </td>
                            <td className="px-3 py-1.5 text-center" onClick={(e) => e.stopPropagation()}>
                              <button onClick={() => handleRemoveTicker(r["종목코드"])} className="text-xs text-red-400 hover:text-red-300">삭제</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <p className="text-gray-600 text-sm py-3">종목을 추가하세요.</p>
              )}

              <div className="flex gap-2 mt-3">
                <input placeholder={market === "KR" ? "종목코드 (예: 005930)" : "Ticker (예: NVDA)"}
                  value={newTicker} onChange={(e) => setNewTicker(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddTicker()}
                  className="bg-[#0d1117] border border-gray-700 rounded px-3 py-1.5 text-sm text-white flex-1" />
                <button onClick={handleAddTicker}
                  className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white">추가</button>
              </div>

              <button onClick={handleDeleteGroup}
                className="mt-4 px-3 py-1 rounded text-xs bg-red-900/30 text-red-400 hover:bg-red-900/50 border border-red-900/50">
                그룹 삭제
              </button>
            </>
          ) : (
            <p className="text-gray-600 py-4">그룹이 없습니다. 오른쪽에서 새 그룹을 만들어보세요.</p>
          )}
        </div>

        {/* 우측: 그룹 생성 */}
        <div>
          <h3 className="text-sm font-bold text-white mb-2">새 그룹 만들기</h3>
          <input placeholder="그룹명 (예: 2차전지 소재)"
            value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateGroup()}
            className="w-full bg-[#0d1117] border border-gray-700 rounded px-3 py-1.5 text-sm text-white mb-2" />
          <button onClick={handleCreateGroup}
            className="w-full px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white">생성</button>
        </div>
      </div>
    </div>
  );
}
