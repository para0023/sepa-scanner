"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { fetchApi } from "@/lib/api";
import DataTable from "@/components/tables/DataTable";
import LoadingSpinner from "@/components/layout/LoadingSpinner";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const TABS = ["보유현황", "위험관리", "거래별성과", "종목별성과", "월별분석", "주간리뷰", "매매일지", "잔액관리", "거래이력"];

const POSITION_COLUMNS = [
  { key: "종목코드", label: "종목코드", align: "left" as const },
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "진입근거", label: "진입근거", align: "center" as const },
  { key: "평균매수가", label: "평균매수가", align: "right" as const, format: "price" as const },
  { key: "수량", label: "수량", align: "right" as const },
  { key: "손절가", label: "손절가", align: "right" as const, format: "price" as const },
  { key: "현재가", label: "현재가", align: "right" as const, format: "price" as const },
  { key: "수익률(%)", label: "수익률(%)", align: "right" as const, format: "percent" as const },
  { key: "평가금액", label: "평가금액", align: "right" as const, format: "price" as const },
  { key: "매수일", label: "매수일", align: "center" as const },
  { key: "경과일", label: "경과일", align: "center" as const },
  { key: "손절경고", label: "손절경고", align: "center" as const },
];

const LOG_COLUMNS = [
  { key: "date", label: "날짜", align: "left" as const },
  { key: "name", label: "종목명", align: "left" as const },
  { key: "type", label: "구분", align: "center" as const },
  { key: "price", label: "가격", align: "right" as const, format: "price" as const },
  { key: "quantity", label: "수량", align: "right" as const },
  { key: "entry_reason", label: "근거", align: "center" as const },
  { key: "memo", label: "메모", align: "left" as const },
];

const PNL_COLUMNS = [
  { key: "종목명", label: "종목명", align: "left" as const },
  { key: "진입근거", label: "근거", align: "center" as const },
  { key: "수익률(%)", label: "수익률(%)", align: "right" as const, format: "percent" as const },
  { key: "비용차감손익(원)", label: "실현손익", align: "right" as const, format: "price" as const },
  { key: "거래비용(원)", label: "비용", align: "right" as const, format: "price" as const },
  { key: "보유일수", label: "보유일", align: "center" as const },
  { key: "RR", label: "R/R", align: "right" as const, format: "number" as const },
];

const MONTHLY_COLUMNS = [
  { key: "월", label: "월", align: "left" as const },
  { key: "거래수", label: "거래수", align: "center" as const },
  { key: "승률(%)", label: "승률(%)", align: "right" as const, format: "number" as const },
  { key: "평균수익률(%)", label: "평균수익률", align: "right" as const, format: "percent" as const },
  { key: "총손익", label: "총손익", align: "right" as const, format: "price" as const },
  { key: "누적손익", label: "누적손익", align: "right" as const, format: "price" as const },
];

function _fmt(n: number, ccy?: string) {
  if (ccy === "$") return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}

function KpiCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-lg font-bold ${color || "text-white"}`}>{value}</p>
      {sub && <p className="text-xs text-gray-600">{sub}</p>}
    </div>
  );
}

function WeeklyReviewTab({ market, currency }: { market: "KR" | "US"; currency: string }) {
  const fmt = (n: number) => _fmt(n, currency);
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
  const [weeks, setWeeks] = useState<string[]>([]);
  const [selectedWeek, setSelectedWeek] = useState("");
  const [review, setReview] = useState<any>(null);
  const [wLoading, setWLoading] = useState(false);
  const router = useRouter();

  useEffect(() => {
    fetch(`${API}/portfolio/weekly/weeks?market=${market}`)
      .then((r) => r.json())
      .then((r) => {
        const w = r?.weeks || [];
        setWeeks(w);
        if (w.length > 0 && !selectedWeek) setSelectedWeek(w[0]);
      })
      .catch(() => setWeeks([]));
  }, [market]);

  useEffect(() => {
    if (!selectedWeek) return;
    setWLoading(true);
    fetch(`${API}/portfolio/weekly/review?market=${market}&week=${selectedWeek}`)
      .then((r) => r.json())
      .then(setReview)
      .catch(() => setReview(null))
      .finally(() => setWLoading(false));
  }, [selectedWeek, market]);

  const weekEnd = (w: string) => {
    const d = new Date(w);
    d.setDate(d.getDate() + 4);
    return d.toISOString().slice(0, 10);
  };

  if (weeks.length === 0) return <p className="text-gray-600 py-4">거래 내역이 없습니다.</p>;

  return (
    <div>
      {/* 주간 선택 */}
      <div className="flex gap-1 flex-wrap mb-4">
        {weeks.map((w) => (
          <button key={w} onClick={() => setSelectedWeek(w)}
            className={`px-2.5 py-1 rounded text-xs ${selectedWeek === w ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-500 hover:text-white"}`}>
            {w} ~ {weekEnd(w)}
          </button>
        ))}
      </div>

      {wLoading && <LoadingSpinner text="주간 리뷰 로딩 중" />}

      {!wLoading && review && (
        <div>
          {/* 1. 포트폴리오 현황 */}
          <h3 className="text-sm font-bold text-white mb-2">포트폴리오 현황</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
            <KpiCard label="주초 평가" value={`${fmt(review.week_start_val || 0)}${currency}`} />
            <KpiCard label="주말 평가" value={`${fmt(review.week_end_val || 0)}${currency}`}
              sub={`${(review.week_end_val || 0) - (review.week_start_val || 0) >= 0 ? "+" : ""}${fmt((review.week_end_val || 0) - (review.week_start_val || 0))}${currency}`} />
            <KpiCard label="주간 수익률" value={`${(review.weekly_return_pct || 0) >= 0 ? "+" : ""}${(review.weekly_return_pct || 0).toFixed(2)}%`}
              color={(review.weekly_return_pct || 0) >= 0 ? "text-red-400" : "text-teal-400"} />
          </div>

          {/* 2. 거래현황 */}
          {review.summary && (
            <>
              <h3 className="text-sm font-bold text-white mb-2">거래현황</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <KpiCard label="총거래수" value={`${review.summary["총거래수"] || 0}건`}
                  sub={`${review.summary["승"] || 0}승 ${review.summary["패"] || 0}패`} />
                <KpiCard label="승률" value={`${(review.summary["승률(%)"] || 0).toFixed(1)}%`} />
                <KpiCard label="주간 실현수익" value={`${(review.summary["주간실현수익"] || 0) >= 0 ? "+" : ""}${fmt(review.summary["주간실현수익"] || 0)}${currency}`}
                  color={(review.summary["주간실현수익"] || 0) >= 0 ? "text-red-400" : "text-teal-400"}
                  sub={review.capital ? `원금대비 ${((review.summary["주간실현수익"] || 0) / review.capital * 100).toFixed(2)}%` : undefined} />
              </div>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <KpiCard label="승리 평균수익률" value={`${(review.summary["승리평균수익률(%)"] || 0) >= 0 ? "+" : ""}${(review.summary["승리평균수익률(%)"] || 0).toFixed(2)}%`} />
                <KpiCard label="패배 평균손실률" value={`${(review.summary["패배평균손실률(%)"] || 0).toFixed(2)}%`} />
              </div>
            </>
          )}
          {!review.summary && <p className="text-gray-600 text-sm mb-4">해당 주에 청산 거래가 없습니다.</p>}

          {/* 3. 진입 */}
          <h3 className="text-sm font-bold text-white mb-2">진입 ({(review.entries || []).length}건)</h3>
          {(review.entries || []).length > 0 ? (
            <div className="space-y-2 mb-4">
              {review.entries.map((e: any, i: number) => (
                <div key={i} className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                  <p className="text-sm font-medium text-white cursor-pointer hover:text-blue-400"
                    onClick={() => router.push(`/chart/${e["종목코드"]}`)}>
                    {e["종목명"]} <span className="text-gray-500">({e["종목코드"]})</span>
                  </p>
                  {(e["매수"] || []).map((b: any, j: number) => (
                    <p key={j} className="text-xs text-gray-400 mt-1">
                      {b["날짜"]} | {fmt(b["가격"])}{currency} x {b["수량"]}주 | 근거: {b["진입근거"] || "-"}
                      {b["손절가"] ? ` | 손절: ${fmt(b["손절가"])}${currency}` : ""}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          ) : <p className="text-gray-600 text-xs mb-4">해당 주 진입 없음</p>}

          {/* 4. 청산 */}
          <h3 className="text-sm font-bold text-white mb-2">청산 ({(review.exits || []).length}건)</h3>
          {(review.exits || []).length > 0 ? (
            <div className="space-y-2 mb-4">
              {review.exits.map((e: any, i: number) => (
                <div key={i} className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                  <p className="text-sm font-medium text-white cursor-pointer hover:text-blue-400"
                    onClick={() => router.push(`/chart/${e["종목코드"]}`)}>
                    {e["종목명"]} <span className="text-gray-500">({e["종목코드"]})</span>
                  </p>
                  {(e["매도"] || []).map((s: any, j: number) => (
                    <p key={j} className="text-xs text-gray-400 mt-1">
                      {s["날짜"]} | {fmt(s["가격"])}{currency} x {s["수량"]}주 | 사유: {s["사유"] || "-"}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          ) : <p className="text-gray-600 text-xs mb-4">해당 주 청산 없음</p>}

          {/* 5. 진입+청산 */}
          {(review.both || []).length > 0 && (
            <>
              <h3 className="text-sm font-bold text-white mb-2">진입+청산 ({review.both.length}건)</h3>
              <div className="space-y-2 mb-4">
                {review.both.map((e: any, i: number) => (
                  <div key={i} className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                    <p className="text-sm font-medium text-white cursor-pointer hover:text-blue-400"
                      onClick={() => router.push(`/chart/${e["종목코드"]}`)}>
                      {e["종목명"]} <span className="text-gray-500">({e["종목코드"]})</span>
                    </p>
                    <p className="text-xs text-gray-500 mt-1">매수:</p>
                    {(e["매수"] || []).map((b: any, j: number) => (
                      <p key={`b${j}`} className="text-xs text-gray-400 ml-2">
                        {b["날짜"]} | {fmt(b["가격"])}{currency} x {b["수량"]}주 | 근거: {b["진입근거"] || "-"}
                      </p>
                    ))}
                    <p className="text-xs text-gray-500 mt-1">매도:</p>
                    {(e["매도"] || []).map((s: any, j: number) => (
                      <p key={`s${j}`} className="text-xs text-gray-400 ml-2">
                        {s["날짜"]} | {fmt(s["가격"])}{currency} x {s["수량"]}주 | 사유: {s["사유"] || "-"}
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function BalanceTab({ market, currency, onReload }: { market: "KR" | "US"; currency: string; onReload: () => void }) {
  const fmt = (n: number) => _fmt(n, currency);
  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
  const [capital, setCapital] = useState(0);
  const [flows, setFlows] = useState<any[]>([]);
  const [sysBalance, setSysBalance] = useState<any>(null);
  const [flowForm, setFlowForm] = useState({ date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), type: "입금", amount: "", note: "" });
  const [adjForm, setAdjForm] = useState({ date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), actual: "" });
  const [msg, setMsg] = useState("");

  const load = () => {
    const safe = (p: Promise<any>) => p.catch(() => null);
    safe(fetch(`${API}/portfolio/capital?market=${market}`).then((r) => r.json())).then((d) => {
      if (d) { setCapital(d.capital || 0); setFlows(d.flows || []); }
    });
    safe(fetch(`${API}/portfolio/capital/balance?market=${market}`).then((r) => r.json())).then(setSysBalance);
  };

  useEffect(() => { load(); }, [market]);

  const handleAddFlow = async () => {
    const amount = Number(flowForm.amount);
    if (!amount || amount <= 0) { setMsg("금액을 입력해주세요."); return; }
    const signed = flowForm.type === "입금" ? amount : -amount;
    await fetch(`${API}/portfolio/capital/flow?market=${market}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: flowForm.date, amount: signed, note: flowForm.note }),
    });
    setMsg("저장 완료!"); setFlowForm({ ...flowForm, amount: "", note: "" });
    load(); onReload();
    setTimeout(() => setMsg(""), 3000);
  };

  const handleDelete = async (flowId: string) => {
    await fetch(`${API}/portfolio/capital/flow/${flowId}?market=${market}`, { method: "DELETE" });
    load(); onReload();
  };

  const handleAdjust = async () => {
    const actual = Number(adjForm.actual);
    if (!actual || actual <= 0) { setMsg("실제 예수금을 입력해주세요."); return; }
    const sysDeposit = sysBalance?.deposit || 0;
    const diff = actual - sysDeposit;
    if (Math.abs(diff) < 1) { setMsg("차이가 없습니다."); return; }
    await fetch(`${API}/portfolio/capital/flow?market=${market}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: adjForm.date, amount: diff,
        note: `잔액조정 (증권사 예수금 ${actual.toLocaleString()} - 추정 ${sysDeposit.toLocaleString()} = ${diff >= 0 ? "+" : ""}${diff.toLocaleString()})`,
      }),
    });
    setMsg(`조정 완료: ${diff >= 0 ? "+" : ""}${fmt(diff)}${currency}`);
    setAdjForm({ ...adjForm, actual: "" });
    load(); onReload();
    setTimeout(() => setMsg(""), 3000);
  };

  return (
    <div>
      {/* 입출금 입력 */}
      <h3 className="text-sm font-bold text-white mb-3">원금 입출금 관리</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-2 text-sm">
        <input type="date" value={flowForm.date} onChange={(e) => setFlowForm({ ...flowForm, date: e.target.value })}
          className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
        <select value={flowForm.type} onChange={(e) => setFlowForm({ ...flowForm, type: e.target.value })}
          className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white">
          <option value="입금">입금</option><option value="출금">출금</option>
        </select>
        <input type="number" placeholder={`금액 (${currency})`} value={flowForm.amount}
          onChange={(e) => setFlowForm({ ...flowForm, amount: e.target.value })}
          className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
        <input placeholder="메모" value={flowForm.note} onChange={(e) => setFlowForm({ ...flowForm, note: e.target.value })}
          className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
      </div>
      <button onClick={handleAddFlow}
        className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white mb-4">저장</button>
      {msg && <span className="ml-3 text-sm text-green-400">{msg}</span>}

      {/* 현재 원금 + 입출금 이력 */}
      <div className="bg-[#161b22] rounded-lg p-4 border border-gray-800 mb-4 max-w-xs">
        <p className="text-xs text-gray-500">현재 원금 합계</p>
        <p className="text-2xl font-bold text-white">{fmt(capital)}{currency}</p>
      </div>

      {flows.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm text-gray-500 mb-2">입출금 이력</h3>
          <div className="overflow-x-auto border border-gray-800 rounded-lg">
            <table className="w-full text-sm">
              <thead><tr className="bg-[#161b22] border-b border-gray-800 text-gray-500 text-xs">
                <th className="px-3 py-2 text-left">날짜</th>
                <th className="px-3 py-2 text-right">금액</th>
                <th className="px-3 py-2 text-left">메모</th>
                <th className="px-3 py-2 text-center w-12"></th>
              </tr></thead>
              <tbody>
                {flows.map((f: any) => {
                  const amt = f.amount ?? f["금액(원)"] ?? f["금액"] ?? 0;
                  const id = f.id || f["id"] || "";
                  return (
                    <tr key={id || Math.random()} className="border-b border-gray-800/50">
                      <td className="px-3 py-1.5 text-gray-400">{f.date || f["날짜"]}</td>
                      <td className={`px-3 py-1.5 text-right font-medium ${amt >= 0 ? "text-red-400" : "text-teal-400"}`}>
                        {amt >= 0 ? "+" : ""}{fmt(amt)}{currency}
                      </td>
                      <td className="px-3 py-1.5 text-gray-500">{f.note || f["메모"] || ""}</td>
                      <td className="px-3 py-1.5 text-center">
                        {id && (
                          <button onClick={() => handleDelete(id)}
                            className="text-xs text-red-400 hover:text-red-300">삭제</button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 실잔액 조정 */}
      <h3 className="text-sm font-bold text-white mb-2">예수금 조정</h3>
      <p className="text-xs text-gray-600 mb-3">증권사 예수금(주문가능금액)과 시스템 추정 예수금의 차이를 조정합니다. 보유종목 평가와 무관하게 비교할 수 있습니다.</p>

      {sysBalance && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
          <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
            <p className="text-xs text-gray-500">시스템 추정 예수금</p>
            <p className="text-lg font-bold text-white">{fmt(sysBalance.deposit)}{currency}</p>
            <p className="text-xs text-gray-600">
              원금 {fmt(sysBalance.capital)} + 실현손익 {fmt(sysBalance.cum_pnl)} - 매수금액 {fmt(sysBalance.invested)}
            </p>
          </div>
          <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
            <p className="text-xs text-gray-500">증권사 예수금 입력</p>
            <div className="flex gap-2 mt-1">
              <input type="number" placeholder={`예수금 (${currency})`} value={adjForm.actual}
                onChange={(e) => setAdjForm({ ...adjForm, actual: e.target.value })}
                className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white text-sm flex-1" />
            </div>
            <div className="mt-1">
              <input type="date" value={adjForm.date} onChange={(e) => setAdjForm({ ...adjForm, date: e.target.value })}
                className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white text-sm w-full" />
            </div>
            <button onClick={handleAdjust}
              className="mt-2 px-3 py-1 bg-yellow-600 hover:bg-yellow-700 rounded text-xs text-white">차이 조정</button>
          </div>
          {adjForm.actual && Number(adjForm.actual) > 0 && (
            <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
              <p className="text-xs text-gray-500">차이</p>
              {(() => {
                const diff = Number(adjForm.actual) - (sysBalance.deposit || 0);
                return (
                  <>
                    <p className={`text-lg font-bold ${diff >= 0 ? "text-red-400" : "text-teal-400"}`}>
                      {diff >= 0 ? "+" : ""}{fmt(diff)}{currency}
                    </p>
                    <p className="text-xs text-gray-600">
                      {diff > 0 ? "시스템이 비용을 과대 추정" : diff < 0 ? "시스템이 비용을 과소 추정" : "일치"}
                    </p>
                  </>
                );
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function JournalTab() {
  const [mode, setMode] = useState<"write" | "view">("write");
  const [date, setDate] = useState(() => new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10));
  const [krPositions, setKrPositions] = useState<any[]>([]);
  const [usPositions, setUsPositions] = useState<any[]>([]);
  const [memos, setMemos] = useState<Record<string, string>>({});
  const [extraNotes, setExtraNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  // 조회 모드
  const [dates, setDates] = useState<string[]>([]);
  const [viewDate, setViewDate] = useState("");
  const [viewData, setViewData] = useState<any>(null);

  const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

  // 작성 모드: 보유종목 + 기존 일지 로드
  const [jLoading, setJLoading] = useState(false);
  useEffect(() => {
    if (mode !== "write") return;
    let cancelled = false;
    setJLoading(true);

    (async () => {
      try {
        const [krRes, usRes, journalRes] = await Promise.all([
          fetch(`${API}/portfolio/positions?market=KR`).then((r) => r.json()).catch(() => ({ data: [] })),
          fetch(`${API}/portfolio/positions?market=US`).then((r) => r.json()).catch(() => ({ data: [] })),
          fetch(`${API}/journal/${date}`).then((r) => r.json()).catch(() => ({})),
        ]);
        if (cancelled) return;

        setKrPositions(krRes?.data || []);
        setUsPositions(usRes?.data || []);

        const existing: Record<string, string> = {};
        const entries = journalRes?.entries || [];
        if (Array.isArray(entries)) entries.forEach((e: any) => { existing[e["종목코드"]] = e["메모"] || ""; });
        setMemos(existing);
        setExtraNotes(journalRes?.extra_notes || "");
      } catch {}
      if (!cancelled) setJLoading(false);
    })();

    return () => { cancelled = true; };
  }, [mode, date]);

  // 조회 모드: 날짜 목록
  useEffect(() => {
    if (mode !== "view") return;
    fetchApi<any>("/journal/dates").then((d) => {
      const list = Array.isArray(d) ? d : (d?.dates || []);
      setDates(list);
      if (list.length > 0) setViewDate((prev) => prev || list[list.length - 1]);
    }).catch(() => setDates([]));
  }, [mode]);

  // 조회 모드: 선택 날짜 일지 로드
  useEffect(() => {
    if (mode !== "view" || !viewDate) return;
    fetchApi<any>(`/journal/${viewDate}`).then(setViewData).catch(() => setViewData(null));
  }, [mode, viewDate]);

  const handleSave = async () => {
    setSaving(true);
    const entries = [...krPositions, ...usPositions]
      .filter((p) => (memos[p["종목코드"]] || "").trim())
      .map((p) => ({
        "종목코드": p["종목코드"],
        "종목명": p["종목명"],
        "시장": String(p["종목코드"]).match(/^[0-9]+$/) ? "KR" : "US",
        "메모": memos[p["종목코드"]],
      }));
    try {
      await fetch(`${API}/journal/${date}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, entries, extra_notes: extraNotes.trim() }),
      });
      setMsg(`${date} 일지 저장 완료!`);
      setTimeout(() => setMsg(""), 3000);
    } catch { setMsg("저장 실패"); }
    setSaving(false);
  };

  const handleDelete = async () => {
    await fetch(`${API}/journal/${viewDate}`, { method: "DELETE" });
    setViewData(null);
    setDates((prev) => prev.filter((d) => d !== viewDate));
    setViewDate("");
  };

  return (
    <div>
      {/* 모드 전환 */}
      <div className="flex gap-2 mb-4">
        <button onClick={() => setMode("write")}
          className={`px-3 py-1 rounded text-sm ${mode === "write" ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400"}`}>
          작성
        </button>
        <button onClick={() => setMode("view")}
          className={`px-3 py-1 rounded text-sm ${mode === "view" ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400"}`}>
          조회
        </button>
      </div>

      {mode === "write" && (
        <div>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="bg-[#0d1117] border border-gray-700 rounded px-3 py-1.5 text-sm text-white mb-4" />

          {jLoading && <p className="text-gray-500 text-sm mb-3 animate-pulse">보유종목 로딩 중...</p>}

          {/* 한국 보유종목 */}
          {krPositions.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-bold text-white mb-2">한국 보유종목</h3>
              {krPositions.map((p: any) => (
                <div key={p["종목코드"]} className="mb-3">
                  <p className="text-sm text-gray-300">
                    <span className="font-medium text-white">{p["종목명"]}</span>
                    <span className="text-gray-500 ml-1">({p["종목코드"]})</span>
                    <span className="text-gray-600 ml-2">매수가: {_fmt(p["평균매수가"])}원</span>
                    <span className="text-gray-600 ml-2">손절가: {_fmt(p["손절가"])}원</span>
                    {p["1차익절가"] > 0 && <span className="text-gray-600 ml-2">익절: {_fmt(p["1차익절가"])}원</span>}
                  </p>
                  <textarea
                    value={memos[p["종목코드"]] || ""}
                    onChange={(e) => setMemos({ ...memos, [p["종목코드"]]: e.target.value })}
                    placeholder="현재 상태 분석 + 오늘 행동 계획"
                    className="w-full mt-1 bg-[#0d1117] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600 resize-y"
                    rows={3}
                  />
                </div>
              ))}
            </div>
          )}

          {/* 미국 보유종목 */}
          {usPositions.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-bold text-white mb-2">미국 보유종목</h3>
              {usPositions.map((p: any) => (
                <div key={p["종목코드"]} className="mb-3">
                  <p className="text-sm text-gray-300">
                    <span className="font-medium text-white">{p["종목명"]}</span>
                    <span className="text-gray-500 ml-1">({p["종목코드"]})</span>
                    <span className="text-gray-600 ml-2">매수가: ${p["평균매수가"]?.toFixed(2)}</span>
                    <span className="text-gray-600 ml-2">손절가: ${p["손절가"]?.toFixed(2)}</span>
                    {p["1차익절가"] > 0 && <span className="text-gray-600 ml-2">익절: ${p["1차익절가"]?.toFixed(2)}</span>}
                  </p>
                  <textarea
                    value={memos[p["종목코드"]] || ""}
                    onChange={(e) => setMemos({ ...memos, [p["종목코드"]]: e.target.value })}
                    placeholder="현재 상태 분석 + 오늘 행동 계획"
                    className="w-full mt-1 bg-[#0d1117] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600 resize-y"
                    rows={3}
                  />
                </div>
              ))}
            </div>
          )}
          {!jLoading && krPositions.length === 0 && usPositions.length === 0 && (
            <p className="text-gray-600 text-sm mb-4">보유 종목이 없습니다.</p>
          )}

          {/* 추가 메모 */}
          <div className="mb-4">
            <h3 className="text-sm font-bold text-white mb-2">추가 메모</h3>
            <textarea
              value={extraNotes}
              onChange={(e) => setExtraNotes(e.target.value)}
              placeholder="신규 관심종목, 시장 동향, 기타 메모"
              className="w-full bg-[#0d1117] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600 resize-y"
              rows={4}
            />
          </div>

          <button onClick={handleSave} disabled={saving}
            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white disabled:opacity-50">
            {saving ? "저장 중..." : "일지 저장"}
          </button>
          {msg && <span className="ml-3 text-sm text-green-400">{msg}</span>}
        </div>
      )}

      {mode === "view" && (
        <div>
          {dates.length === 0 ? (
            <p className="text-gray-600 py-4">작성된 일지가 없습니다.</p>
          ) : (
            <>
              <div className="flex gap-1 flex-wrap mb-4">
                {(Array.isArray(dates) ? [...dates] : []).reverse().map((d) => (
                  <button key={d} onClick={() => setViewDate(d)}
                    className={`px-2.5 py-1 rounded text-xs ${viewDate === d ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-500 hover:text-white"}`}>
                    {d}
                  </button>
                ))}
              </div>

              {viewData && (
                <div>
                  <p className="text-xs text-gray-600 mb-3">저장: {(viewData.saved_at || "").slice(0, 16)}</p>

                  {(viewData.entries || []).map((e: any, i: number) => (
                    <div key={i} className="mb-3 bg-[#161b22] rounded-lg p-3 border border-gray-800">
                      <p className="text-sm font-medium text-white">
                        {e["시장"] === "KR" ? "🇰🇷" : "🇺🇸"} {e["종목명"]} <span className="text-gray-500">({e["종목코드"]})</span>
                      </p>
                      <p className="text-sm text-gray-300 mt-1 whitespace-pre-wrap">{e["메모"]}</p>
                    </div>
                  ))}

                  {viewData.extra_notes && (
                    <div className="mb-3 bg-[#161b22] rounded-lg p-3 border border-gray-800">
                      <p className="text-sm font-medium text-white">추가 메모</p>
                      <p className="text-sm text-gray-300 mt-1 whitespace-pre-wrap">{viewData.extra_notes}</p>
                    </div>
                  )}

                  <button onClick={handleDelete}
                    className="px-3 py-1 rounded text-xs bg-red-900/30 text-red-400 hover:bg-red-900/50 border border-red-900/50 mt-2">
                    이 일지 삭제
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function PortfolioPage() {
  const [market, setMarket] = useState<"KR" | "US">("KR");
  const [tab, setTab] = useState(0);
  const [positions, setPositions] = useState<any[]>([]);
  const [tradeLog, setTradeLog] = useState<any[]>([]);
  const [oti, setOti] = useState<any>(null);
  const [otiHistory, setOtiHistory] = useState<any[]>([]);
  const [exposureHistory, setExposureHistory] = useState<any[]>([]);
  const [pnlData, setPnlData] = useState<any[]>([]);
  // 성과 기간 필터
  const [perfUnit, setPerfUnit] = useState<"all" | "year" | "quarter" | "month" | "week">("all");
  const [perfPeriod, setPerfPeriod] = useState<string>("");
  const [tickerPnl, setTickerPnl] = useState<any[]>([]);
  const [monthlyPerf, setMonthlyPerf] = useState<any[]>([]);
  const [capitalInfo, setCapitalInfo] = useState<any>(null);
  const [marketScore, setMarketScore] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  // 매수/매도 폼
  const [showBuyForm, setShowBuyForm] = useState(false);
  const [showSellForm, setShowSellForm] = useState(false);
  const [buyForm, setBuyForm] = useState({ ticker: "", name: "", date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), price: "", quantity: "", stop_loss: "", entry_reason: "PB20", memo: "", take_profit: "" });
  const [reentryWarning, setReentryWarning] = useState<any>(null);
  const [buySuggestions, setBuySuggestions] = useState<any[]>([]);
  const [sellForm, setSellForm] = useState({ position_id: "", date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), price: "", quantity: "", reason: "" });
  const [showStopForm, setShowStopForm] = useState(false);
  const [stopForm, setStopForm] = useState({ position_id: "", date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), price: "", note: "" });
  const [formMsg, setFormMsg] = useState("");

  const currency = market === "KR" ? "원" : "$";
  const fmt = (n: number) => _fmt(n, currency);

  const [pricesLoading, setPricesLoading] = useState(false);
  const safe = (p: Promise<any>) => p.catch(() => null);

  const loadAll = () => {
    setLoading(true);

    // 1단계: 포지션 + 거래이력 먼저 (빠름)
    Promise.all([
      safe(fetchApi(`/portfolio/positions?market=${market}`)),
      safe(fetchApi(`/portfolio/trade-log?market=${market}`)),
    ]).then(([pos, log]: any[]) => {
      setPositions(pos?.data || []);
      setTradeLog((log?.data || []).reverse());
      setLoading(false); // 여기서 로딩 해제 → 화면 즉시 표시

      // 2단계: 현재가 비동기
      if (pos?.data?.length) {
        setPricesLoading(true);
        fetchApi<any>(`/portfolio/positions/prices?market=${market}`)
          .then((pr) => {
            const prices = pr?.prices || {};
            setPositions((prev) => prev.map((p: any) => {
              const cur = prices[p["종목코드"]];
              if (!cur) return p;
              const avg = p["평균매수가"] || 0;
              const qty = p["수량"] || 0;
              const sl = p["손절가"] || 0;
              return {
                ...p,
                "현재가": cur,
                "수익률(%)": avg > 0 ? Math.round((cur / avg - 1) * 10000) / 100 : null,
                "평가금액": Math.round(cur * qty),
                "손절경고": cur > 0 && sl > 0 && cur <= sl ? "손절선 이탈" : "",
              };
            }));
          })
          .catch(() => {})
          .finally(() => setPricesLoading(false));
      }
    });

    // 3단계: 나머지 데이터 병렬 로드 (UI 블로킹 없음)
    safe(fetchApi(`/portfolio/oti?market=${market}`)).then(setOti);
    safe(fetchApi(`/portfolio/oti/history?market=${market}&lookback=60`)).then((r) => setOtiHistory(r?.data || []));
    safe(fetchApi(`/portfolio/exposure/history?market=${market}&lookback=90`)).then((r) => setExposureHistory(r?.data || []));
    safe(fetchApi(`/portfolio/pnl/realized?market=${market}`)).then((r) => setPnlData(r?.data || []));
    safe(fetchApi(`/portfolio/pnl/by-ticker?market=${market}`)).then((r) => setTickerPnl(r?.data || []));
    safe(fetchApi(`/portfolio/monthly-performance?market=${market}`)).then((r) => setMonthlyPerf(r?.data || []));
    safe(fetchApi(`/portfolio/capital?market=${market}`)).then(setCapitalInfo);
    safe(fetchApi(`/portfolio/market-score?market=${market}&lookback=90`)).then(setMarketScore);
  };

  useEffect(() => { loadAll(); }, [market]);

  // 성과 KPI 계산 (Streamlit 12개 KPI 동일)
  const calcKpi = (data: any[]) => {
    if (!data.length) return null;
    const pnlCol = data[0]["비용차감손익(원)"] !== undefined ? "비용차감손익(원)" : "비용차감손익($)";
    const grossCol = data[0]["실현손익(원)"] !== undefined ? "실현손익(원)" : "실현손익($)";
    const feeCol = data[0]["거래비용(원)"] !== undefined ? "거래비용(원)" : "거래비용($)";
    const retCol = "수익률(%)";
    const wins = data.filter((r) => r[retCol] > 0);
    const losses = data.filter((r) => r[retCol] <= 0);
    const n = data.length;

    const totalNet = data.reduce((s, r) => s + (r[pnlCol] || 0), 0);
    const totalGross = data.reduce((s, r) => s + (r[grossCol] || 0), 0);
    const totalFees = data.reduce((s, r) => s + (r[feeCol] || 0), 0);
    const winRate = (wins.length / n) * 100;

    // 가중평균 수익률 (매수금액 가중)
    const buyCost = (r: any) => (r["평균매수가"] || 0) * (r["수량"] || r["청산수량"] || 0);
    const totalInv = data.reduce((s, r) => s + buyCost(r), 0);
    const wAvgRet = totalInv > 0 ? data.reduce((s, r) => s + (r[retCol] || 0) * buyCost(r), 0) / totalInv : 0;
    const wAvgWin = (() => { const wInv = wins.reduce((s, r) => s + buyCost(r), 0); return wInv > 0 ? wins.reduce((s, r) => s + (r[retCol] || 0) * buyCost(r), 0) / wInv : 0; })();
    const wAvgLoss = (() => { const lInv = losses.reduce((s, r) => s + buyCost(r), 0); return lInv > 0 ? losses.reduce((s, r) => s + (r[retCol] || 0) * buyCost(r), 0) / lInv : 0; })();

    // 목표손절 위반
    const lossesWithTarget = losses.filter((r) => r["목표손절률(%)"] != null);
    const violations = lossesWithTarget.filter((r) => r[retCol] < r["목표손절률(%)"]);
    const violationRate = lossesWithTarget.length > 0 ? (violations.length / lossesWithTarget.length) * 100 : 0;
    const avgPlannedLoss = lossesWithTarget.length > 0 ? lossesWithTarget.reduce((s, r) => s + r["목표손절률(%)"], 0) / lossesWithTarget.length : null;

    // 원금 대비
    const capital = capitalInfo?.capital || 0;
    const turnover = capital > 0 ? totalInv / capital : null;
    const capitalRet = capital > 0 ? (totalGross / capital) * 100 : null;

    // R/R, 보유일
    const rrVals = data.filter((r) => r["RR"] != null);
    const avgRR = rrVals.length ? rrVals.reduce((s, r) => s + r["RR"], 0) / rrVals.length : null;
    const avgHoldWin = wins.length ? wins.reduce((s, r) => s + (r["보유일수"] || 0), 0) / wins.length : null;
    const avgHoldLoss = losses.length ? losses.reduce((s, r) => s + (r["보유일수"] || 0), 0) / losses.length : null;

    return {
      totalNet, totalGross, totalFees, totalInv,
      count: n, wins: wins.length, losses: losses.length, winRate,
      wAvgRet, wAvgWin, wAvgLoss,
      violations: violations.length, violationRate, avgPlannedLoss,
      turnover, capitalRet, avgRR, avgHoldWin, avgHoldLoss,
    };
  };

  const calcByEntry = (data: any[]) => {
    const map: Record<string, any[]> = {};
    data.forEach((r) => { const key = r["진입근거"] || "기타"; if (!map[key]) map[key] = []; map[key].push(r); });
    return Object.entries(map).map(([entry, rows]) => ({ entry, ...calcKpi(rows) }));
  };

  // ── 누적 수익 곡선 렌더 ──
  const renderEquityCurve = (data: any[], dateCol: string) => {
    if (data.length < 2) return null;
    const pnlKey = data[0]["실현손익(원)"] !== undefined ? "실현손익(원)" : "실현손익($)";
    const ccy = data[0]["실현손익(원)"] !== undefined ? "원" : "$";
    const isKRW = ccy === "원";

    // 같은 날짜 합산 + 정렬
    const dateMap: Record<string, number> = {};
    data.forEach((r) => {
      const d = r[dateCol] || getDateField(r);
      if (d) dateMap[d] = (dateMap[d] || 0) + (r[pnlKey] || 0);
    });
    const sortedDates = Object.keys(dateMap).sort();
    if (sortedDates.length < 1) return null;

    // 시작점 0 추가
    const firstDate = sortedDates[0];
    const startDate = firstDate.slice(0, 8) + "01";
    const allDates = [startDate, ...sortedDates];
    let cum = 0;
    const cumData = [0, ...sortedDates.map((d) => { cum += dateMap[d]; return cum; })];
    const labels = allDates.map((d) => d.slice(5));
    const lastCum = cumData[cumData.length - 1];
    const color = lastCum >= 0 ? "#F87171" : "#34D399";
    const fmtVal = (v: number) => isKRW ? `${v >= 0 ? "+" : ""}${(v / 10000).toFixed(0)}만` : `${v >= 0 ? "+" : ""}$${(v / 1000).toFixed(0)}k`;

    return (
      <div className="mt-6">
        <h3 className="text-sm text-gray-500 mb-2">누적 수익 곡선</h3>
        <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl overflow-hidden">
          <ReactECharts style={{ height: 240 }} option={{
            ...chartBase,
            xAxis: { type: "category", data: labels, ...axisStyle, boundaryGap: false },
            yAxis: { type: "value", ...axisStyle, axisLabel: { ...axisStyle.axisLabel, formatter: (v: number) => fmtVal(v) } },
            tooltip: { trigger: "axis", backgroundColor: "rgba(22,27,34,0.95)", borderColor: "#333", textStyle: { color: "#ddd" },
              formatter: (params: any) => { const p = params[0]; return `${allDates[p.dataIndex]}<br/>누적: <b>${p.value >= 0 ? "+" : ""}${p.value.toLocaleString()}${ccy}</b>`; },
            },
            series: [
              {
                type: "line", smooth: 0.4, data: cumData,
                symbol: "circle", symbolSize: 5,
                lineStyle: { color, width: 2.5, shadowColor: `${color}44`, shadowBlur: 6 },
                itemStyle: { color },
                label: { show: cumData.length <= 40, formatter: (p: any) => p.value !== 0 ? fmtVal(p.value) : "", fontSize: 9, color: "#e0e0e0", position: "top", distance: 8 },
                areaStyle: {
                  color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [{ offset: 0, color: `${color}25` }, { offset: 1, color: `${color}00` }],
                  },
                },
              },
              { type: "line", data: allDates.map(() => 0), lineStyle: { color: "#444", width: 1, type: [4, 4] }, symbol: "none" },
            ],
          }} />
        </div>
      </div>
    );
  };

  // ── 수익률 분포 렌더 ──
  const renderReturnDist = (data: any[]) => {
    const rets = data.map((r) => r["수익률(%)"]).filter((v) => v != null) as number[];
    if (rets.length < 2) return null;

    const mean = rets.reduce((s, v) => s + v, 0) / rets.length;
    const std = Math.sqrt(rets.reduce((s, v) => s + (v - mean) ** 2, 0) / (rets.length - 1));
    const maxRet = Math.max(...rets);
    const minRet = Math.min(...rets);

    // 자동 구간 (최대 15개 빈)
    const range = maxRet - minRet;
    const binSize = Math.max(1, Math.ceil(range / 15));
    const minEdge = Math.floor(minRet / binSize) * binSize;
    const maxEdge = Math.ceil(maxRet / binSize) * binSize;
    const bins: { label: string; count: number; pct: string; isPositive: boolean }[] = [];
    for (let b = minEdge; b < maxEdge; b += binSize) {
      const bEnd = b + binSize;
      const count = rets.filter((v) => v >= b && v < bEnd).length;
      const pct = rets.length > 0 ? ((count / rets.length) * 100).toFixed(1) : "0";
      bins.push({ label: `${b}~${bEnd}%`, count, pct, isPositive: (b + bEnd) / 2 >= 0 });
    }

    return (
      <div className="mt-6">
        <h3 className="text-sm text-gray-500 mb-2">수익률 분포 <span className="text-xs text-gray-600 ml-2">평균 {mean >= 0 ? "+" : ""}{mean.toFixed(1)}%</span></h3>
        <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl overflow-hidden">
          <ReactECharts style={{ height: 220 }} option={{
            ...chartBase,
            xAxis: { type: "category", data: bins.map((b) => b.label), ...axisStyle, axisLabel: { ...axisStyle.axisLabel, rotate: -30, fontSize: 9 } },
            yAxis: { type: "value", ...axisStyle, minInterval: 1 },
            tooltip: { trigger: "axis", backgroundColor: "rgba(22,27,34,0.95)", borderColor: "#333", textStyle: { color: "#ddd" },
              formatter: (params: any) => { const p = params[0]; const bin = bins[p.dataIndex]; return `${bin.label}<br/>빈도: <b>${bin.count}건</b> (${bin.pct}%)`; },
            },
            series: [{
              type: "bar", data: bins.map((b) => ({
                value: b.count,
                itemStyle: { color: b.isPositive ? "rgba(248,113,113,0.7)" : "rgba(52,211,153,0.7)", borderRadius: [3, 3, 0, 0] },
              })),
              label: { show: true, position: "top", fontSize: 9, color: "#AAA", formatter: (p: any) => bins[p.dataIndex].count > 0 ? `${bins[p.dataIndex].pct}%` : "" },
              barGap: "5%",
            }],
          }} />
        </div>

        {/* 통계 카드 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
          <KpiCard label="평균수익률" value={`${mean >= 0 ? "+" : ""}${mean.toFixed(2)}%`} color={mean >= 0 ? "text-red-400" : "text-teal-400"} />
          <KpiCard label="표준편차" value={`${std.toFixed(2)}%`} />
          <KpiCard label="최대" value={`${maxRet >= 0 ? "+" : ""}${maxRet.toFixed(2)}%`} color="text-red-400" />
          <KpiCard label="최소" value={`${minRet >= 0 ? "+" : ""}${minRet.toFixed(2)}%`} color="text-teal-400" />
        </div>
      </div>
    );
  };

  // 기간 필터링
  const getWeekKey = (dateStr: string) => {
    const d = new Date(dateStr);
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1); // Monday
    const mon = new Date(d.setDate(diff));
    return mon.toISOString().slice(0, 10);
  };
  const getQuarterKey = (dateStr: string) => {
    const m = parseInt(dateStr.slice(5, 7));
    const q = Math.ceil(m / 3);
    return `${dateStr.slice(0, 4)}-Q${q}`;
  };

  const getPeriodKey = (dateStr: string, unit: string) => {
    if (unit === "year") return dateStr.slice(0, 4);
    if (unit === "quarter") return getQuarterKey(dateStr);
    if (unit === "month") return dateStr.slice(0, 7);
    if (unit === "week") return getWeekKey(dateStr);
    return "all";
  };

  const getAvailablePeriods = (data: any[], unit: string) => {
    if (unit === "all") return [];
    const set = new Set<string>();
    data.forEach((r) => {
      const d = getDateField(r);
      if (d) set.add(getPeriodKey(d, unit));
    });
    return Array.from(set).sort().reverse();
  };

  const getDateField = (r: any) => r["날짜"] || r["청산일"] || r["date"] || "";

  const filterByPeriod = (data: any[], unit: string, period: string) => {
    if (unit === "all" || !period) return data;
    return data.filter((r) => {
      const d = getDateField(r);
      return d && getPeriodKey(d, unit) === period;
    });
  };

  const perfPeriods = getAvailablePeriods(pnlData, perfUnit);
  const perfPeriodsTicker = getAvailablePeriods(tickerPnl, perfUnit);

  // unit 변경 시 최신 기간 자동 선택
  useEffect(() => {
    if (perfUnit === "all") { setPerfPeriod(""); return; }
    const periods = getAvailablePeriods(pnlData, perfUnit);
    setPerfPeriod(periods[0] || "");
  }, [perfUnit, pnlData]);

  const filteredPnl = filterByPeriod(pnlData, perfUnit, perfPeriod);
  const filteredTickerPnl = filterByPeriod(tickerPnl, perfUnit, perfPeriod);

  const periodLabel = (p: string, unit: string) => {
    if (unit === "week") return `${p} 주`;
    if (unit === "quarter") return p;
    return p;
  };

  // 보유현황 합계
  const totalCost = positions.reduce((s, p) => s + (p["평균매수가"] || 0) * (p["수량"] || 0), 0);
  const totalEval = positions.reduce((s, p) => s + (p["평가금액"] || p["현재가"] * p["수량"] || 0), 0);
  const totalUnreal = totalEval - totalCost;
  const totalRetPct = totalCost > 0 ? (totalUnreal / totalCost * 100) : 0;

  // 매수 제출
  const submitBuy = async () => {
    try {
      await fetchApi(`/portfolio/buy?market=${market}`, );
      setFormMsg("매수 등록 완료");
      setShowBuyForm(false);
      loadAll();
    } catch (e: any) { setFormMsg("오류: " + e.message); }
  };

  // 공통 차트 스타일
  const chartBase = {
    backgroundColor: "transparent",
    grid: { left: 45, right: 15, top: 35, bottom: 28 },
    tooltip: {
      trigger: "axis" as const,
      backgroundColor: "rgba(22,27,34,0.95)",
      borderColor: "#333",
      textStyle: { color: "#ddd", fontSize: 12 },
      axisPointer: { lineStyle: { color: "rgba(255,255,255,0.15)" } },
    },
  };
  const axisStyle = {
    axisLabel: { color: "#666", fontSize: 11 },
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: "rgba(255,255,255,0.05)" } },
  };

  // OTI 차트 옵션
  const otiMax = otiHistory.length > 0 ? Math.max(...otiHistory.map((d: any) => d.oti), 250) + 80 : 300;
  const otiChartOption = otiHistory.length > 0 ? {
    ...chartBase,
    xAxis: { type: "category", data: otiHistory.map((d: any) => d.date.slice(5)), ...axisStyle, boundaryGap: false },
    yAxis: { type: "value", min: 0, max: otiMax, ...axisStyle },
    legend: { show: true, textStyle: { color: "#777", fontSize: 10 }, right: 0, top: 0, itemWidth: 12, itemHeight: 8 },
    series: [
      {
        name: "OTI", type: "line", smooth: 0.4, data: otiHistory.map((d: any) => d.oti),
        lineStyle: { color: "#EF4444", width: 2.5, shadowColor: "rgba(239,68,68,0.3)", shadowBlur: 8 },
        itemStyle: { color: "#EF4444" }, symbol: "none",
        areaStyle: {
          color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: "rgba(239,68,68,0.25)" }, { offset: 1, color: "rgba(239,68,68,0)" }] },
        },
      },
      { name: "정상(100)", type: "line", data: otiHistory.map(() => 100), lineStyle: { color: "rgba(100,100,100,0.5)", width: 1, type: [4, 4] }, symbol: "none", itemStyle: { color: "#666" } },
      { name: "주의(200)", type: "line", data: otiHistory.map(() => 200), lineStyle: { color: "rgba(243,156,18,0.5)", width: 1, type: [4, 4] }, symbol: "none", itemStyle: { color: "#F39C12" } },
      { name: "WALK AWAY(500)", type: "line", data: otiHistory.map(() => 500), lineStyle: { color: "rgba(231,76,60,0.5)", width: 1, type: [4, 4] }, symbol: "none", itemStyle: { color: "#E74C3C" } },
    ],
  } : null;

  // 추세 대비 익스포져 판정
  const trendAlignment = (score: number, exposure: number, otiVal: number) => {
    let label = "";
    if (score >= 70) {
      if (exposure >= 80) label = "추세 순응";
      else if (exposure >= 50) label = "가속 필요";
      else label = "기회 미활용";
    } else if (score >= 30) {
      if (exposure >= 80) label = "과다 노출";
      else if (exposure >= 50) label = "중립";
      else label = "방어 적정";
    } else {
      if (exposure >= 80) label = "추세 역행";
      else if (exposure >= 50) label = "청산 미흡";
      else label = "관망 적정";
    }
    if (otiVal >= 200 && exposure < 50) label += " · 저노출 과매매";
    return label;
  };

  const curExposure = exposureHistory.length > 0 ? exposureHistory[exposureHistory.length - 1].exposure : 0;
  const curScore = marketScore?.current?.score || 50;
  const curOti = oti?.oti || 0;
  const alignLabel = trendAlignment(curScore, curExposure, curOti);
  const scoreLevelLabel = curScore >= 85 ? "최적" : curScore >= 70 ? "양호" : curScore >= 50 ? "보통" : curScore >= 30 ? "주의" : "위험";

  // 시장점수 + 익스포져 합산 차트 (날짜 merge)
  const trendChartOption = (() => {
    const msData = marketScore?.data || [];
    const expData = exposureHistory || [];
    if (!msData.length && !expData.length) return null;

    // 날짜 기준 merge
    const dateMap: Record<string, { score?: number; exposure?: number }> = {};
    msData.forEach((d: any) => { dateMap[d.date] = { ...dateMap[d.date], score: d.score }; });
    expData.forEach((d: any) => { dateMap[d.date] = { ...dateMap[d.date], exposure: d.exposure }; });
    const sortedDates = Object.keys(dateMap).sort();

    // ffill
    let lastScore = 50, lastExp = 0;
    const dates: string[] = [], scores: number[] = [], exps: number[] = [];
    sortedDates.forEach((d) => {
      const v = dateMap[d];
      if (v.score != null) lastScore = v.score;
      if (v.exposure != null) lastExp = v.exposure;
      dates.push(d.slice(5)); // MM-DD
      scores.push(lastScore);
      exps.push(Number(lastExp.toFixed(1)));
    });

    return {
      ...chartBase,
      xAxis: { type: "category", data: dates, ...axisStyle, boundaryGap: false },
      yAxis: { type: "value", min: 0, max: 105, ...axisStyle },
      legend: { show: true, data: ["시장점수", "익스포져"], textStyle: { color: "#777", fontSize: 10 }, right: 0, top: 0, itemWidth: 12, itemHeight: 8 },
      series: [
        {
          name: "시장점수", type: "line", smooth: 0.4, data: scores,
          lineStyle: { color: "#F87171", width: 2.5, shadowColor: "rgba(248,113,113,0.3)", shadowBlur: 6 },
          itemStyle: { color: "#F87171" }, symbol: "none",
          areaStyle: {
            color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: "rgba(248,113,113,0.15)" }, { offset: 1, color: "rgba(248,113,113,0)" }] },
          },
        },
        {
          name: "익스포져", type: "line", smooth: 0.4, data: exps,
          lineStyle: { color: "#34D399", width: 2.5, shadowColor: "rgba(52,211,153,0.3)", shadowBlur: 6 },
          itemStyle: { color: "#34D399" }, symbol: "none",
          areaStyle: {
            color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: "rgba(52,211,153,0.12)" }, { offset: 1, color: "rgba(52,211,153,0)" }] },
          },
        },
        { name: "85", type: "line", data: dates.map(() => 85), lineStyle: { color: "rgba(100,100,100,0.4)", width: 1, type: [4, 4] }, symbol: "none", itemStyle: { color: "#555" } },
        { name: "30", type: "line", data: dates.map(() => 30), lineStyle: { color: "rgba(100,100,100,0.4)", width: 1, type: [4, 4] }, symbol: "none", itemStyle: { color: "#555" } },
      ],
    };
  })();

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-4">포트폴리오</h1>

      <div className="flex items-center gap-4 mb-4">
          {tab !== 6 && (
          <div className="flex gap-1">
            {(["KR", "US"] as const).map((m) => (
              <button key={m} onClick={() => setMarket(m)}
                className={`px-3 py-1 rounded text-sm ${market === m ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
                {m === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}
              </button>
            ))}
          </div>
        )}
        <div className="flex gap-1 flex-wrap">
          {TABS.map((t, i) => (
            <button key={t} onClick={() => setTab(i)}
              className={`px-3 py-1 rounded text-sm ${tab === i ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
              {t}
            </button>
          ))}
        </div>
      </div>

      {loading && <LoadingSpinner text="포트폴리오 로딩 중" />}

      {/* ═══ 보유현황 ═══ */}
      {!loading && tab === 0 && (
        <div>
          {/* 요약 카드 */}
          {positions.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <KpiCard label="총 투자금액" value={`${fmt(totalCost)}${currency}`} />
              <KpiCard label="총 평가금액" value={`${fmt(totalEval)}${currency}`} />
              <KpiCard label="평가손익" value={`${totalUnreal >= 0 ? "+" : ""}${fmt(totalUnreal)}${currency}`}
                color={totalUnreal >= 0 ? "text-red-400" : "text-teal-400"} />
              <KpiCard label="수익률" value={`${totalRetPct >= 0 ? "+" : ""}${totalRetPct.toFixed(2)}%`}
                color={totalRetPct >= 0 ? "text-red-400" : "text-teal-400"} />
            </div>
          )}

          <p className="text-xs text-gray-500 mb-2">
            {positions.length}종목 보유 중
            {pricesLoading && <span className="ml-2 text-blue-400 animate-pulse">현재가 조회 중...</span>}
          </p>
          <DataTable columns={POSITION_COLUMNS} data={positions} tickerKey="종목코드" defaultSortKey="평가금액" defaultSortDir="desc" />

          {/* 매수/매도 입력 버튼 */}
          <div className="flex gap-2 mt-4">
            <button onClick={() => setShowBuyForm(!showBuyForm)}
              className="px-3 py-1.5 rounded text-sm bg-red-900/30 text-red-400 hover:bg-red-900/50 border border-red-900/50">
              {showBuyForm ? "▼ 매수 접기" : "▶ 매수 입력"}
            </button>
            <button onClick={() => setShowSellForm(!showSellForm)}
              className="px-3 py-1.5 rounded text-sm bg-blue-900/30 text-blue-400 hover:bg-blue-900/50 border border-blue-900/50">
              {showSellForm ? "▼ 매도 접기" : "▶ 매도 입력"}
            </button>
            <button onClick={() => setShowStopForm(!showStopForm)}
              className="px-3 py-1.5 rounded text-sm bg-yellow-900/30 text-yellow-400 hover:bg-yellow-900/50 border border-yellow-900/50">
              {showStopForm ? "▼ 손절가 접기" : "▶ 손절가 수정"}
            </button>
          </div>

          {formMsg && <p className="text-xs text-yellow-400 mt-2">{formMsg}</p>}

          {/* 매수 폼 */}
          {showBuyForm && (
            <div className="bg-[#161b22] rounded-lg p-4 border border-gray-800 mt-3">
              <h3 className="text-sm font-bold text-white mb-3">매수 입력</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div className="relative col-span-2">
                  <input placeholder="종목명 검색" value={buyForm.name} onChange={(e) => {
                    setBuyForm({ ...buyForm, name: e.target.value });
                    const q = e.target.value.trim();
                    if (q.length >= 1) {
                      fetch(`http://${typeof window !== "undefined" ? window.location.hostname : "localhost"}:8000/api/stocks/search?q=${encodeURIComponent(q)}&limit=8`)
                        .then((r) => r.json())
                        .then((items) => setBuySuggestions(items || []))
                        .catch(() => setBuySuggestions([]));
                    } else { setBuySuggestions([]); }
                  }}
                    className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white w-full" />
                  {buySuggestions.length > 0 && (
                    <div className="absolute left-0 right-0 top-full mt-1 bg-[#1c2128] border border-gray-700 rounded shadow-lg max-h-48 overflow-y-auto z-50">
                      {buySuggestions.map((item: any) => (
                        <button key={`${item.code}-${item.market}`} onClick={() => {
                          setBuyForm({ ...buyForm, ticker: item.code, name: item.name });
                          setBuySuggestions([]);
                          setReentryWarning(null);
                          fetch(`http://${typeof window !== "undefined" ? window.location.hostname : "localhost"}:8000/api/portfolio/reentry-check/${item.code}?market=${market}`)
                            .then((r) => r.json()).then(setReentryWarning).catch(() => {});
                        }}
                          className="w-full text-left px-3 py-1.5 hover:bg-[#2d333b] text-sm">
                          <span className="text-white">{item.name}</span>
                          <span className="text-gray-500 ml-1.5 text-xs">{item.code}</span>
                          <span className="text-gray-600 text-[10px] ml-1">{item.market}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <input type="date" value={buyForm.date} onChange={(e) => setBuyForm({ ...buyForm, date: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <select value={buyForm.entry_reason} onChange={(e) => setBuyForm({ ...buyForm, entry_reason: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white">
                  <option value="PB5">PB5</option><option value="PB20">PB20</option>
                  <option value="HB5">HB5</option><option value="HB20">HB20</option><option value="HB60">HB60</option><option value="HB100">HB100</option>
                  <option value="BO">BO</option>
                </select>
                <input type="number" placeholder="매수가" value={buyForm.price} onChange={(e) => setBuyForm({ ...buyForm, price: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <input type="number" placeholder="수량" value={buyForm.quantity} onChange={(e) => setBuyForm({ ...buyForm, quantity: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <input type="number" placeholder="손절가" value={buyForm.stop_loss} onChange={(e) => setBuyForm({ ...buyForm, stop_loss: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <input type="number" placeholder="1차익절가 (선택)" value={buyForm.take_profit} onChange={(e) => setBuyForm({ ...buyForm, take_profit: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
              </div>
              <input placeholder="메모 (선택)" value={buyForm.memo} onChange={(e) => setBuyForm({ ...buyForm, memo: e.target.value })}
                className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white w-full mt-2 text-sm" />
              <button onClick={async () => {
                try {
                  const body = {
                    ticker: buyForm.ticker, name: buyForm.name, date: buyForm.date,
                    price: Number(buyForm.price), quantity: Number(buyForm.quantity),
                    stop_loss: Number(buyForm.stop_loss), entry_reason: buyForm.entry_reason,
                    memo: buyForm.memo, take_profit: Number(buyForm.take_profit) || 0,
                  };
                  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"}/portfolio/buy?market=${market}`, {
                    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
                  });
                  if (res.ok) { setFormMsg("매수 등록 완료"); setShowBuyForm(false); setBuyForm({ ticker: "", name: "", date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), price: "", quantity: "", stop_loss: "", entry_reason: "PB20", memo: "", take_profit: "" }); setReentryWarning(null); setBuySuggestions([]); loadAll(); }
                  else setFormMsg("오류: " + await res.text());
                } catch (e: any) { setFormMsg("오류: " + e.message); }
              }} className="mt-3 px-4 py-1.5 bg-red-600 hover:bg-red-700 rounded text-sm text-white">매수 등록</button>
              {reentryWarning?.warning && (
                <div className="mt-2 p-2 bg-yellow-900/30 border border-yellow-700/50 rounded text-xs text-yellow-400">
                  ⚠️ {reentryWarning.message}
                </div>
              )}
            </div>
          )}

          {/* 매도 폼 */}
          {showSellForm && (
            <div className="bg-[#161b22] rounded-lg p-4 border border-gray-800 mt-3">
              <h3 className="text-sm font-bold text-white mb-3">매도 입력</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <select value={sellForm.position_id} onChange={(e) => setSellForm({ ...sellForm, position_id: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white col-span-2">
                  <option value="">종목 선택</option>
                  {positions.map((p) => (
                    <option key={p["position_id"]} value={p["position_id"]}>
                      {p["종목명"]} ({p["수량"]}주)
                    </option>
                  ))}
                </select>
                <input type="date" value={sellForm.date} onChange={(e) => setSellForm({ ...sellForm, date: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <input type="number" placeholder="매도가" value={sellForm.price} onChange={(e) => setSellForm({ ...sellForm, price: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <input type="number" placeholder="수량" value={sellForm.quantity} onChange={(e) => setSellForm({ ...sellForm, quantity: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <input placeholder="매도 사유" value={sellForm.reason} onChange={(e) => setSellForm({ ...sellForm, reason: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white col-span-2" />
              </div>
              <button onClick={async () => {
                try {
                  const body = {
                    position_id: sellForm.position_id, date: sellForm.date,
                    price: Number(sellForm.price), quantity: Number(sellForm.quantity), reason: sellForm.reason,
                  };
                  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api"}/portfolio/sell?market=${market}`, {
                    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
                  });
                  if (res.ok) { setFormMsg("매도 등록 완료"); setShowSellForm(false); setSellForm({ position_id: "", date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), price: "", quantity: "", reason: "" }); loadAll(); }
                  else setFormMsg("오류: " + await res.text());
                } catch (e: any) { setFormMsg("오류: " + e.message); }
              }} className="mt-3 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white">매도 등록</button>
            </div>
          )}

          {/* 손절가 수정 폼 */}
          {showStopForm && (
            <div className="bg-[#161b22] rounded-lg p-4 border border-gray-800 mt-3">
              <h3 className="text-sm font-bold text-white mb-3">손절가 수정</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <select value={stopForm.position_id} onChange={(e) => setStopForm({ ...stopForm, position_id: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white col-span-2">
                  <option value="">종목 선택</option>
                  {positions.map((p) => (
                    <option key={p["position_id"]} value={p["position_id"]}>
                      {p["종목명"]} (현재 손절: {market === "KR" ? fmt(p["손절가"]) : "$" + (p["손절가"]?.toFixed(2) || 0)})
                    </option>
                  ))}
                </select>
                <input type="number" placeholder="새 손절가" value={stopForm.price}
                  onChange={(e) => setStopForm({ ...stopForm, price: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
                <input type="date" value={stopForm.date} onChange={(e) => setStopForm({ ...stopForm, date: e.target.value })}
                  className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white" />
              </div>
              <input placeholder="변경 사유 (선택)" value={stopForm.note} onChange={(e) => setStopForm({ ...stopForm, note: e.target.value })}
                className="bg-[#0d1117] border border-gray-700 rounded px-2 py-1.5 text-white w-full mt-2 text-sm" />
              <button onClick={async () => {
                try {
                  const body = { position_id: stopForm.position_id, date: stopForm.date, price: Number(stopForm.price), note: stopForm.note };
                  const res = await fetch(`http://${typeof window !== "undefined" ? window.location.hostname : "localhost"}:8000/api/portfolio/stop-loss/update?market=${market}`, {
                    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
                  });
                  if (res.ok) { setFormMsg("손절가 수정 완료"); setShowStopForm(false); setStopForm({ position_id: "", date: new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10), price: "", note: "" }); loadAll(); }
                  else setFormMsg("오류: " + await res.text());
                } catch (e: any) { setFormMsg("오류: " + e.message); }
              }} className="mt-3 px-4 py-1.5 bg-yellow-600 hover:bg-yellow-700 rounded text-sm text-white">손절가 수정</button>
            </div>
          )}
        </div>
      )}

      {/* ═══ 위험관리 ═══ */}
      {!loading && tab === 1 && (
        <div className="space-y-6">
          {/* OTI 현황 */}
          {oti && (
            <div className="bg-[#161b22] rounded-lg p-4 border border-gray-800 max-w-md">
              <p className="text-xs text-gray-500">OTI (과매매지수)</p>
              <p className="text-3xl font-bold text-white">
                {oti.oti} <span className="text-lg">{oti.level}</span>
              </p>
              <p className="text-sm text-gray-500 mt-1">3일내 {oti.count}종목 청산</p>
              {oti.details?.map((d: any, i: number) => (
                <p key={i} className="text-xs text-gray-600 mt-1">
                  · {d["종목명"]} ({d["보유일"]}일, {d["수익률"] >= 0 ? "+" : ""}{d["수익률"].toFixed(2)}%)
                </p>
              ))}
              <div className="mt-3 pt-2 border-t border-gray-800">
                <p className="text-[10px] text-gray-600 leading-relaxed">
                  산출: 3일 내 청산 종목 수 × (100 + 손실률 가중치)<br/>
                  🟢 0~99 정상 · 🟡 100~199 주의 · 🟠 200~499 과매매 · 🔴 500+ WALK AWAY
                </p>
              </div>
            </div>
          )}

          {/* OTI 추이 차트 */}
          {otiChartOption && (
            <div>
              <h2 className="text-sm text-gray-500 mb-2">OTI 추이 (60일)</h2>
              <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl overflow-hidden">
                <ReactECharts option={otiChartOption} style={{ height: 260 }} />
              </div>
            </div>
          )}

          {/* 시장점수 vs 익스포져 */}
          <div>
            <h2 className="text-sm text-gray-500 mb-2">시장 추세 vs 익스포져</h2>

            {/* 현재 지표 카드 */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
              <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                <p className="text-xs text-gray-500">시장점수</p>
                <p className="text-xl font-bold text-white">{curScore}</p>
                <p className="text-xs text-gray-600">{scoreLevelLabel} · 기울기 {marketScore?.current?.slope >= 0 ? "+" : ""}{marketScore?.current?.slope || 0}%</p>
              </div>
              <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                <p className="text-xs text-gray-500">익스포져</p>
                <p className="text-xl font-bold text-white">{curExposure.toFixed(0)}%</p>
              </div>
              <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                <p className="text-xs text-gray-500">추세 정합</p>
                <p className="text-lg font-bold text-white">{alignLabel}</p>
              </div>
            </div>

            {/* 합산 차트 */}
            {trendChartOption && (
              <div className="bg-[#0f1318] border border-gray-800/60 rounded-xl overflow-hidden">
                <ReactECharts option={trendChartOption} style={{ height: 260 }} />
              </div>
            )}

            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                <p className="text-[10px] text-gray-500 font-medium mb-1">시장점수 산출</p>
                <p className="text-[10px] text-gray-600 leading-relaxed">
                  MA20 기울기(50%) + 가격위치(30%) + 저점상승(20%)<br/>
                  기울기: 10일 전 MA20 대비 변화율 → 0~100점<br/>
                  위치: 종가가 MA20 위면 100, 아래+거래량↓ 50, 아래+거래량↑ 20<br/>
                  저점: 20일 최저가가 상승 중이면 100, 아니면 30<br/>
                  🟢 85+ 최적 · 🟢 70+ 양호 · 🟡 50+ 보통 · 🟠 30+ 주의 · 🔴 30미만 위험
                </p>
              </div>
              <div className="bg-[#161b22] rounded-lg p-3 border border-gray-800">
                <p className="text-[10px] text-gray-500 font-medium mb-1">추세 정합 판정</p>
                <p className="text-[10px] text-gray-600 leading-relaxed">
                  시장점수(강/중/약) × 익스포져(고/중/저) → 9칸 매트릭스<br/>
                  강세+고노출 = 추세 순응 ✅<br/>
                  약세+고노출 = 추세 역행 🔴<br/>
                  약세+저노출 = 관망 적정 ✅<br/>
                  강세+저노출 = 기회 미활용 ⚠️<br/>
                  익스포져 = 평가액 / (현금+평가액) × 100
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ═══ 기간 필터 (거래별/종목별 공통) ═══ */}
      {!loading && (tab === 2 || tab === 3) && (
        <div className="mb-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex gap-1">
              {([
                { value: "all", label: "전체" },
                { value: "year", label: "연도" },
                { value: "quarter", label: "분기" },
                { value: "month", label: "월" },
                { value: "week", label: "주" },
              ] as const).map((u) => (
                <button key={u.value} onClick={() => setPerfUnit(u.value)}
                  className={`px-3 py-1 rounded text-sm ${perfUnit === u.value ? "bg-blue-600 text-white" : "bg-[#1f2937] text-gray-400 hover:text-white"}`}>
                  {u.label}
                </button>
              ))}
            </div>

            {perfUnit !== "all" && perfPeriods.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {perfPeriods.map((p) => (
                  <button key={p} onClick={() => setPerfPeriod(p)}
                    className={`px-2.5 py-1 rounded text-xs ${perfPeriod === p ? "bg-gray-600 text-white" : "bg-[#1f2937] text-gray-500 hover:text-white"}`}>
                    {p}
                  </button>
                ))}
              </div>
            )}

            {perfUnit !== "all" && (
              <span className="text-xs text-gray-600">{filteredPnl.length}건</span>
            )}
          </div>
        </div>
      )}

      {/* ═══ 거래별 성과분석 ═══ */}
      {!loading && tab === 2 && (
        <div>
          {(() => {
            const kpi = calcKpi(filteredPnl);
            if (!kpi) return <p className="text-gray-600 py-4">해당 기간에 실현된 거래가 없습니다.</p>;
            const lossVsPlan = kpi.avgPlannedLoss != null ? (kpi.wAvgLoss - kpi.avgPlannedLoss) : null;
            return (
              <>
                {/* KPI 4행 × 3열 = 12개 */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-2">
                  <KpiCard label="총 실현손익 (비용차감)" value={`${fmt(kpi.totalNet)}${currency}`}
                    sub={`거래비용 ${fmt(kpi.totalFees)}${currency}`}
                    color={kpi.totalNet >= 0 ? "text-red-400" : "text-teal-400"} />
                  <KpiCard label="거래 건수" value={`${kpi.count}건`} />
                  <KpiCard label="승 / 패" value={`${kpi.wins}승 ${kpi.losses}패`} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-2">
                  <KpiCard label="승률" value={`${kpi.winRate.toFixed(1)}%`} />
                  <KpiCard label="승리 시 평균수익률" value={`${kpi.wAvgWin >= 0 ? "+" : ""}${kpi.wAvgWin.toFixed(2)}%`} />
                  <KpiCard label="패배 시 평균손실률" value={`${kpi.wAvgLoss.toFixed(2)}%`}
                    sub={lossVsPlan != null ? (lossVsPlan > 0 ? `목표보다 ${Math.abs(lossVsPlan).toFixed(2)}%p 절약` : `목표보다 ${Math.abs(lossVsPlan).toFixed(2)}%p 초과`) : undefined} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-2">
                  <KpiCard label="목표손절 위반" value={`${kpi.violations}회`}
                    sub={`위반율 ${kpi.violationRate.toFixed(1)}%`} />
                  <KpiCard label="전체 평균수익률 (가중)" value={`${kpi.wAvgRet >= 0 ? "+" : ""}${kpi.wAvgRet.toFixed(2)}%`} />
                  <KpiCard label="자산회전율" value={kpi.turnover != null ? `${kpi.turnover.toFixed(2)}배` : "-"}
                    sub={kpi.capitalRet != null ? `원금대비 ${kpi.capitalRet >= 0 ? "+" : ""}${kpi.capitalRet.toFixed(2)}%` : undefined} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                  <KpiCard label="평균 R/R" value={kpi.avgRR != null ? kpi.avgRR.toFixed(2) : "-"} />
                  <KpiCard label="수익 시 평균보유기간" value={kpi.avgHoldWin != null ? `${kpi.avgHoldWin.toFixed(0)}일` : "-"} />
                  <KpiCard label="손실 시 평균보유기간" value={kpi.avgHoldLoss != null ? `${kpi.avgHoldLoss.toFixed(0)}일` : "-"} />
                </div>

                <h3 className="text-sm text-gray-500 mb-2">진입근거별 성과</h3>
                <div className="overflow-x-auto border border-gray-800 rounded-lg mb-4">
                  <table className="w-full text-sm">
                    <thead><tr className="bg-[#161b22] border-b border-gray-800 text-gray-500 text-xs">
                      <th className="px-3 py-2 text-left">근거</th><th className="px-3 py-2 text-center">건수</th>
                      <th className="px-3 py-2 text-center">승/패</th><th className="px-3 py-2 text-right">승률</th>
                      <th className="px-3 py-2 text-right">승리평균</th><th className="px-3 py-2 text-right">패배평균</th>
                      <th className="px-3 py-2 text-right">가중평균</th><th className="px-3 py-2 text-right">R/R</th>
                      <th className="px-3 py-2 text-right">총손익</th>
                    </tr></thead>
                    <tbody>
                      {calcByEntry(filteredPnl).map((r) => (
                        <tr key={r.entry} className="border-b border-gray-800/50">
                          <td className="px-3 py-1.5 text-gray-300">{r.entry}</td>
                          <td className="px-3 py-1.5 text-center text-gray-400">{r.count}</td>
                          <td className="px-3 py-1.5 text-center text-gray-400">{r.wins}/{r.losses}</td>
                          <td className="px-3 py-1.5 text-right text-gray-300">{r.winRate?.toFixed(1)}%</td>
                          <td className="px-3 py-1.5 text-right text-red-400">{r.wAvgWin?.toFixed(2)}%</td>
                          <td className="px-3 py-1.5 text-right text-teal-400">{r.wAvgLoss?.toFixed(2)}%</td>
                          <td className={`px-3 py-1.5 text-right ${(r.wAvgRet || 0) >= 0 ? "text-red-400" : "text-teal-400"}`}>{r.wAvgRet?.toFixed(2)}%</td>
                          <td className="px-3 py-1.5 text-right text-gray-300">{r.avgRR != null ? r.avgRR.toFixed(2) : "-"}</td>
                          <td className={`px-3 py-1.5 text-right ${(r.totalNet || 0) >= 0 ? "text-red-400" : "text-teal-400"}`}>{fmt(r.totalNet || 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <h3 className="text-sm text-gray-500 mb-2">거래 내역</h3>
                <DataTable columns={PNL_COLUMNS} data={filteredPnl} tickerKey="종목코드" showRowNumber />

                {renderEquityCurve(filteredPnl, "날짜")}
                {renderReturnDist(filteredPnl)}
              </>
            );
          })()}
        </div>
      )}

      {/* ═══ 종목별 성과분석 ═══ */}
      {!loading && tab === 3 && (
        <div>
          {(() => {
            const kpi = calcKpi(filteredTickerPnl);
            if (!kpi) return <p className="text-gray-600 py-4">실현된 종목이 없습니다.</p>;
            return (
              <>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-2">
                  <KpiCard label="총 실현손익 (비용차감)" value={`${fmt(kpi.totalNet)}${currency}`}
                    sub={`거래비용 ${fmt(kpi.totalFees)}${currency}`}
                    color={kpi.totalNet >= 0 ? "text-red-400" : "text-teal-400"} />
                  <KpiCard label="종목 수" value={`${kpi.count}종목`} sub={`${kpi.wins}승 ${kpi.losses}패`} />
                  <KpiCard label="승률" value={`${kpi.winRate.toFixed(1)}%`} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-2">
                  <KpiCard label="승리 시 평균수익률" value={`${kpi.wAvgWin >= 0 ? "+" : ""}${kpi.wAvgWin.toFixed(2)}%`} />
                  <KpiCard label="패배 시 평균손실률" value={`${kpi.wAvgLoss.toFixed(2)}%`} />
                  <KpiCard label="전체 평균수익률 (가중)" value={`${kpi.wAvgRet >= 0 ? "+" : ""}${kpi.wAvgRet.toFixed(2)}%`} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                  <KpiCard label="평균 R/R" value={kpi.avgRR != null ? kpi.avgRR.toFixed(2) : "-"} />
                  <KpiCard label="자산회전율" value={kpi.turnover != null ? `${kpi.turnover.toFixed(2)}배` : "-"} />
                  <KpiCard label="원금대비 실현수익률" value={kpi.capitalRet != null ? `${kpi.capitalRet >= 0 ? "+" : ""}${kpi.capitalRet.toFixed(2)}%` : "-"} />
                </div>

                <h3 className="text-sm text-gray-500 mb-2">진입근거별 성과</h3>
                <div className="overflow-x-auto border border-gray-800 rounded-lg mb-4">
                  <table className="w-full text-sm">
                    <thead><tr className="bg-[#161b22] border-b border-gray-800 text-gray-500 text-xs">
                      <th className="px-3 py-2 text-left">근거</th><th className="px-3 py-2 text-center">건수</th>
                      <th className="px-3 py-2 text-center">승/패</th><th className="px-3 py-2 text-right">승률</th>
                      <th className="px-3 py-2 text-right">승리평균</th><th className="px-3 py-2 text-right">패배평균</th>
                      <th className="px-3 py-2 text-right">가중평균</th><th className="px-3 py-2 text-right">R/R</th>
                      <th className="px-3 py-2 text-right">총손익</th>
                    </tr></thead>
                    <tbody>
                      {calcByEntry(filteredTickerPnl).map((r) => (
                        <tr key={r.entry} className="border-b border-gray-800/50">
                          <td className="px-3 py-1.5 text-gray-300">{r.entry}</td>
                          <td className="px-3 py-1.5 text-center text-gray-400">{r.count}</td>
                          <td className="px-3 py-1.5 text-center text-gray-400">{r.wins}/{r.losses}</td>
                          <td className="px-3 py-1.5 text-right text-gray-300">{r.winRate?.toFixed(1)}%</td>
                          <td className="px-3 py-1.5 text-right text-red-400">{r.wAvgWin?.toFixed(2)}%</td>
                          <td className="px-3 py-1.5 text-right text-teal-400">{r.wAvgLoss?.toFixed(2)}%</td>
                          <td className={`px-3 py-1.5 text-right ${(r.wAvgRet || 0) >= 0 ? "text-red-400" : "text-teal-400"}`}>{r.wAvgRet?.toFixed(2)}%</td>
                          <td className="px-3 py-1.5 text-right text-gray-300">{r.avgRR != null ? r.avgRR.toFixed(2) : "-"}</td>
                          <td className={`px-3 py-1.5 text-right ${(r.totalNet || 0) >= 0 ? "text-red-400" : "text-teal-400"}`}>{fmt(r.totalNet || 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <h3 className="text-sm text-gray-500 mb-2">종목별 내역</h3>
                <DataTable columns={PNL_COLUMNS} data={filteredTickerPnl} tickerKey="종목코드" showRowNumber />

                {renderEquityCurve(filteredTickerPnl, "청산일")}
                {renderReturnDist(filteredTickerPnl)}
              </>
            );
          })()}
        </div>
      )}

      {/* ═══ 월별 분석 ═══ */}
      {!loading && tab === 4 && (
        monthlyPerf.length > 0
          ? <DataTable columns={MONTHLY_COLUMNS} data={monthlyPerf} />
          : <p className="text-gray-600 py-4">월별 데이터가 없습니다.</p>
      )}

      {/* ═══ 매매일지 (한국+미국 동시) ═══ */}
      {/* ═══ 주간 리뷰 ═══ */}
      {!loading && tab === 5 && <WeeklyReviewTab market={market} currency={currency} />}

      {/* ═══ 매매일지 ═══ */}
      {tab === 6 && <JournalTab />}

      {/* ═══ 잔액관리 ═══ */}
      {!loading && tab === 7 && <BalanceTab market={market} currency={currency} onReload={loadAll} />}

      {/* ═══ 거래이력 ═══ */}
      {!loading && tab === 8 && (
        <>
          <p className="text-xs text-gray-500 mb-2">{tradeLog.length}건</p>
          <DataTable columns={LOG_COLUMNS} data={tradeLog} tickerKey="ticker" />
        </>
      )}
    </div>
  );
}
