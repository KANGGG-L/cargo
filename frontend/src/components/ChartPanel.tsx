"use client";

import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

/** Shared dark control-tower defaults for every chart panel. */
export const DARK_AXIS = {
  axisLine: { lineStyle: { color: "#33415c" } },
  axisLabel: { color: "#8b9bb4", fontSize: 10 },
  splitLine: { lineStyle: { color: "#1c2740" } },
};

export const DARK_LEGEND = {
  textStyle: { color: "#8b9bb4", fontSize: 11 },
  top: 0,
};

export default function ChartPanel({
  title,
  option,
  height = 300,
}: {
  title: string;
  option: EChartsOption;
  height?: number;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0f1729] p-4">
      <h3 className="mb-2 text-sm font-semibold tracking-wide text-slate-300">
        {title}
      </h3>
      <ReactECharts option={option} style={{ height }} notMerge />
    </div>
  );
}
