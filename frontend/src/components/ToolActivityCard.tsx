"use client";

import { useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import { DARK_AXIS, DARK_LEGEND } from "@/components/ChartPanel";

export interface ToolPayload {
  sql?: string;
  columns?: string[];
  rows?: (string | number | null)[][];
  row_count?: number;
  chart?: { type: "bar" | "line" | "pie"; x_key: string; y_keys: string[] } | null;
  error?: string;
}

export interface ToolEvent {
  name: string;
  summary: string;
  payload?: ToolPayload;
  running: boolean;
}

const TOOL_LABEL: Record<string, string> = {
  query_data: "Querying control tower database",
  diagnose_anomaly: "Diagnosing anomalies",
  simulate_disruption: "Running disruption simulation",
  quote_booking: "Preparing freight quote",
};

function chartOption(ev: ToolEvent): EChartsOption | null {
  const { chart, columns, rows } = ev.payload ?? {};
  if (!chart || !columns || !rows?.length) return null;
  const xIdx = columns.indexOf(chart.x_key);
  const yIdx = chart.y_keys.map((y) => columns.indexOf(y)).filter((i) => i >= 0);
  if (xIdx < 0 || yIdx.length === 0) return null;

  const categories = rows.map((r) => String(r[xIdx] ?? ""));
  const series = yIdx.map((i) => ({
    name: columns[i],
    type: chart.type,
    data: rows.map((r) => (typeof r[i] === "number" ? r[i] : null)),
    showSymbol: rows.length > 30 ? false : true,
    itemStyle: { borderRadius: chart.type === "bar" ? 2 : 0 },
  }));

  if (chart.type === "pie") {
    return {
      legend: DARK_LEGEND,
      series: [
        {
          type: "pie",
          radius: ["40%", "70%"],
          data: rows.map((r) => ({
            name: String(r[xIdx]),
            value: typeof r[yIdx[0]] === "number" ? (r[yIdx[0]] as number) : 0,
          })),
        },
      ],
      tooltip: {},
    };
  }
  return {
    legend: DARK_LEGEND,
    grid: { left: 50, right: 20, top: 30, bottom: 55 },
    xAxis: { type: "category", data: categories, ...DARK_AXIS },
    yAxis: { type: "value", ...DARK_AXIS },
    series: series as EChartsOption["series"],
    dataZoom: rows.length > 40 ? [{ type: "inside" }] : [],
    tooltip: { trigger: "axis" },
  };
}

export default function ToolActivityCard({ ev }: { ev: ToolEvent }) {
  const [open, setOpen] = useState(false);
  const option = useMemo(() => chartOption(ev), [ev]);

  return (
    <div className="my-2 w-full overflow-hidden rounded-lg border border-slate-800 bg-[#0d1526]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-400 hover:bg-slate-800/40"
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            ev.running ? "animate-pulse bg-amber-400" : "bg-emerald-400"
          }`}
        />
        <span className="font-medium text-slate-300">
          {TOOL_LABEL[ev.name] ?? ev.name}
        </span>
        {!ev.running && ev.summary && (
          <span className="text-slate-500">— {ev.summary}</span>
        )}
        <span className="ml-auto text-slate-600">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="min-w-0 overflow-hidden border-t border-slate-800/80 px-3 py-2 text-xs">
          {ev.payload?.error && (
            <div className="text-rose-400">Error: {ev.payload.error}</div>
          )}
          {ev.payload?.sql && (
            <pre className="mb-2 overflow-x-auto rounded bg-black/40 p-2 text-[11px] leading-relaxed text-cyan-200/80">
              {ev.payload.sql}
            </pre>
          )}
          {option && (
            <ReactECharts option={option} style={{ height: 220, width: "100%" }} notMerge />
          )}
          {!option && ev.payload?.columns && ev.payload.columns.length > 0 && (
            <DataTable ev={ev} />
          )}
        </div>
      )}
    </div>
  );
}

function DataTable({ ev }: { ev: ToolEvent }) {
  const { columns, rows } = ev.payload!;
  if (!columns || !rows) return null;
  return (
    <div className="max-h-56 overflow-auto rounded border border-slate-800/60">
      <table className="w-full text-left text-[11px]">
        <thead className="sticky top-0 bg-[#101a30] text-slate-400">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1.5 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="text-slate-300">
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-slate-800/50">
              {r.map((v, j) => (
                <td key={j} className="whitespace-nowrap px-2 py-1">
                  {v ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
