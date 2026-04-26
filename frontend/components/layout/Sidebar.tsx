"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { fetchApi } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/", label: "Main", icon: "🏠" },
  { href: "/scanner/sepa", label: "SEPA Scanner", icon: "🔍" },
  { href: "/scanner/rs", label: "RS Scanner", icon: "📊" },
  { href: "/scanner/short", label: "Short Scanner", icon: "🔻" },
  { href: "/scanner/universe", label: "기타순위", icon: "📋" },
  { href: "/portfolio", label: "포트폴리오", icon: "💼" },
  { href: "/market", label: "시장 지표", icon: "🌍" },
  { href: "/watchlist/groups", label: "그룹 분석", icon: "📂" },
];

interface StockItem {
  code: string;
  name: string;
  market: string;
}

export default function Sidebar() {
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<StockItem[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // 페이지 이동 시 모바일 메뉴 닫기
  useEffect(() => { setMobileOpen(false); }, [pathname]);

  // 검색어 변경 시 자동완성
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!query.trim() || query.trim().length < 1) {
      setSuggestions([]); setShowDropdown(false); return;
    }
    debounceRef.current = setTimeout(() => {
      fetchApi<StockItem[]>(`/stocks/search?q=${encodeURIComponent(query.trim())}&limit=15`)
        .then((items) => { setSuggestions(items); setShowDropdown(items.length > 0); })
        .catch(() => { setSuggestions([]); setShowDropdown(false); });
    }, 200);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  // 바깥 클릭 시 드롭다운 닫기
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setShowDropdown(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const goToChart = (code: string) => {
    setShowDropdown(false); setQuery(""); setSuggestions([]); setMobileOpen(false);
    window.location.href = `/chart/${code}`;
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      const q = query.trim();
      if (!q) return;
      if (suggestions.length === 1) goToChart(suggestions[0].code);
      else if (q.length <= 6 && /^[A-Za-z0-9]+$/.test(q)) goToChart(q.toUpperCase());
      else if (suggestions.length > 0) goToChart(suggestions[0].code);
    }
  };

  const sidebarContent = (
    <>
      {/* 로고 */}
      <div className="p-4 border-b border-gray-800 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-white">SEPA Scanner</h1>
          <p className="text-xs text-gray-500 mt-0.5">v2.0 — React</p>
        </div>
        {/* 모바일 닫기 버튼 */}
        <button onClick={() => setMobileOpen(false)} className="md:hidden text-gray-400 hover:text-white text-xl">
          ✕
        </button>
      </div>

      {/* 종목 검색 */}
      <div className="p-3 border-b border-gray-800" ref={wrapperRef}>
        <div className="relative">
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowDropdown(true)}
            onKeyDown={handleKeyDown} placeholder="종목명 또는 코드"
            className="w-full px-3 py-1.5 bg-[#0d1117] border border-gray-700 rounded text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none" />
          {showDropdown && (
            <div className="absolute left-0 right-0 top-full mt-1 bg-[#1c2128] border border-gray-700 rounded shadow-lg max-h-64 overflow-y-auto z-50">
              {suggestions.map((item) => (
                <button key={`${item.code}-${item.market}`} onClick={() => goToChart(item.code)}
                  className="w-full text-left px-3 py-1.5 hover:bg-[#2d333b] text-sm flex justify-between items-center">
                  <span>
                    <span className="text-white">{item.name}</span>
                    <span className="text-gray-500 ml-1.5 text-xs">{item.code}</span>
                  </span>
                  <span className="text-gray-600 text-[10px]">{item.market}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 네비게이션 */}
      <nav className="flex-1 overflow-y-auto py-2">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link key={item.href} href={item.href}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm transition ${
                active ? "bg-[#1f2937] text-white border-l-2 border-blue-500" : "text-gray-400 hover:text-white hover:bg-[#1f2937]"
              }`}>
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );

  return (
    <>
      {/* 모바일 햄버거 버튼 */}
      <button onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-3 left-3 z-50 bg-[#161b22] border border-gray-700 rounded-lg px-2.5 py-1.5 text-white text-lg">
        ☰
      </button>

      {/* 모바일 오버레이 */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 bg-black/60 z-40" onClick={() => setMobileOpen(false)} />
      )}

      {/* 사이드바 — 데스크톱: 항상 표시, 모바일: 슬라이드 */}
      <aside className={`
        fixed left-0 top-0 h-full bg-[#161b22] border-r border-gray-800 flex flex-col z-50
        w-56 transition-transform duration-200
        md:translate-x-0
        ${mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}
      `}>
        {sidebarContent}
      </aside>
    </>
  );
}
