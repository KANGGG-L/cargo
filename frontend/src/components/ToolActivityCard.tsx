"use client";

import { useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import {
  ChevronDown,
  CircleCheck,
  Clock,
  FileText,
  LoaderCircle,
  MessageSquareText,
  RadioTower,
  ReceiptText,
  TriangleAlert,
} from "lucide-react";
import { DARK_AXIS, DARK_LEGEND } from "@/components/ChartPanel";

export interface ToolPayload {
  sql?: string;
  columns?: string[];
  rows?: (string | number | null)[][];
  row_count?: number;
  chart?: { type: "bar" | "line" | "pie"; x_key: string; y_keys: string[] } | null;
  error?: string;
  /* diagnose_anomaly */
  anchor?: string;
  findings?: Record<string, unknown>[];
  overlapping_events?: Record<string, unknown>[];
  /* simulate_disruption */
  scenario?: string;
  mode?: string;
  recovery_curve?: { day: string; backlog_tonnes: number }[];
  affected_legs?: number;
  revenue_at_risk_musd?: number;
  /* quote_booking */
  legs?: Record<string, unknown>[];
  total_usd?: number;
  estimated_transit_days?: number;
}

export interface ToolEvent {
  name: string;
  summary: string;
  payload?: ToolPayload;
  running: boolean;
}

const TOOL_META: Record<string, { label: string; icon: typeof FileText }> = {
  query_data: { label: "Querying control tower database", icon: FileText },
  diagnose_anomaly: { label: "Diagnosing anomalies", icon: TriangleAlert },
  simulate_disruption: { label: "Running disruption simulation", icon: RadioTower },
  quote_booking: { label: "Preparing freight quote", icon: ReceiptText },
  raise_alert: { label: "Raising exception ticket", icon: MessageSquareText },
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
  const meta = TOOL_META[ev.name] ?? { label: ev.name, icon: FileText };

  return (
    <div className="my-2 w-full overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-zinc-600 hover:bg-zinc-100"
      >
        {ev.running ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin text-zinc-400" />
        ) : (
          <CircleCheck className="h-3.5 w-3.5 text-emerald-600" />
        )}
        <meta.icon className="h-3.5 w-3.5 text-zinc-400" />
        <span className="font-medium text-zinc-800">{meta.label}</span>
        {!ev.running && ev.summary && (
          <span className="text-zinc-500">— {ev.summary}</span>
        )}
        <ChevronDown
          className={`ml-auto h-3.5 w-3.5 text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="min-w-0 overflow-hidden border-t border-zinc-200 px-3 py-2 text-xs">
          {ev.payload?.error && (
            <div className="mb-1.5 text-rose-600">Error: {ev.payload.error}</div>
          )}
          {ev.payload?.sql && (
            <pre className="mb-2 overflow-x-auto rounded-md bg-zinc-900 p-2 text-[11px] leading-relaxed text-zinc-100">
              {ev.payload.sql}
            </pre>
          )}
          {option && (
            <ReactECharts option={option} style={{ height: 220, width: "100%" }} notMerge />
          )}
          {ev.payload?.recovery_curve && <RecoveryChart ev={ev} />}
          {ev.payload?.findings && <FindingsList ev={ev} />}
          {ev.payload?.legs && !option && <QuoteBreakdown ev={ev} />}
          {!option && !ev.payload?.recovery_curve && !ev.payload?.findings && !ev.payload?.legs && (
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
    <div className="max-h-56 overflow-auto rounded-md border border-zinc-200 bg-white">
      <table className="w-full text-left text-[11px]">
        <thead className="sticky top-0 bg-zinc-100 text-zinc-500">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1.5 font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="text-zinc-700">
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-zinc-100">
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

function RecoveryChart({ ev }: { ev: ToolEvent }) {
  const curve = ev.payload!.recovery_curve!;
  return (
    <div className="rounded-md border border-zinc-200 bg-white p-1">
      <div className="px-2 pt-1 text-[11px] text-zinc-500">
        Backlog recovery curve (130% surge capacity after reopening)
      </div>
      <ReactECharts
        style={{ height: 200, width: "100%" }}
        notMerge
        option={{
          grid: { left: 55, right: 20, top: 15, bottom: 30 },
          xAxis: { type: "category", data: curve.map((c) => c.day), ...DARK_AXIS },
          yAxis: { type: "value", name: "tonnes", ...DARK_AXIS },
          series: [
            {
              type: "bar",
              itemStyle: { color: "#0e9384", borderRadius: [3, 3, 0, 0] },
              data: curve.map((c) => c.backlog_tonnes),
            },
          ],
          tooltip: { trigger: "axis" },
        }}
      />
    </div>
  );
}

function FindingsList({ ev }: { ev: ToolEvent }) {
  const { findings, overlapping_events, anchor } = ev.payload!;
  return (
    <div className="space-y-1.5 bg-white">
      <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
        <Clock className="h-3 w-3" /> as of {anchor}
      </div>
      {(findings ?? []).map((f, i) => (
        <div
          key={i}
          className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-800"
        >
          <span className="font-semibold">{String(f.metric)}</span>
          {" · "}
          {String(f.route_lane ?? f.port ?? f.dest)}
          {": "}
          {String(f.baseline_otp ?? f.baseline_delay_h ?? f.baseline_margin)}
          {" → "}
          {String(f.recent_otp ?? f.recent_delay_h ?? f.recent_margin)}
        </div>
      ))}
      {(overlapping_events ?? []).map((e, i) => (
        <div
          key={`e${i}`}
          className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-[11px] text-rose-700"
        >
          {String(e.event_code)} · {String(e.primary_location)} ·{" "}
          {String(e.start_timestamp).slice(0, 10)} → {String(e.end_timestamp).slice(0, 10)}
        </div>
      ))}
      {(!findings || findings.length === 0) && (
        <div className="flex items-center gap-1.5 text-[11px] text-emerald-700">
          <CircleCheck className="h-3 w-3" /> No deviations beyond threshold.
        </div>
      )}
    </div>
  );
}

function QuoteBreakdown({ ev }: { ev: ToolEvent }) {
  const { legs, total_usd, estimated_transit_days } = ev.payload!;
  return (
    <div className="space-y-1.5 bg-white">
      {(legs ?? []).map((l, i) => (
        <div
          key={i}
          className="flex items-center justify-between rounded-md border border-zinc-200 px-2.5 py-1.5 text-[11px] text-zinc-700"
        >
          <span>
            <span className="font-semibold uppercase text-zinc-900">{String(l.mode)}</span>{" "}
            {String(l.origin)} → {String(l.dest)}
          </span>
          <span>
            ${String(l.charge_usd)} · {String(l.weight_break)} · {String(l.avg_transit_days)} d
          </span>
        </div>
      ))}
      <div className="flex justify-between px-2.5 pt-1 text-xs font-semibold text-zinc-900">
        <span>Total · est. {String(estimated_transit_days)} days</span>
        <span className="tabular-nums">${String(total_usd)}</span>
      </div>
    </div>
  );
}
