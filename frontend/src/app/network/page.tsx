"use client";

import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { api } from "@/lib/api";
import type {
  MilestoneRow,
  SankeyPayload,
  ShipmentListItem,
  TraceLeg,
  TracePayload,
} from "@/lib/api";
import ChartPanel, { DARK_AXIS } from "@/components/ChartPanel";

const MODE_STYLE: Record<string, { icon: string; color: string; label: string }> = {
  SEA: { icon: "🚢", color: "border-indigo-500/60 bg-indigo-950/30", label: "text-indigo-300" },
  AIR: { icon: "✈️", color: "border-cyan-500/60 bg-cyan-950/30", label: "text-cyan-300" },
  TRUCK: { icon: "🚛", color: "border-emerald-500/60 bg-emerald-950/30", label: "text-emerald-300" },
};

const STATUS_STYLE: Record<string, string> = {
  DELIVERED: "bg-emerald-950/60 text-emerald-400 border-emerald-800",
  DELAYED: "bg-amber-950/60 text-amber-400 border-amber-800",
  EXCEPTION: "bg-rose-950/60 text-rose-400 border-rose-800",
};

const CHAINS = ["ALL", "SEA_AIR_TRUCK", "TRUCK_AIR_TRUCK", "DIRECT_AIR"];
const STATUSES = ["", "DELIVERED", "DELAYED", "EXCEPTION"];

function fmtDelay(min: number): { text: string; cls: string } {
  if (min == null) return { text: "—", cls: "text-slate-500" };
  if (min <= 15) return { text: "on time", cls: "text-emerald-400" };
  const h = Math.round(min / 60 * 10) / 10;
  return { text: `+${h} h`, cls: h > 20 ? "text-rose-400" : "text-amber-400" };
}

function fmtTs(ts: string): string {
  return ts.slice(5, 16).replace("T", " ");
}

export default function NetworkPage() {
  const [chain, setChain] = useState("ALL");
  const [status, setStatus] = useState("");
  const [shipments, setShipments] = useState<ShipmentListItem[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TracePayload | null>(null);
  const [milestones, setMilestones] = useState<MilestoneRow[] | null>(null);
  const [sankey, setSankey] = useState<SankeyPayload | null>(null);

  useEffect(() => {
    api.shipments(chain === "ALL" ? undefined : chain, status || undefined)
      .then((rows) => {
        setShipments(rows);
        if (rows.length > 0) setSelectedId((cur) => cur ?? rows[0].shipment_id);
      })
      .catch(() => setShipments([]));
  }, [chain, status]);

  useEffect(() => {
    if (!selectedId) return;
    setTrace(null);
    setMilestones(null);
    api.trace(selectedId).then(setTrace).catch(() => setTrace(null));
    api.milestones(selectedId).then((r) => setMilestones(r.milestones)).catch(() => setMilestones(null));
  }, [selectedId]);

  useEffect(() => {
    api.sankey().then(setSankey).catch(() => {});
  }, []);

  const sankeyOption: EChartsOption | null = useMemo(() => {
    if (!sankey) return null;
    return {
      series: [
        {
          type: "sankey",
          left: 20,
          right: 120,
          top: 10,
          bottom: 10,
          nodeWidth: 12,
          nodeGap: 10,
          emphasis: { focus: "adjacency" },
          data: sankey.nodes.map((n) => ({
            name: n.name,
            itemStyle: {
              color: n.name.includes("METRO")
                ? "#34d399"
                : n.name === "HKG"
                  ? "#f59e0b"
                  : n.name.startsWith("CN") || ["CNSHA", "CNNGB", "CNYTN", "CNCAN", "SZX"].includes(n.name)
                    ? "#818cf8"
                    : "#22d3ee",
            },
          })),
          links: sankey.links.map((l) => ({ ...l })),
          label: { color: "#8b9bb4", fontSize: 10 },
          lineStyle: { color: "gradient", opacity: 0.25, curveness: 0.5 },
        },
      ],
      tooltip: { trigger: "item" },
    };
  }, [sankey]);

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        {/* Shipment list */}
        <div className="rounded-xl border border-slate-800 bg-[#0f1729]">
          <div className="border-b border-slate-800 p-3">
            <div className="flex flex-wrap gap-1">
              {CHAINS.map((c) => (
                <button
                  key={c}
                  onClick={() => setChain(c)}
                  className={`rounded-md border px-2 py-1 text-[10px] font-medium transition-colors ${
                    chain === c
                      ? "border-cyan-700 bg-cyan-950/60 text-cyan-300"
                      : "border-slate-800 text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {c === "ALL" ? "ALL CHAINS" : c.replace(/_/g, " ")}
                </button>
              ))}
            </div>
            <div className="mt-2 flex gap-1">
              {STATUSES.map((s) => (
                <button
                  key={s || "any"}
                  onClick={() => setStatus(s)}
                  className={`rounded-md border px-2 py-1 text-[10px] font-medium transition-colors ${
                    status === s
                      ? "border-slate-600 bg-slate-800 text-slate-200"
                      : "border-slate-800 text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {s || "ANY STATUS"}
                </button>
              ))}
            </div>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {shipments === null && (
              <div className="p-4 text-xs text-slate-500">Loading shipments…</div>
            )}
            {shipments?.length === 0 && (
              <div className="p-4 text-xs text-slate-500">No shipments match.</div>
            )}
            {shipments?.map((s) => (
              <button
                key={s.shipment_id}
                onClick={() => setSelectedId(s.shipment_id)}
                className={`block w-full border-b border-slate-800/60 px-3 py-2.5 text-left transition-colors hover:bg-slate-800/40 ${
                  selectedId === s.shipment_id ? "bg-cyan-950/30" : ""
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono font-semibold text-slate-200">{s.shipment_id}</span>
                  <span className={`rounded border px-1.5 py-0.5 text-[9px] ${STATUS_STYLE[s.status] ?? ""}`}>
                    {s.status}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                  <span className="truncate pr-2">{s.customer_name}</span>
                  <span className="shrink-0 text-slate-400">
                    {s.origin_location} → {s.destination_location}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Trace */}
        <div className="rounded-xl border border-slate-800 bg-[#0f1729] p-4">
          {!trace && <div className="text-xs text-slate-500">Select a shipment…</div>}
          {trace && (
            <>
              <div className="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <h3 className="font-mono text-sm font-bold text-white">{trace.shipment.shipment_id}</h3>
                <span className="text-xs text-slate-400">{trace.shipment.customer_name} · {trace.shipment.region}</span>
                <span className={`rounded border px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[trace.shipment.status] ?? ""}`}>
                  {trace.shipment.status}
                </span>
                <span className="ml-auto text-[11px] text-slate-500">
                  {trace.shipment.transport_chain_type} · {trace.shipment.cargo_category} ·{" "}
                  {Math.round(trace.shipment.total_chargeable_weight_kg).toLocaleString()} kg ·{" "}
                  ${Math.round(trace.shipment.contracted_revenue_usd).toLocaleString()}
                </span>
              </div>

              {/* shipment-level dual-track milestones */}
              {milestones && (
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {milestones
                    .filter((m) => m.leg_id === null)
                    .map((m, i) => (
                      <MilestoneChip key={`${m.code}-${i}`} m={m} />
                    ))}
                </div>
              )}

              <div className="space-y-0">
                {trace.legs.map((leg, i) => (
                  <LegRow
                    key={leg.leg_id}
                    leg={leg}
                    last={i === trace.legs.length - 1}
                    legMilestones={milestones?.filter((m) => m.leg_id === leg.leg_id)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {sankeyOption && (
        <ChartPanel
          title="Modal Flow through the HKG Hub — feeder origins → hub → air lanes → metro delivery (leg volume)"
          option={sankeyOption}
          height={340}
        />
      )}
    </div>
  );
}

function fmtShort(ts: string): string {
  return ts.slice(5, 16).replace("T", " ");
}

const DEV_STYLE: Record<string, string> = {
  ON_TIME: "border-emerald-800 bg-emerald-950/40 text-emerald-300",
  LATE: "border-amber-800 bg-amber-950/40 text-amber-300",
  MISSING: "border-rose-800 bg-rose-950/40 text-rose-300",
};

function MilestoneChip({ m }: { m: MilestoneRow }) {
  const cls = DEV_STYLE[m.deviation] ?? DEV_STYLE.MISSING;
  return (
    <span className={`rounded-md border px-2 py-1 text-[10px] leading-tight ${cls}`}>
      <span className="font-bold">{m.code}</span>
      <span className="mx-1 opacity-60">plan {fmtShort(m.planned_ts)}</span>
      {m.deviation === "MISSING" ? (
        <span className="font-semibold">NOT REPORTED</span>
      ) : (
        <span>act {fmtShort(m.actual_ts!)}</span>
      )}
    </span>
  );
}

function LegRow({
  leg,
  last,
  legMilestones,
}: {
  leg: TraceLeg;
  last: boolean;
  legMilestones?: MilestoneRow[];
}) {
  const style = MODE_STYLE[leg.transport_mode] ?? MODE_STYLE.TRUCK;
  const delay = fmtDelay(leg.delay_minutes);
  return (
    <div className="flex gap-3">
      {/* rail */}
      <div className="flex flex-col items-center">
        <div className={`flex h-9 w-9 items-center justify-center rounded-lg border text-lg ${style.color}`}>
          {style.icon}
        </div>
        {!last && <div className="w-px flex-1 bg-slate-700" />}
      </div>
      {/* content */}
      <div className="min-w-0 flex-1 pb-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={`text-xs font-bold uppercase tracking-wide ${style.label}`}>
            {leg.transport_mode} · LEG {leg.leg_sequence}
          </span>
          <span className="text-sm font-semibold text-slate-200">
            {leg.origin_facility} → {leg.destination_facility}
          </span>
          <span className="font-mono text-[11px] text-slate-500">
            {leg.carrier_code} {leg.voyage_flight_no}
          </span>
          <span className={`ml-auto text-xs font-semibold ${delay.cls}`}>{delay.text}</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500">
          <span>dep {fmtTs(leg.actual_depart_ts || leg.planned_depart_ts)}</span>
          <span>arr {fmtTs(leg.actual_arrive_ts || leg.planned_arrive_ts)}</span>
          <span>{Math.round(leg.distance_km).toLocaleString()} km</span>
          <span>${leg.allocated_cost_usd.toLocaleString()}</span>
          <span className={leg.leg_status === "COMPLETED" ? "text-emerald-500" : "text-amber-500"}>
            {leg.leg_status}
          </span>
        </div>
        {legMilestones && legMilestones.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {legMilestones.map((m, i) => (
              <MilestoneChip key={`${m.code}-${i}`} m={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
