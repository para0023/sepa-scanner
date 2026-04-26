"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  LineSeries,
  HistogramSeries,
  type IChartApi,
} from "lightweight-charts";

interface SubPanelProps {
  dates: string[];
  data: (number | null)[];
  title: string;
  height?: number;
  color?: string;
  type?: "line" | "histogram";
  thresholds?: { value: number; color: string; style?: "dashed" | "solid" }[];
}

function getBarColor(val: number): string {
  if (val <= 0.33) return "rgba(39,174,96,0.85)";   // 녹색
  if (val <= 0.66) return "rgba(243,156,18,0.85)";   // 황색
  return "rgba(192,57,43,0.85)";                      // 적색
}

export default function SubPanelChart({
  dates,
  data,
  title,
  height = 80,
  color = "#888",
  type = "line",
  thresholds,
}: SubPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || !dates.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#0d1117" },
        textColor: "#666",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.02)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      rightPriceScale: {
        borderColor: "#333",
        scaleMargins: { top: 0.1, bottom: 0.05 },
      },
      timeScale: {
        borderColor: "#333",
        visible: false,
      },
      crosshair: {
        horzLine: { visible: false },
        vertLine: { visible: true, color: "rgba(255,255,255,0.1)", style: 2 },
      },
      watermark: { visible: false },
    });

    chartRef.current = chart;

    if (type === "histogram") {
      const series = chart.addSeries(HistogramSeries, {
        priceLineVisible: false,
        lastValueVisible: false,
      });

      const histData = dates
        .map((d, i) => {
          const val = data[i];
          if (val === null) return null;
          return {
            time: d,
            value: val,
            color: getBarColor(val),
          };
        })
        .filter(Boolean) as any[];

      series.setData(histData);
    } else {
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
      });

      const lineData = dates
        .map((d, i) => ({ time: d, value: data[i] }))
        .filter((p) => p.value !== null) as any[];

      series.setData(lineData);
    }

    // 기준선
    if (thresholds) {
      thresholds.forEach((t) => {
        const refSeries = chart.addSeries(LineSeries, {
          color: t.color,
          lineWidth: 1,
          lineStyle: t.style === "dashed" ? 2 : 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        const refData = dates.map((d) => ({ time: d, value: t.value })) as any[];
        refSeries.setData(refData);
      });
    }

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [dates, data, title, height, color, type, thresholds]);

  return (
    <div className="relative">
      <span className="absolute top-1 left-2 z-10 text-[10px] text-gray-500 font-mono pointer-events-none">
        {title}
      </span>
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
