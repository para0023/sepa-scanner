"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchApi } from "@/lib/api";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

interface DashboardData {
  indices: Record<string, { price: number; change: number; change_pct: number }>;
  oti: Record<string, { oti: number; level: string; count: number; details: any[] }>;
  holdings: Record<string, any[]>;
  stop_alerts: any[];
  assets: Record<string, { capital: number; cum_pnl: number; unrealized: number; total: number; total_ret: number }>;
}

function MetricCard({ label, price, change, changePct }: {
  label: string; price: number; change: number; changePct: number;
}) {
  const isUp = change >= 0;
  return (
    <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-lg font-bold text-white">{price.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}</p>
      <p className={`text-xs ${isUp ? "text-red-400" : "text-teal-400"}`}>
        {isUp ? "+" : ""}{change.toLocaleString("ko-KR", { maximumFractionDigits: 2 })} ({isUp ? "+" : ""}{changePct.toFixed(2)}%)
      </p>
    </div>
  );
}

function fmt(n: number) { return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 }); }

export default function Dashboard() {
  const router = useRouter();
  const [idx, setIdx] = useState<Record<string, { price: number; change: number; change_pct: number }>>({});
  const [oti, setOti] = useState<Record<string, { oti: number; level: string; count: number; details: any[] }>>({});
  const [holdings, setHoldings] = useState<Record<string, any[]>>({});
  const [stop_alerts, setStopAlerts] = useState<any[]>([]);
  const [assets, setAssets] = useState<Record<string, { capital: number; cum_pnl: number; unrealized: number; total: number; total_ret: number }>>({});
  const [loading, setLoading] = useState(true);
  const [pricesLoading, setPricesLoading] = useState(false);
  const [indicesLoading, setIndicesLoading] = useState(false);
  const [indexPeriod, setIndexPeriod] = useState(1);

  useEffect(() => {
    // 1단계: 보유종목 + OTI (빠름, 파일 읽기)
    fetchApi<any>("/dashboard/holdings")
      .then((h) => {
        setOti(h.oti || {});
        setHoldings(h.holdings || {});
        setAssets(h.assets || {});
        setLoading(false); // 즉시 화면 표시

        // 2단계: 현재가 (느림, yfinance)
        setPricesLoading(true);
        fetchApi<any>("/dashboard/prices")
          .then((p) => {
            setHoldings(p.holdings || {});
            setStopAlerts(p.stop_alerts || []);
            setAssets(p.assets || {});
          })
          .catch(() => {})
          .finally(() => setPricesLoading(false));
      })
      .catch(() => setLoading(false));

  }, []);

  // 지수/매크로 — period 변경 시 재호출
  useEffect(() => {
    setIndicesLoading(true);
    fetchApi<any>(`/dashboard/indices?lookback=${indexPeriod}`)
      .then((i) => setIdx(i.indices || {}))
      .catch(() => {})
      .finally(() => setIndicesLoading(false));
  }, [indexPeriod]);

  if (loading) return <LoadingSpinner text="대시보드 로딩 중" />;

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-1">SEPA Dashboard</h1>
      <p className="text-xs text-gray-600 mb-4">Specific Entry Point Analysis · Market Index & 포트폴리오 요약</p>

      {/* 시장 지수 */}
      <div className="flex items-center gap-3 mb-2">
        <h2 className="text-sm text-gray-500">Market Index</h2>
        <div className="flex gap-1">
          {([
            { value: 1, label: "전일" },
            { value: 5, label: "전주" },
            { value: 20, label: "전월" },
            { value: 250, label: "전년" },
          ] as const).map((p) => (
            <button key={p.value} onClick={() => setIndexPeriod(p.value)}
              className={`px-2 py-0.5 rounded text-xs ${indexPeriod === p.value ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-500 hover:text-white"}`}>
              {p.label}
            </button>
          ))}
        </div>
        {indicesLoading && <span className="text-blue-400 animate-pulse text-xs">조회 중...</span>}
      </div>
      <div className="grid grid-cols-4 gap-3 mb-4">
        {["코스피", "코스닥", "S&P500", "나스닥"].map((label) => {
          const d = idx[label];
          return d ? <MetricCard key={label} label={label} price={d.price} change={d.change} changePct={d.change_pct} />
            : <div key={label} className="bg-[#161b22] rounded-lg p-3 border border-gray-800"><p className="text-xs text-gray-500">{label}</p><p className="text-lg text-gray-600">—</p></div>;
        })}
      </div>

      {/* 매크로 */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {[{ key: "USD/KRW", label: "원/달러" }, { key: "DXY", label: "DXY" }, { key: "WTI", label: "WTI" }, { key: "Gold", label: "Gold" }].map(({ key, label }) => {
          const d = idx[key];
          return d ? <MetricCard key={key} label={label} price={d.price} change={d.change} changePct={d.change_pct} />
            : <div key={key} className="bg-[#161b22] rounded-lg p-3 border border-gray-800"><p className="text-xs text-gray-500">{label}</p><p className="text-lg text-gray-600">—</p></div>;
        })}
      </div>

      {/* Risk — OTI + 시장점수 */}
      <h2 className="text-sm text-gray-500 mb-2">Risk</h2>
      <div className="grid grid-cols-2 gap-3 mb-6">
        {(["KR", "US"] as const).map((m) => {
          const o = oti[m];
          return (
            <div key={m} className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
              <p className="text-xs text-gray-500">{m === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"} OTI</p>
              <p className="text-xl font-bold text-white">{o ? o.oti : "—"} {o && <span className="text-sm">{o.level}</span>}</p>
              {o && o.details?.map((d: any, i: number) => (
                <p key={i} className="text-xs text-gray-600">· {d["종목명"]} ({d["보유일"]}일, {d["수익률"] >= 0 ? "+" : ""}{d["수익률"].toFixed(2)}%)</p>
              ))}
            </div>
          );
        })}
      </div>

      {/* 보유 포트폴리오 + 손절 근접 */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {/* 보유 종목 */}
        <div className="col-span-2">
          <h2 className="text-sm text-gray-500 mb-2">보유 포트폴리오{pricesLoading && <span className="ml-2 text-blue-400 animate-pulse text-xs">현재가 조회 중...</span>}</h2>

          {(["KR", "US"] as const).map((m) => {
            const rows = holdings[m];
            if (!rows || rows.length === 0) return null;
            const currency = m === "KR" ? "원" : "$";
            return (
              <div key={m} className="mb-4">
                <p className="text-xs text-gray-400 mb-1 font-medium">{m === "KR" ? "한국" : "미국"}</p>
                <div className="overflow-x-auto border border-gray-800 rounded-lg">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-[#161b22] border-b border-gray-800 text-gray-500">
                        <th className="px-2 py-1.5 text-left">종목</th>
                        <th className="px-2 py-1.5 text-right">평균가</th>
                        <th className="px-2 py-1.5 text-right">현재가</th>
                        <th className="px-2 py-1.5 text-right">손절가</th>
                        <th className="px-2 py-1.5 text-right">수익률</th>
                        <th className="px-2 py-1.5 text-center">경과</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r: any, i: number) => {
                        const ret = r["수익률"];
                        return (
                          <tr key={i} className="border-b border-gray-800/50 hover:bg-[#1f2937] cursor-pointer"
                            onClick={() => router.push(`/chart/${r["종목코드"]}`)}>
                            <td className="px-2 py-1 text-gray-300">{r["종목명"]}</td>
                            <td className="px-2 py-1 text-right text-gray-400">{fmt(r["평균매수가"])}</td>
                            <td className="px-2 py-1 text-right text-white">{r["현재가"] ? fmt(r["현재가"]) : "—"}</td>
                            <td className="px-2 py-1 text-right text-gray-400">{fmt(r["손절가"])}</td>
                            <td className={`px-2 py-1 text-right font-medium ${ret != null ? (ret >= 0 ? "text-red-400" : "text-teal-400") : "text-gray-600"}`}>
                              {ret != null ? `${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%` : "—"}
                            </td>
                            <td className="px-2 py-1 text-center text-gray-500">{r["경과일"]}일</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}
        </div>

        {/* 손절 근접 + 총자산 */}
        <div>
          <h2 className="text-sm text-gray-500 mb-2">손절선 근접 종목</h2>
          <div className="border border-gray-800 rounded-lg overflow-hidden mb-4">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-[#161b22] border-b border-gray-800 text-gray-500">
                  <th className="px-2 py-1.5 text-left">종목</th>
                  <th className="px-2 py-1.5 text-right">현재가</th>
                  <th className="px-2 py-1.5 text-right">손절가</th>
                  <th className="px-2 py-1.5 text-right">거리</th>
                </tr>
              </thead>
              <tbody>
                {stop_alerts.map((a: any, i: number) => {
                  const dist = a["손절거리(%)"];
                  const urgent = dist != null && dist < 3;
                  return (
                    <tr key={i} className={`border-b border-gray-800/50 cursor-pointer ${urgent ? "bg-red-900/20" : "hover:bg-[#1f2937]"}`}
                      onClick={() => router.push(`/chart/${a["종목코드"]}`)}>
                      <td className="px-2 py-1 text-gray-300">
                        <span className="text-gray-600 text-[10px] mr-1">{a["시장"]}</span>{a["종목명"]}
                      </td>
                      <td className="px-2 py-1 text-right text-white">{a["현재가"] ? fmt(a["현재가"]) : "—"}</td>
                      <td className="px-2 py-1 text-right text-gray-400">{a["손절가"] ? fmt(a["손절가"]) : "—"}</td>
                      <td className={`px-2 py-1 text-right font-medium ${urgent ? "text-red-400" : "text-yellow-400"}`}>
                        {dist != null ? `${dist.toFixed(1)}%` : "—"}
                      </td>
                    </tr>
                  );
                })}
                {stop_alerts.length === 0 && (
                  <tr><td colSpan={4} className="px-2 py-4 text-center text-gray-600">없음</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* 총자산 */}
          <h2 className="text-sm text-gray-500 mb-2">총자산</h2>
          {(["KR", "US"] as const).map((m) => {
            const a = assets[m];
            if (!a || a.capital <= 0) return null;
            const currency = m === "KR" ? "원" : "$";
            const isUp = a.total_ret >= 0;
            return (
              <div key={m} className="bg-[#161b22] rounded-lg p-3 border border-gray-800 mb-2">
                <p className="text-xs text-gray-500">{m === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}</p>
                <p className="text-lg font-bold text-white">{m === "KR" ? `${fmt(a.total)}원` : `$${fmt(a.total)}`}</p>
                <p className={`text-xs ${isUp ? "text-red-400" : "text-teal-400"}`}>
                  수익률 {isUp ? "+" : ""}{a.total_ret.toFixed(2)}%
                </p>
                <p className="text-[10px] text-gray-600 mt-1">
                  실현 {m === "KR" ? fmt(a.cum_pnl) : "$" + fmt(a.cum_pnl)} · 미실현 {m === "KR" ? fmt(a.unrealized) : "$" + fmt(a.unrealized)}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
