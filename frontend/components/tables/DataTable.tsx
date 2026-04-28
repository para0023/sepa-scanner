"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";

interface Column {
  key: string;
  label: string;
  align?: "left" | "right" | "center";
  format?: "number" | "percent" | "price";
}

interface DataTableProps {
  columns: Column[];
  data: Record<string, any>[];
  tickerKey?: string;
  onRowClick?: (row: Record<string, any>) => void;
  showRowNumber?: boolean;
  defaultSortKey?: string;       // 기본 정렬 컬럼
  defaultSortDir?: "asc" | "desc";  // 기본 정렬 방향
}

function formatCell(value: any, format?: string): string {
  if (value === null || value === undefined) return "—";
  if (format === "number") return Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  if (format === "percent") return (Number(value) >= 0 ? "+" : "") + Number(value).toFixed(2) + "%";
  if (format === "price") {
    const n = Number(value);
    // 소수점이 있으면 달러(미국주식) → 소수점 2자리
    if (n % 1 !== 0) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
  }
  return String(value);
}

export default function DataTable({ columns, data, tickerKey, onRowClick, showRowNumber, defaultSortKey, defaultSortDir }: DataTableProps) {
  const router = useRouter();
  const [sortKey, setSortKey] = useState<string | null>(defaultSortKey || null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultSortDir || "desc");

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortedData = useMemo(() => {
    if (!sortKey) return data;
    return [...data].sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      // null/undefined를 맨 뒤로
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      // 숫자 비교
      const na = Number(va), nb = Number(vb);
      if (!isNaN(na) && !isNaN(nb)) {
        return sortDir === "asc" ? na - nb : nb - na;
      }
      // 문자열 비교
      const sa = String(va), sb = String(vb);
      return sortDir === "asc" ? sa.localeCompare(sb) : sb.localeCompare(sa);
    });
  }, [data, sortKey, sortDir]);

  const handleClick = (row: Record<string, any>) => {
    if (onRowClick) {
      onRowClick(row);
    } else if (tickerKey && row[tickerKey]) {
      router.push(`/chart/${row[tickerKey]}`);
    }
  };

  return (
    <div className="overflow-x-auto border border-gray-800 rounded-lg">
      <table className="w-full text-sm md:text-sm text-xs">
        <thead>
          <tr className="bg-[#161b22] border-b border-gray-800">
            {showRowNumber && (
              <th className="px-2 py-2 text-xs text-gray-500 font-medium text-center w-10">#</th>
            )}
            {columns.map((col) => (
              <th
                key={col.key}
                onClick={() => handleSort(col.key)}
                className={`px-2 md:px-3 py-2 text-xs text-gray-500 font-medium cursor-pointer hover:text-gray-300 select-none whitespace-nowrap ${
                  col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"
                }`}
              >
                {col.label}
                {sortKey === col.key && (
                  <span className="ml-1 text-blue-400">{sortDir === "asc" ? "▲" : "▼"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedData.map((row, i) => (
            <tr
              key={i}
              onClick={() => handleClick(row)}
              className="border-b border-gray-800/50 hover:bg-[#1f2937] cursor-pointer transition"
            >
              {showRowNumber && (
                <td className="px-2 py-1.5 text-center text-gray-500 text-xs">{i + 1}</td>
              )}
              {columns.map((col) => {
                const val = row[col.key];
                const formatted = formatCell(val, col.format);
                const isNeg = col.format === "percent" && Number(val) < 0;
                const isPos = col.format === "percent" && Number(val) > 0;

                return (
                  <td
                    key={col.key}
                    className={`px-2 md:px-3 py-1.5 whitespace-nowrap ${
                      col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left"
                    } ${isPos ? "text-red-400" : isNeg ? "text-teal-400" : "text-gray-300"}`}
                  >
                    {formatted}
                  </td>
                );
              })}
            </tr>
          ))}
          {data.length === 0 && (
            <tr>
              <td colSpan={columns.length + (showRowNumber ? 1 : 0)} className="px-3 py-8 text-center text-gray-600">
                데이터 없음
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
