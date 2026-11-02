"use client";

import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

/** Shared light-theme ECharts defaults (zinc grid, 11px labels, fixed series palette). */
export const DARK_AXIS = {
  axisLine: { lineStyle: { color: "#e4e4e7" } },
  axisLabel: { color: "#71717a", fontSize: 11 },
  splitLine: { lineStyle: { color: "#f4f4f5" } },
};

export const DARK_LEGEND = {
  textStyle: { color: "#71717a", fontSize: 11 },
  top: 0,
};

/** Fixed 5-colour categorical palette (indigo / teal / fuchsia / amber / slate). */
export const SERIES_COLORS = ["#4f46e5", "#0e9384", "#d946ef", "#f59e0b", "#64748b"];

export default function ChartPanel({
  title,
  subtitle,
  option,
  height = 300,
}: {
  title: string;
  subtitle?: string;
  option: EChartsOption;
  height?: number;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
        {subtitle && <span className="text-[11px] text-zinc-400">{subtitle}</span>}
      </div>
      <ReactECharts option={option} style={{ height }} notMerge />
    </div>
  );
}
