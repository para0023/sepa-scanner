"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  type IChartApi,
  type LogicalRange,
} from "lightweight-charts";

interface ChartData {
  ohlcv: {
    dates: string[];
    open: number[];
    high: number[];
    low: number[];
    close: number[];
    volume: number[];
  };
  ma: Record<string, (number | null)[]>;
  rs: { line: (number | null)[]; score: number };
  benchmark_line: (number | null)[];
  signals: { entry: number[]; sell: number[] };
  atr: (number | null)[];
  vol_ma5?: (number | null)[];
  vol_ma60?: (number | null)[];
  trades: { date: string; type: string; price: number; quantity: number }[];
}

const MA_COLORS: Record<string, string> = {
  ma5: "#FFEB3B", ma20: "#FF9800", ma60: "#4CAF50",
  wma100: "#2196F3", ma120: "#9C27B0", ma200: "#F44336",
};
const MA_LABELS: Record<string, string> = {
  ma5: "MA5", ma20: "MA20", ma60: "MA60",
  wma100: "WMA100", ma120: "MA120", ma200: "MA200",
};

function barColor(val: number): string {
  // 0(녹색) → 0.5(황색) → 1(적색) 그라데이션
  const v = Math.max(0, Math.min(1, val));
  if (v <= 0.5) {
    // 녹색(39,174,96) → 황색(243,156,18)
    const t = v / 0.5;
    const r = Math.round(39 + (243 - 39) * t);
    const g = Math.round(174 + (156 - 174) * t);
    const b = Math.round(96 + (18 - 96) * t);
    return `rgba(${r},${g},${b},0.85)`;
  } else {
    // 황색(243,156,18) → 적색(192,57,43)
    const t = (v - 0.5) / 0.5;
    const r = Math.round(243 + (192 - 243) * t);
    const g = Math.round(156 + (57 - 156) * t);
    const b = Math.round(18 + (43 - 18) * t);
    return `rgba(${r},${g},${b},0.85)`;
  }
}
function fmtNum(n: number) {
  // 소수점이 있으면 달러(미국), 없으면 원(한국)
  if (n % 1 !== 0) return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}
function fmtVol(n: number) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "K";
  return String(n);
}

export default function CandlestickChart({ data }: { data: ChartData }) {
  const visibleDays = 60;
  // 가격이 소수점이면 달러(미국주식)
  const isUSD = data.ohlcv.close.some((v) => v % 1 !== 0);
  const minMove = isUSD ? 0.01 : 1;
  const refs = {
    entry: useRef<HTMLDivElement>(null),
    sell: useRef<HTMLDivElement>(null),
    main: useRef<HTMLDivElement>(null),
    vol: useRef<HTMLDivElement>(null),
    rs: useRef<HTMLDivElement>(null),
    atr: useRef<HTMLDivElement>(null),
  };
  const chartsRef = useRef<IChartApi[]>([]);
  const isSyncing = useRef(false);
  const [hIdx, setHIdx] = useState(-1);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const idx = hIdx >= 0 ? hIdx : data.ohlcv.dates.length - 1;
  const prev = idx > 0 ? idx - 1 : 0;
  const pc = data.ohlcv.close[prev];
  const o = data.ohlcv.open[idx], h = data.ohlcv.high[idx], l = data.ohlcv.low[idx], c = data.ohlcv.close[idx];
  const up = c >= o;
  function pctVsPrev(price: number) {
    if (!pc || pc === 0) return "";
    const p = ((price / pc) - 1) * 100;
    return `(${p >= 0 ? "+" : ""}${p.toFixed(2)}%)`;
  }

  useEffect(() => {
    const containers = Object.values(refs);
    if (containers.some((r) => !r.current) || !data) return;

    chartsRef.current.forEach((ch) => ch.remove());
    chartsRef.current = [];

    const w = refs.main.current!.clientWidth;
    const dates = data.ohlcv.dates;

    const BG = { type: ColorType.Solid as const, color: "#0d1117" };
    const GRID = {
      vertLines: { color: "rgba(255,255,255,0.04)" },
      horzLines: { color: "rgba(255,255,255,0.04)" },
    };

    const PRICE_SCALE_WIDTH = 85; // 모든 차트 우측 축 너비 고정

    function mk(el: HTMLDivElement, h: number, showTime = false) {
      return createChart(el, {
        width: w, height: h,
        layout: { background: BG, textColor: "#AAA", attributionLogo: false as any },
        grid: GRID,
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: "#333", visible: true, minimumWidth: PRICE_SCALE_WIDTH },
        leftPriceScale: { visible: false },
        timeScale: { borderColor: "#333", visible: showTime, timeVisible: false },
      });
    }

    // 1) 진입신호 — 높이 균일, 색상으로만 표현
    const cEntry = mk(refs.entry.current!, 25);
    const sEntry = cEntry.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false });
    sEntry.setData(dates.map((d, i) => ({ time: d, value: 1, color: barColor(data.signals.entry[i]) })) as any);

    // 2) 분배신호 — 높이 균일, 색상으로만 표현
    const cSell = mk(refs.sell.current!, 25);
    const sSell = cSell.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false });
    sSell.setData(dates.map((d, i) => ({ time: d, value: 1, color: barColor(data.signals.sell[i]) })) as any);

    // 3) 캔들 + MA
    const cMain = mk(refs.main.current!, 350);
    const sCandle = cMain.addSeries(CandlestickSeries, {
      upColor: "#EF5350", downColor: "#26A69A",
      borderUpColor: "#EF5350", borderDownColor: "#26A69A",
      wickUpColor: "#EF5350", wickDownColor: "#26A69A",
      priceFormat: { type: "custom", formatter: (p: any) => fmtNum(Number(p)), minMove },
    });
    sCandle.setData(dates.map((d, i) => ({
      time: d, open: data.ohlcv.open[i], high: data.ohlcv.high[i],
      low: data.ohlcv.low[i], close: data.ohlcv.close[i],
    })) as any);

    // 벤치마크 라인 (별도 축, 점선)
    if (data.benchmark_line) {
      const sBench = cMain.addSeries(LineSeries, {
        color: "#5C6BC0", lineWidth: 1, lineStyle: 2,
        priceScaleId: "benchmark",
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "custom", formatter: (p: any) => fmtNum(Number(p)), minMove },
      });
      cMain.priceScale("benchmark").applyOptions({
        scaleMargins: { top: 0.02, bottom: 0.15 },
        visible: false,
      });
      sBench.setData(dates.map((d, i) => ({ time: d, value: data.benchmark_line[i] }))
        .filter((p) => p.value != null) as any[]);
    }

    // 매매 마커 — DOM 오버레이로 직접 표시
    if (data.trades && data.trades.length > 0) {
      const mainEl = refs.main.current!;

      // 날짜별 캔들 high/low 맵 (마커가 캔들에 겹치지 않도록)
      const dateHighLow: Record<string, { high: number; low: number }> = {};
      dates.forEach((d, i) => {
        dateHighLow[d] = { high: data.ohlcv.high[i], low: data.ohlcv.low[i] };
      });

      const updateMarkers = () => {
        // 기존 마커 제거
        mainEl.querySelectorAll(".trade-marker").forEach((el) => el.remove());

        data.trades.forEach((t) => {
          const ts = cMain.timeScale();
          const x = ts.timeToCoordinate(t.date as any);
          if (x === null) return;

          const isBuy = t.type === "buy";
          const candle = dateHighLow[t.date];

          // 매수: 캔들 low 아래, 매도: 캔들 high 위
          const anchorPrice = candle
            ? (isBuy ? candle.low : candle.high)
            : t.price;
          const yAnchor = sCandle.priceToCoordinate(anchorPrice);
          if (yAnchor === null) return;

          const marker = document.createElement("div");
          marker.className = "trade-marker";
          // 매수: 화살표+텍스트가 캔들 low 아래로, 매도: 텍스트+화살표가 캔들 high 위로
          const markerOffset = isBuy ? 6 : 42;
          marker.style.cssText = `
            position: absolute;
            left: ${x - 8}px;
            top: ${isBuy ? yAnchor + markerOffset : yAnchor - markerOffset}px;
            z-index: 20;
            pointer-events: auto;
            cursor: default;
            font-size: 14px;
            line-height: 1;
            text-align: center;
          `;
          marker.innerHTML = isBuy
            ? `<div style="color:#EF5350">▲</div><div style="color:#EF5350;font-size:8px;white-space:nowrap">${fmtNum(t.price)}<br>${t.quantity}주</div>`
            : `<div style="color:#42A5F5;font-size:8px;white-space:nowrap">${fmtNum(t.price)}<br>${t.quantity}주</div><div style="color:#42A5F5">▼</div>`;
          marker.title = `${isBuy ? "매수" : "매도"} ${t.date}\n${fmtNum(t.price)} x ${t.quantity}`;
          mainEl.style.position = "relative";
          mainEl.appendChild(marker);
        });
      };

      // 초기 + 스크롤/줌 시 위치 업데이트
      setTimeout(updateMarkers, 100);
      cMain.timeScale().subscribeVisibleLogicalRangeChange(updateMarkers);
      cMain.subscribeCrosshairMove(updateMarkers);
    }

    // MA선
    Object.entries(data.ma).forEach(([key, vals]) => {
      const s = cMain.addSeries(LineSeries, {
        color: MA_COLORS[key] || "#888", lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "custom", formatter: (p: any) => fmtNum(Number(p)), minMove },
      });
      s.setData(dates.map((d, i) => ({ time: d, value: vals[i] })).filter((p) => p.value !== null) as any[]);
    });

    // 4) 거래량 (별도 차트) + MA5/MA60
    const cVol = mk(refs.vol.current!, 60);
    const sVol = cVol.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceLineVisible: false, lastValueVisible: false,
    });
    sVol.setData(dates.map((d, i) => ({
      time: d, value: data.ohlcv.volume[i],
      color: data.ohlcv.close[i] >= data.ohlcv.open[i] ? "rgba(239,83,80,0.4)" : "rgba(38,166,154,0.4)",
    })) as any);

    // 거래량 MA5 (노란선)
    if (data.vol_ma5) {
      const sVolMa5 = cVol.addSeries(LineSeries, {
        color: "#FFEB3B", lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "volume" },
      });
      sVolMa5.setData(dates.map((d, i) => ({ time: d, value: data.vol_ma5![i] })).filter((p) => p.value != null) as any[]);
    }

    // 거래량 MA60 (주황선)
    if (data.vol_ma60) {
      const sVolMa60 = cVol.addSeries(LineSeries, {
        color: "#FF9800", lineWidth: 1,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "volume" },
      });
      sVolMa60.setData(dates.map((d, i) => ({ time: d, value: data.vol_ma60![i] })).filter((p) => p.value != null) as any[]);
    }

    // 5) RS
    const cRS = mk(refs.rs.current!, 80);
    const sRS = cRS.addSeries(LineSeries, {
      color: "#FF6D00", lineWidth: 2 as any,
      priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: true,
    });
    sRS.setData(dates.map((d, i) => ({ time: d, value: data.rs.line[i] })).filter((p) => p.value !== null) as any[]);

    // RS 기준선 100
    const sRSref = cRS.addSeries(LineSeries, {
      color: "#333", lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    sRSref.setData(dates.map((d) => ({ time: d, value: 100 })) as any[]);

    // 6) ATR (날짜축 표시)
    const cATR = mk(refs.atr.current!, 60, true);
    const sATR = cATR.addSeries(LineSeries, {
      color: "#26A69A", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: true,
    });
    sATR.setData(dates.map((d, i) => ({ time: d, value: data.atr[i] })).filter((p) => p.value !== null) as any[]);

    // 차트 배열
    const all = [cEntry, cSell, cMain, cVol, cRS, cATR];
    chartsRef.current = all;

    // 초기 범위: visibleDays 기준으로 최근 N일 표시
    const totalBars = dates.length;
    const initialRange = {
      from: Math.max(0, totalBars - visibleDays) - 0.5,
      to: totalBars - 0.5,
    };

    // requestAnimationFrame으로 초기 동기화 보장
    requestAnimationFrame(() => {
      all.forEach((ch) => {
        ch.timeScale().setVisibleLogicalRange(initialRange);
      });

      // 시간축 동기화 이벤트 바인딩 (초기 동기화 후)
      all.forEach((src) => {
        src.timeScale().subscribeVisibleLogicalRangeChange((newRange: LogicalRange | null) => {
          if (isSyncing.current || !newRange) return;
          isSyncing.current = true;
          all.forEach((dst) => {
            if (dst !== src) dst.timeScale().setVisibleLogicalRange(newRange);
          });
          isSyncing.current = false;
        });

        src.subscribeCrosshairMove((param) => {
          const t = param.time as string | undefined;
          if (t) {
            setHIdx(dates.indexOf(t));
            // main 차트의 crosshair 좌표를 사용
            if (src === cMain && param.point) {
              const wrapperEl = wrapperRef.current;
              const mainEl = refs.main.current;
              if (wrapperEl && mainEl) {
                const wrapperRect = wrapperEl.getBoundingClientRect();
                const mainRect = mainEl.getBoundingClientRect();
                setTooltipPos({
                  x: param.point.x,
                  y: mainRect.top - wrapperRect.top + param.point.y,
                });
              }
            }
          } else {
            setHIdx(-1);
            setTooltipPos(null);
          }
        });
      });
    });

    // 반응형
    const onResize = () => {
      const nw = refs.main.current?.clientWidth || w;
      all.forEach((ch) => ch.applyOptions({ width: nw }));
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      all.forEach((ch) => ch.remove());
      chartsRef.current = [];
    };
  }, [data]);

  // 플로팅 툴팁 위치 계산
  const getTooltipStyle = (): React.CSSProperties => {
    if (!tooltipPos || hIdx < 0) return { display: "none" };
    const wrapperEl = wrapperRef.current;
    const tooltipEl = tooltipRef.current;
    if (!wrapperEl) return { display: "none" };
    const ww = wrapperEl.clientWidth;
    const tw = tooltipEl?.clientWidth || 220;
    // 마우스 오른쪽에 표시, 넘치면 왼쪽
    const xPos = tooltipPos.x + 20 + tw > ww ? tooltipPos.x - tw - 20 : tooltipPos.x + 20;
    return {
      position: "absolute",
      left: xPos,
      top: tooltipPos.y - 40,
      zIndex: 40,
      pointerEvents: "none" as const,
    };
  };

  return (
    <div className="border border-gray-800 rounded-lg overflow-hidden relative" ref={wrapperRef}>
      {/* MA 범례 (항상 표시) */}
      <div className="bg-[#0d1117] px-3 py-1 flex items-center gap-3 text-[10px] font-mono border-b border-gray-800">
        {Object.entries(MA_COLORS).map(([k, col]) => <span key={k} style={{ color: col }}>{MA_LABELS[k]}</span>)}
        <span className="text-gray-600">|</span>
        <span style={{ color: "#5C6BC0" }}>- - 벤치마크</span>
      </div>

      {/* 플로팅 툴팁 */}
      <div ref={tooltipRef} style={getTooltipStyle()}
        className="bg-[#161b22]/95 border border-gray-700 rounded-lg px-3 py-2 text-xs font-mono shadow-xl backdrop-blur-sm min-w-[200px]">
        <div className="text-gray-400 mb-1.5">{data.ohlcv.dates[idx]}</div>
        {/* 종가 → 고가 → 저가 → 시가 */}
        <div className="grid grid-cols-[auto_1fr_auto] gap-x-2 gap-y-0.5">
          <span className="text-gray-500">종가</span>
          <span className={up ? "text-red-400 text-right" : "text-teal-400 text-right"}>{fmtNum(c)}</span>
          <span className={c >= pc ? "text-red-400" : "text-teal-400"}>{pctVsPrev(c)}</span>

          <span className="text-gray-500">고가</span>
          <span className={up ? "text-red-400 text-right" : "text-teal-400 text-right"}>{fmtNum(h)}</span>
          <span className={h >= pc ? "text-red-400" : "text-teal-400"}>{pctVsPrev(h)}</span>

          <span className="text-gray-500">저가</span>
          <span className={up ? "text-red-400 text-right" : "text-teal-400 text-right"}>{fmtNum(l)}</span>
          <span className={l >= pc ? "text-red-400" : "text-teal-400"}>{pctVsPrev(l)}</span>

          <span className="text-gray-500">시가</span>
          <span className={up ? "text-red-400 text-right" : "text-teal-400 text-right"}>{fmtNum(o)}</span>
          <span className={o >= pc ? "text-red-400" : "text-teal-400"}>{pctVsPrev(o)}</span>
        </div>

        <div className="text-gray-500 mt-1">
          Vol <span className="text-gray-300">{fmtVol(data.ohlcv.volume[idx])}</span>
          {data.vol_ma5 && data.vol_ma5[idx] != null && <span className="ml-2" style={{color:"#FFEB3B"}}>MA5 {fmtVol(data.vol_ma5[idx]!)}</span>}
          {data.vol_ma60 && data.vol_ma60[idx] != null && <span className="ml-2" style={{color:"#FF9800"}}>MA60 {fmtVol(data.vol_ma60[idx]!)}</span>}
        </div>

        {/* 이동평균선 */}
        <div className="border-t border-gray-700/50 mt-1.5 pt-1.5 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
          {Object.entries(data.ma).map(([k, vals]) => {
            const v = vals[idx];
            if (v == null) return null;
            return (
              <React.Fragment key={k}>
                <span style={{ color: MA_COLORS[k] || "#888" }}>{MA_LABELS[k] || k}</span>
                <span className="text-gray-300 text-right">{fmtNum(v)}</span>
              </React.Fragment>
            );
          })}
        </div>

        {/* RS / ATR / 신호 */}
        <div className="border-t border-gray-700/50 mt-1.5 pt-1.5 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
          <span className="text-gray-500">RS</span>
          <span className="text-orange-400 text-right">{data.rs.line[idx] != null ? Number(data.rs.line[idx]).toFixed(1) : "—"}</span>
          <span className="text-gray-500">ATR</span>
          <span className="text-teal-400 text-right">{data.atr[idx] != null ? data.atr[idx]?.toFixed(1) + "%" : "—"}</span>
          <span className="text-gray-500">진입</span>
          <span className="text-right" style={{ color: barColor(data.signals.entry[idx]) }}>{(data.signals.entry[idx] * 100).toFixed(0)}</span>
          <span className="text-gray-500">분배</span>
          <span className="text-right" style={{ color: barColor(data.signals.sell[idx]) }}>{(data.signals.sell[idx] * 100).toFixed(0)}</span>
        </div>
      </div>

      {/* 진입신호 */}
      <div className="relative">
        <span className="absolute top-1 left-1 z-10 text-[9px] text-gray-300 font-mono pointer-events-none">진입신호</span>
        <div ref={refs.entry} />
      </div>

      {/* 분배신호 */}
      <div className="relative mt-2">
        <span className="absolute top-1 left-1 z-10 text-[9px] text-gray-300 font-mono pointer-events-none">분배신호</span>
        <div ref={refs.sell} />
      </div>

      {/* 캔들 + MA */}
      <div className="mt-2">
        <div ref={refs.main} />
      </div>

      {/* 거래량 */}
      <div className="relative mt-2">
        <span className="absolute top-1 left-1 z-10 text-[9px] text-gray-300 font-mono pointer-events-none">거래량</span>
        <div ref={refs.vol} />
      </div>

      {/* RS */}
      <div className="relative mt-2">
        <span className="absolute top-1 left-1 z-10 text-[9px] text-orange-400 font-mono pointer-events-none">RS Line</span>
        <div ref={refs.rs} />
      </div>

      {/* ATR */}
      <div className="relative mt-2">
        <span className="absolute top-1 left-1 z-10 text-[9px] text-teal-400 font-mono pointer-events-none">ATR%</span>
        <div ref={refs.atr} />
      </div>
    </div>
  );
}
