"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";

function getApiBase() {
  if (typeof window === "undefined") return "http://localhost:8000/api";
  return `http://${window.location.hostname}:8000/api`;
}

function fmtKR(n: number) { return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 }); }

export default function JournalPage() {
  const [mode, setMode] = useState<"write" | "view">("write");
  const [date, setDate] = useState(() => new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10));
  const [krPositions, setKrPositions] = useState<any[]>([]);
  const [usPositions, setUsPositions] = useState<any[]>([]);
  const [memos, setMemos] = useState<Record<string, string>>({});
  const [extraNotes, setExtraNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const [dates, setDates] = useState<string[]>([]);
  const [viewDate, setViewDate] = useState("");
  const [viewData, setViewData] = useState<any>(null);
  const [jLoading, setJLoading] = useState(false);

  const API = getApiBase();

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

  useEffect(() => {
    if (mode !== "view") return;
    fetch(`${API}/journal/dates`).then((r) => r.json()).then((d) => {
      const list = Array.isArray(d) ? d : (d?.dates || []);
      setDates(list);
      list.sort().reverse();
      if (list.length > 0) setViewDate((prev) => prev || list[0]);
    }).catch(() => setDates([]));
  }, [mode]);

  useEffect(() => {
    if (mode !== "view" || !viewDate) return;
    fetch(`${API}/journal/${viewDate}`).then((r) => r.json()).then(setViewData).catch(() => setViewData(null));
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
        method: "POST", headers: { "Content-Type": "application/json" },
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
    <div className="max-w-3xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-4">매매계획</h1>

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

          {krPositions.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-bold text-white mb-2">한국 보유종목</h3>
              {krPositions.map((p: any) => (
                <div key={p["종목코드"]} className="mb-3">
                  <p className="text-sm text-gray-300">
                    <span className="font-medium text-white">{p["종목명"]}</span>
                    <span className="text-gray-500 ml-1">({p["종목코드"]})</span>
                    <span className="text-gray-600 ml-2">매수가: {fmtKR(p["평균매수가"])}원</span>
                    <span className="text-gray-600 ml-2">손절가: {fmtKR(p["손절가"])}원</span>
                    {p["1차익절가"] > 0 && <span className="text-gray-600 ml-2">익절: {fmtKR(p["1차익절가"])}원</span>}
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

          <div className="mb-4">
            <h3 className="text-sm font-bold text-white mb-2">추가 메모</h3>
            <textarea value={extraNotes} onChange={(e) => setExtraNotes(e.target.value)}
              placeholder="신규 관심종목, 시장 동향, 기타 메모"
              className="w-full bg-[#0d1117] border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600 resize-y"
              rows={4} />
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
                {(Array.isArray(dates) ? dates : []).map((d) => (
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
