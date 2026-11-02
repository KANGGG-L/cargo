"use client";

import { useEffect, useState } from "react";
import type { EChartsOption } from "echarts";
import { CircleAlert, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import type { NetworkPayload, OverviewPayload, TrendsPayload } from "@/lib/api";
import ChartPanel, { DARK_AXIS, DARK_LEGEND, SERIES_COLORS } from "@/components/ChartPanel";
import KpiCard from "@/components/KpiCard";

const CATEGORY_STYLE: Record<string, string> = {
  WEATHER: "border-sky-200 bg-sky-50 text-sky-700",
  PORT_CONGESTION: "border-amber-200 bg-amber-50 text-amber-700",
  BORDER_CONGESTION: "border-amber-200 bg-amber-50 text-amber-700",
  COMMERCIAL_MISCONFIGURATION: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700",
};

export default function OverviewPage() {
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [trends, setTrends] = useState<TrendsPayload | null>(null);
  const [network, setNetwork] = useState<NetworkPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.overview(), api.trends(), api.network()])
      .then(([o, t, n]) => {
        setOverview(o);
        setTrends(t);
        setNetwork(n);
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">
        Backend unreachable at{" "}
        <code>{process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"}</code> — start it
        with <code>uvicorn app.main:app --port 8000</code>.
        <div className="mt-2 text-xs text-red-500/80">{error}</div>
      </div>
    );
  }

  if (!overview || !trends || !network) {
    return <div className="animate-pulse text-sm text-zinc-500">Loading control tower…</div>;
  }

  const k = overview.kpis;

  const windowArea = (name: string, from: string, to: string) => ({
    itemStyle: { color: "#f4f4f5" },
    label: { color: "#a1a1aa", fontSize: 10 },
    data: [[{ name, xAxis: from }, { xAxis: to }]],
  });

  const dailyOption: EChartsOption = {
    legend: { ...DARK_LEGEND, data: ["Air OTP %", "Load Factor %"] },
    grid: { left: 40, right: 40, top: 30, bottom: 45 },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    xAxis: { type: "category", data: trends.daily.map((d) => d.date), ...DARK_AXIS },
    yAxis: [
      { type: "value", min: 0, max: 100, ...DARK_AXIS },
      { type: "value", ...DARK_AXIS },
    ],
    series: [
      {
        name: "Air OTP %",
        type: "line",
        showSymbol: false,
        lineStyle: { width: 1.5, color: SERIES_COLORS[0] },
        itemStyle: { color: SERIES_COLORS[0] },
        data: trends.daily.map((d) => d.air_otp_pct),
        markArea: windowArea("Typhoon", "2025-09-15", "2025-09-21"),
      },
      {
        name: "Load Factor %",
        type: "line",
        yAxisIndex: 1,
        showSymbol: false,
        lineStyle: { width: 1.5, color: SERIES_COLORS[1] },
        itemStyle: { color: SERIES_COLORS[1] },
        data: trends.daily.map((d) => d.load_factor_pct),
      },
    ] as EChartsOption["series"],
    tooltip: { trigger: "axis" },
  };

  const truckOption: EChartsOption = {
    legend: { ...DARK_LEGEND, data: ["Truck OTP %", "Avg Crossing (min)"] },
    grid: { left: 40, right: 45, top: 30, bottom: 45 },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    xAxis: { type: "category", data: trends.daily_truck.map((d) => d.date), ...DARK_AXIS },
    yAxis: [
      { type: "value", min: 0, max: 100, ...DARK_AXIS },
      { type: "value", ...DARK_AXIS },
    ],
    series: [
      {
        name: "Truck OTP %",
        type: "line",
        showSymbol: false,
        lineStyle: { width: 1.5, color: SERIES_COLORS[1] },
        itemStyle: { color: SERIES_COLORS[1] },
        data: trends.daily_truck.map((d) => d.truck_otp_pct),
        markArea: windowArea("SZBP congestion", "2025-11-10", "2025-11-24"),
      },
      {
        name: "Avg Crossing (min)",
        type: "line",
        yAxisIndex: 1,
        showSymbol: false,
        lineStyle: { width: 1.5, color: SERIES_COLORS[3] },
        itemStyle: { color: SERIES_COLORS[3] },
        data: trends.daily_truck.map((d) => d.avg_crossing_minutes),
      },
    ] as EChartsOption["series"],
    tooltip: { trigger: "axis" },
  };

  const seaCorridors = [...new Set(trends.weekly_sea.map((r) => r.corridor))];
  const seaWeeks = [...new Set(trends.weekly_sea.map((r) => r.week))].sort();
  const seaOption: EChartsOption = {
    legend: { ...DARK_LEGEND, data: seaCorridors },
    grid: { left: 40, right: 30, top: 30, bottom: 45 },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    xAxis: { type: "category", data: seaWeeks, ...DARK_AXIS },
    yAxis: { type: "value", min: 0, max: 100, ...DARK_AXIS },
    series: seaCorridors.map((cor, i) => ({
      name: cor,
      type: "line" as const,
      showSymbol: false,
      lineStyle: { width: 1.5, color: SERIES_COLORS[i % SERIES_COLORS.length] },
      itemStyle: { color: SERIES_COLORS[i % SERIES_COLORS.length] },
      data: seaWeeks.map(
        (w) =>
          trends.weekly_sea.find((r) => r.week === w && r.corridor === cor)?.sea_otp_pct ?? null
      ),
      ...(cor === "YANTIAN_FEEDER_HKG"
        ? { markArea: windowArea("Congestion", "2026-03-02", "2026-03-16") }
        : {}),
    })) as EChartsOption["series"],
    tooltip: { trigger: "axis" },
  };

  const monthlyOption: EChartsOption = {
    legend: { ...DARK_LEGEND, data: ["Revenue $M", "Gross Margin %"] },
    grid: { left: 45, right: 40, top: 30, bottom: 25 },
    xAxis: { type: "category", data: trends.monthly.map((m) => m.month), ...DARK_AXIS },
    yAxis: [
      { type: "value", ...DARK_AXIS },
      { type: "value", min: 0, max: 30, ...DARK_AXIS },
    ],
    series: [
      {
        name: "Revenue $M",
        type: "bar",
        itemStyle: { color: "#a1a1aa", borderRadius: [3, 3, 0, 0] },
        data: trends.monthly.map((m) => m.revenue_musd),
      },
      {
        name: "Gross Margin %",
        type: "line",
        yAxisIndex: 1,
        lineStyle: { width: 2, color: SERIES_COLORS[0] },
        itemStyle: { color: SERIES_COLORS[0] },
        data: trends.monthly.map((m) => m.gross_margin_pct),
      },
    ],
    tooltip: { trigger: "axis" },
  };

  const modeOption: EChartsOption = {
    legend: DARK_LEGEND,
    series: [
      {
        type: "pie",
        radius: ["45%", "72%"],
        center: ["50%", "55%"],
        label: { color: "#71717a", formatter: "{b}\n{c} legs" },
        data: network.mode_split.map((m, i) => ({
          name: m.mode,
          value: m.legs,
          itemStyle: { color: SERIES_COLORS[i % SERIES_COLORS.length] },
        })),
      },
    ],
    tooltip: {},
  };

  const laneOption: EChartsOption = {
    grid: { left: 60, right: 30, top: 10, bottom: 25 },
    xAxis: { type: "value", ...DARK_AXIS },
    yAxis: {
      type: "category",
      data: network.air_lanes.map((l) => `HKG-${l.dest}`).reverse(),
      ...DARK_AXIS,
    },
    series: [
      {
        type: "bar",
        itemStyle: { color: SERIES_COLORS[0], borderRadius: [0, 3, 3, 0] },
        data: network.air_lanes.map((l) => l.tonnes).reverse(),
      },
    ],
    tooltip: { trigger: "axis" },
  };

  const feederOption: EChartsOption = {
    legend: { ...DARK_LEGEND, data: ["Avg Delay (h)", "Sea OTP %"] },
    grid: { left: 60, right: 40, top: 30, bottom: 25 },
    xAxis: { type: "category", data: network.feeder_ports.map((f) => f.port), ...DARK_AXIS },
    yAxis: [
      { type: "value", ...DARK_AXIS },
      { type: "value", min: 50, max: 100, ...DARK_AXIS },
    ],
    series: [
      {
        name: "Avg Delay (h)",
        type: "bar",
        itemStyle: { color: "#a1a1aa", borderRadius: [3, 3, 0, 0] },
        data: network.feeder_ports.map((f) => f.avg_delay_hours),
      },
      {
        name: "Sea OTP %",
        type: "line",
        yAxisIndex: 1,
        lineStyle: { width: 2, color: SERIES_COLORS[1] },
        itemStyle: { color: SERIES_COLORS[1] },
        data: network.feeder_ports.map((f) => f.sea_otp_pct),
      },
    ],
    tooltip: { trigger: "axis" },
  };

  const checkpointOption: EChartsOption = {
    legend: { ...DARK_LEGEND, data: ["Truck OTP %", "Avg Crossing (min)"] },
    grid: { left: 60, right: 45, top: 30, bottom: 25 },
    xAxis: { type: "category", data: network.truck_checkpoints.map((c) => c.checkpoint), ...DARK_AXIS },
    yAxis: [
      { type: "value", min: 0, max: 100, ...DARK_AXIS },
      { type: "value", ...DARK_AXIS },
    ],
    series: [
      {
        name: "Truck OTP %",
        type: "bar",
        itemStyle: { color: SERIES_COLORS[1], borderRadius: [3, 3, 0, 0] },
        data: network.truck_checkpoints.map((c) => c.truck_otp_pct),
      },
      {
        name: "Avg Crossing (min)",
        type: "line",
        yAxisIndex: 1,
        lineStyle: { width: 2, color: SERIES_COLORS[3] },
        itemStyle: { color: SERIES_COLORS[3] },
        data: network.truck_checkpoints.map((c) => c.avg_crossing_minutes),
      },
    ],
    tooltip: { trigger: "axis" },
  };

  const chainMax = Math.max(...network.chain_mix.map((x) => x.revenue_musd));

  return (
    <div className="space-y-5">
      {/* KPI rows — three modes at equal footing */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard label="Air OTP (±15min)" value={k.air_otp_pct} unit="%" hint="flight leg level" />
        <KpiCard label="Sea OTP (±4h)" value={k.sea_otp_pct} unit="%" hint="feeder barge legs" />
        <KpiCard label="Truck OTP (±1h)" value={k.truck_otp_pct} unit="%" hint="cross-border legs" />
        <KpiCard label="E2E Shipment OTP" value={k.multimodal_otp_pct} unit="%" hint="±60 min tolerance" />
        <KpiCard label="Cargo Load Factor" value={k.load_factor_pct} unit="%" hint="RTK / ATK, HKG network" />
        <KpiCard label="Hub Dwell (avg)" value={k.avg_dwell_hours} unit="h" hint="feeder arrival → wheels up" />
        <KpiCard
          label="Revenue (18 mo)"
          value={`$${k.total_revenue_musd}M`}
          hint={`${k.total_shipments.toLocaleString()} shipments · ${Math.round(k.total_tonnes).toLocaleString()} t`}
        />
        <KpiCard
          label="Gross Margin"
          value={k.gross_margin_pct}
          unit="%"
          tone={k.gross_margin_pct > 15 ? "good" : "warn"}
        />
      </div>

      {/* Disruption banner */}
      <div className="flex flex-wrap gap-2">
        {overview.recent_disruptions.map((d) => (
          <div
            key={d.event_id}
            className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs ${
              CATEGORY_STYLE[d.event_category] ??
              "border-zinc-200 bg-zinc-50 text-zinc-600"
            }`}
          >
            {d.event_category === "WEATHER" ? (
              <TriangleAlert className="h-3.5 w-3.5" />
            ) : (
              <CircleAlert className="h-3.5 w-3.5" />
            )}
            <span className="font-semibold">{d.event_code}</span>
            <span className="opacity-50">·</span>
            {d.primary_location}
            <span className="opacity-50">·</span>
            {d.start_timestamp.slice(0, 10)} → {d.end_timestamp.slice(0, 10)}
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartPanel title="Air — Daily OTP & Load Factor" subtitle="typhoon window shaded" option={dailyOption} height={320} />
        <ChartPanel title="Road — Daily Truck OTP & Border Crossing Time" subtitle="SZBP congestion shaded" option={truckOption} height={320} />
        <ChartPanel title="Sea — Weekly Feeder Departure OTP" subtitle="by corridor, Yantian congestion shaded" option={seaOption} height={320} />
        <ChartPanel title="Monthly Revenue & Gross Margin" option={monthlyOption} height={320} />
        <ChartPanel title="Transport Mode Split (legs)" option={modeOption} height={280} />
        <ChartPanel title="Top Air Lanes by Carried Tonnes" option={laneOption} height={280} />
        <ChartPanel title="Feeder Port Health (sea legs into HKG)" option={feederOption} height={280} />
        <ChartPanel title="Cross-Border Checkpoints (truck, KPI daily)" option={checkpointOption} height={280} />
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-zinc-900">
            Chain Mix — Revenue by Routing Pattern
          </h3>
          <div className="space-y-3">
            {network.chain_mix.map((c) => (
              <div key={c.chain}>
                <div className="mb-1 flex justify-between text-xs text-zinc-500">
                  <span>{c.chain}</span>
                  <span className="tabular-nums">
                    ${c.revenue_musd}M · {c.shipments.toLocaleString()} shipments
                  </span>
                </div>
                <div className="h-2 w-full rounded-full bg-zinc-100">
                  <div
                    className="h-2 rounded-full bg-indigo-600"
                    style={{ width: `${(c.revenue_musd / chainMax) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-[11px] leading-relaxed text-zinc-500">
            Sea-Air-Truck is the largest routing pattern by revenue — cargo arrives by feeder
            barge into HKG, transits the hub and flies out on long-haul freighters.
          </p>
        </div>
      </div>
    </div>
  );
}
