"use client";

import dynamic from "next/dynamic";
import { Bell, Plane, Search, Ship, Truck, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { api } from "@/lib/api";
import type {
  MilestoneRow,
  SankeyPayload,
  ShipmentListItem,
  TrackLeg,
  TraceLeg,
  TracePayload,
} from "@/lib/api";
import ChartPanel, { DARK_AXIS } from "@/components/ChartPanel";

const ShipmentMap = dynamic(() => import("@/components/ShipmentMap"), {
  ssr: false,
  loading: () => <div className="p-6 text-xs text-zinc-500">Loading map…</div>,
});

const MODE_STYLE: Record<string, { icon: LucideIcon; color: string; label: string }> = {
  SEA: { icon: Ship, color: "border-indigo-200 bg-indigo-50", label: "text-indigo-700" },
  AIR: { icon: Plane, color: "border-sky-200 bg-sky-50", label: "text-sky-700" },
  TRUCK: { icon: Truck, color: "border-emerald-200 bg-emerald-50", label: "text-emerald-700" },
};

const STATUS_STYLE: Record<string, string> = {
  DELIVERED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  DELAYED: "bg-amber-50 text-amber-700 border-amber-200",
  EXCEPTION: "bg-rose-50 text-rose-700 border-rose-200",
};

const CHAINS = ["ALL", "SEA_AIR_TRUCK", "TRUCK_AIR_TRUCK", "DIRECT_AIR"];
const STATUSES = ["", "DELIVERED", "DELAYED", "EXCEPTION"];

function fmtDelay(min: number): { text: string; cls: string } {
  if (min == null) return { text: "—", cls: "text-zinc-500" };
  if (min <= 15) return { text: "on time", cls: "text-emerald-700" };
  const h = Math.round(min / 60 * 10) / 10;
  return { text: `+${h} h`, cls: h > 20 ? "text-rose-700" : "text-amber-700" };
}

function fmtTs(ts: string): string {
  return ts.slice(5, 16).replace("T", " ");
}

export default function NetworkPage() {
  const [chain, setChain] = useState("ALL");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [shipments, setShipments] = useState<ShipmentListItem[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TracePayload | null>(null);
  const [milestones, setMilestones] = useState<MilestoneRow[] | null>(null);
  const [tracks, setTracks] = useState<TrackLeg[] | null>(null);
  const [sankey, setSankey] = useState<SankeyPayload | null>(null);
  const [pins, setPins] = useState<{ alert_id: string; shipment_id: string; severity: string; title: string; lat: number; lon: number; location: string }[] | null>(null);
  const [subEmail, setSubEmail] = useState("");
  const [subOpen, setSubOpen] = useState(false);
  const [subMsg, setSubMsg] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!shipments) return null;
    const q = query.trim().toLowerCase();
    if (!q) return shipments;
    return shipments.filter(
      (s) =>
        s.shipment_id.toLowerCase().includes(q) ||
        s.customer_name.toLowerCase().includes(q) ||
        s.origin_location.toLowerCase().includes(q) ||
        s.destination_location.toLowerCase().includes(q)
    );
  }, [shipments, query]);

  // selection derived from the filtered set (falls back to the first match) —
  // no effect needed, so filter changes never select an invisible row
  const activeId =
    filtered && filtered.length > 0
      ? filtered.some((s) => s.shipment_id === selectedId)
        ? selectedId
        : filtered[0].shipment_id
      : null;

  async function subscribe() {
    if (!activeId) return;
    try {
      await api.subscribe(subEmail, activeId);
      setSubMsg(`Subscribed ${subEmail} to ${activeId} milestones & delay alerts`);
      setSubOpen(false);
      setSubEmail("");
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setSubMsg(raw.startsWith("Error: ") ? raw.slice(7) : raw);
    }
  }

  // restore view state from the URL once (shareable links, refresh survival)
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const c = p.get("chain");
    const s = p.get("status");
    const q = p.get("q");
    const sid = p.get("sid");
    const id = requestAnimationFrame(() => {
      if (c && CHAINS.includes(c)) setChain(c);
      if (s && STATUSES.includes(s)) setStatus(s);
      if (q) setQuery(q);
      if (sid) setSelectedId(sid);
    });
    return () => cancelAnimationFrame(id);
  }, []);

  // keep the URL in sync so filters/search/selection survive a reload
  useEffect(() => {
    const p = new URLSearchParams();
    if (chain !== "ALL") p.set("chain", chain);
    if (status) p.set("status", status);
    if (query) p.set("q", query);
    if (activeId) p.set("sid", activeId);
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [chain, status, query, activeId]);

  useEffect(() => {
    api.shipments(chain === "ALL" ? undefined : chain, status || undefined)
      .then((rows) => setShipments(rows))
      .catch(() => setShipments([]));
  }, [chain, status]);

  useEffect(() => {
    if (!activeId) return;
    setTrace(null);
    setMilestones(null);
    setTracks(null);
    api.trace(activeId).then(setTrace).catch(() => setTrace(null));
    api.milestones(activeId).then((r) => setMilestones(r.milestones)).catch(() => setMilestones(null));
    api.tracks(activeId).then((r) => setTracks(r.tracks)).catch(() => setTracks(null));
  }, [activeId]);

  useEffect(() => {
    api.sankey().then(setSankey).catch(() => {});
    api.posture().then((r) => setPins(r.pins)).catch(() => setPins([]));
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
          links: sankey.links.map((l) => {
            // two-tone demand-vs-capacity: green when there's slack, amber as it
            // fills, rose when demand is at/over available capacity
            const u = l.utilization_pct;
            const color =
              u == null ? "#94a3b8" : u >= 90 ? "#f43f5e" : u >= 70 ? "#f59e0b" : "#34d399";
            return {
              source: l.source,
              target: l.target,
              value: l.value,
              lineStyle: { color, opacity: 0.4 },
              demand: l.demand_tonnes,
              capacity: l.capacity_tonnes,
              headroom: l.headroom_tonnes,
              util: u,
            };
          }),
          label: { color: "#8b9bb4", fontSize: 10 },
          lineStyle: { color: "source", opacity: 0.25, curveness: 0.5 },
        },
      ],
      tooltip: {
        trigger: "item",
        formatter: (p: unknown) => {
          const d = p as { dataType?: string; data?: Record<string, unknown>; name?: string };
          if (d.dataType === "edge" && d.data) {
            const cap = d.data.capacity as number | null;
            const util = d.data.util as number | null;
            return (
              `${d.data.source} → ${d.data.target}<br/>` +
              `Demand: <b>${d.data.demand} t</b><br/>` +
              (cap != null
                ? `Capacity: ${cap} t<br/>Headroom: ${d.data.headroom} t<br/>Utilisation: <b>${util}%</b>`
                : `(last-mile / no shared-service capacity)`)
            );
          }
          return d.name ?? "";
        },
      },
    };
  }, [sankey]);

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        {/* Shipment list */}
        <div className="rounded-xl border border-zinc-200 bg-white">
          <div className="border-b border-zinc-200 p-3">
            <div className="flex flex-wrap gap-1">
              {CHAINS.map((c) => (
                <button
                  key={c}
                  onClick={() => setChain(c)}
                  className={`rounded-md border px-2 py-1 text-[10px] font-medium transition-colors ${
                    chain === c
                      ? "border-zinc-300 bg-zinc-100 text-indigo-600"
                      : "border-zinc-200 text-zinc-500 hover:text-zinc-700"
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
                      ? "border-zinc-400 bg-zinc-100 text-zinc-900"
                      : "border-zinc-200 text-zinc-500 hover:text-zinc-700"
                  }`}
                >
                  {s || "ANY STATUS"}
                </button>
              ))}
            </div>
            <div className="relative mt-2">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search ID, customer, route…"
                aria-label="Search shipments"
                className="w-full rounded-md border border-zinc-300 bg-white py-1.5 pl-7 pr-2 text-xs text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none"
              />
            </div>
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {filtered === null && (
              <div className="p-4 text-xs text-zinc-500">Loading shipments…</div>
            )}
            {filtered?.length === 0 && (
              <div className="p-4 text-xs text-zinc-500">
                No shipments match your filters.
              </div>
            )}
            {filtered?.map((s) => (
              <button
                key={s.shipment_id}
                onClick={() => setSelectedId(s.shipment_id)}
                className={`block w-full border-b border-zinc-200 px-3 py-2.5 text-left transition-colors hover:bg-zinc-100 ${
                  activeId === s.shipment_id ? "bg-zinc-100" : ""
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono font-semibold text-zinc-900">{s.shipment_id}</span>
                  <span className={`rounded border px-1.5 py-0.5 text-[9px] ${STATUS_STYLE[s.status] ?? ""}`}>
                    {s.status}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between text-[11px] text-zinc-500">
                  <span className="truncate pr-2">{s.customer_name}</span>
                  <span className="shrink-0 text-zinc-500">
                    {s.origin_location} → {s.destination_location}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Trace */}
        <div className="rounded-xl border border-zinc-200 bg-white p-4">
          {!trace && <div className="text-xs text-zinc-500">Select a shipment…</div>}
          {trace && (
            <>
              <div className="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <h3 className="font-mono text-sm font-bold text-zinc-900">{trace.shipment.shipment_id}</h3>
                <span className="text-xs text-zinc-500">{trace.shipment.customer_name} · {trace.shipment.region}</span>
                <span className={`rounded border px-1.5 py-0.5 text-[10px] ${STATUS_STYLE[trace.shipment.status] ?? ""}`}>
                  {trace.shipment.status}
                </span>
                <span className="ml-auto text-[11px] text-zinc-500">
                  {trace.shipment.transport_chain_type} · {trace.shipment.cargo_category} ·{" "}
                  {Math.round(trace.shipment.total_chargeable_weight_kg).toLocaleString()} kg ·{" "}
                  ${Math.round(trace.shipment.contracted_revenue_usd).toLocaleString()}
                </span>
                <button
                  onClick={() => setSubOpen((o) => !o)}
                  className="rounded-md border border-zinc-300 px-2 py-1 text-[10px] text-zinc-700 hover:border-zinc-400 hover:text-indigo-600"
                >
                  <Bell className="inline h-3 w-3" /> Subscribe
                </button>
              </div>
              {subOpen && (
                <div className="mb-3 flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2">
                  <input
                    value={subEmail}
                    onChange={(e) => setSubEmail(e.target.value)}
                    placeholder="ops@customer.com"
                    aria-label="Subscriber email"
                    className="flex-1 rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 focus:border-zinc-400 focus:outline-none"
                  />
                  <button
                    onClick={subscribe}
                    className="rounded bg-zinc-900 px-3 py-1 text-xs text-white hover:bg-zinc-700"
                  >
                    Confirm
                  </button>
                </div>
              )}
              {subMsg && <div className="mb-2 text-[11px] text-emerald-700">{subMsg}</div>}

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

      {tracks && tracks.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-zinc-200">
          <div className="border-b border-zinc-200 bg-white px-4 py-2.5 text-sm font-semibold text-zinc-700">
            Route Map — simulated great-circle tracks (swap in AIS/ADS-B feeds for live positions)
            <span className="ml-3 inline-flex gap-3 text-[10px] font-normal">
              <span className="text-indigo-600">● AIR</span>
              <span className="text-indigo-700">● SEA</span>
              <span className="text-emerald-700">● TRUCK</span>
            </span>
          </div>
          <div className="h-[380px]">
            <ShipmentMap tracks={tracks} alertPins={pins ?? []} />
          </div>
        </div>
      )}
    </div>
  );
}

function fmtShort(ts: string): string {
  return ts.slice(5, 16).replace("T", " ");
}

const DEV_STYLE: Record<string, string> = {
  ON_TIME: "border-emerald-200 bg-emerald-50 text-emerald-700",
  LATE: "border-amber-200 bg-amber-50 text-amber-700",
  MISSING: "border-rose-200 bg-rose-50 text-rose-700",
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
        <div className={`flex h-9 w-9 items-center justify-center rounded-lg border ${style.color}`}>
          <style.icon className="h-4 w-4" strokeWidth={2} />
        </div>
        {!last && <div className="w-px flex-1 bg-zinc-300" />}
      </div>
      {/* content */}
      <div className="min-w-0 flex-1 pb-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className={`text-xs font-bold uppercase tracking-wide ${style.label}`}>
            {leg.transport_mode} · LEG {leg.leg_sequence}
          </span>
          <span className="text-sm font-semibold text-zinc-900">
            {leg.origin_facility} → {leg.destination_facility}
          </span>
          <span className="font-mono text-[11px] text-zinc-500">
            {leg.carrier_code} {leg.voyage_flight_no}
          </span>
          <span className={`ml-auto text-xs font-semibold ${delay.cls}`}>{delay.text}</span>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-zinc-500">
          <span>dep {fmtTs(leg.actual_depart_ts || leg.planned_depart_ts)}</span>
          <span>arr {fmtTs(leg.actual_arrive_ts || leg.planned_arrive_ts)}</span>
          <span>{Math.round(leg.distance_km).toLocaleString()} km</span>
          <span>${leg.allocated_cost_usd.toLocaleString()}</span>
          <span className={leg.leg_status === "COMPLETED" ? "text-emerald-600" : "text-amber-500"}>
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
