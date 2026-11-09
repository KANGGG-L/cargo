"use client";

import { useEffect, useState } from "react";
import { api, type CapacityPayload, type NetworkServiceRow } from "@/lib/api";

const MODES = ["AIR", "SEA", "TRUCK"] as const;

export default function CapacityPage() {
  const [mode, setMode] = useState<string>("AIR");
  const [cap, setCap] = useState<CapacityPayload | null>(null);
  const [services, setServices] = useState<NetworkServiceRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    Promise.all([api.networkCapacity(mode), api.networkServices(mode, undefined, 100)])
      .then(([c, s]) => {
        if (!alive) return;
        setCap(c);
        setServices(s);
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [mode]);

  const peak = cap?.utilization.reduce(
    (m, d) => (d.allocated_kg / Math.max(d.capacity_kg, 1) > m.load ? { day: d.day, load: d.allocated_kg / Math.max(d.capacity_kg, 1) } : m),
    { day: "-", load: 0 }
  );
  const cancelledDays = cap?.utilization.filter((d) => d.cancelled_services > 0).length ?? 0;
  const topLoaded = [...services].sort((a, b) => b.load_factor - a.load_factor).slice(0, 12);

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900">Network capacity posture</h2>
          <p className="mt-1 text-[11px] text-zinc-500">
            Shared-service water-line: how full each day&apos;s capacity ran, cancelled services,
            and roll-over reasons. Unlike the single-shipment view, this is where contention shows.
          </p>
        </div>
        <div className="flex gap-1">
          {MODES.map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-lg border px-3 py-1.5 text-xs ${
                mode === m
                  ? "border-zinc-900 bg-zinc-900 text-white"
                  : "border-zinc-300 text-zinc-700 hover:border-zinc-400"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">{error}</div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Service-days" value={cap?.utilization.length ?? 0} tone="text-zinc-900" />
        <Stat label="Days with cancellations" value={cancelledDays} tone="text-rose-700" />
        <Stat label="Peak load day" value={peak ? `${(peak.load * 100).toFixed(0)}%` : "-"} tone="text-indigo-700" sub={peak?.day} />
        <Stat
          label="Rolled (all reasons)"
          value={cap?.rolled_by_reason.reduce((s, r) => s + r.n, 0) ?? 0}
          tone="text-amber-700"
        />
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="mb-2 text-xs font-semibold text-zinc-900">Roll-over by reason</div>
        <div className="flex flex-wrap gap-2">
          {(cap?.rolled_by_reason ?? []).map((r) => (
            <span key={r.roll_reason} className="rounded-lg bg-zinc-100 px-2.5 py-1 text-[11px] text-zinc-700">
              {r.roll_reason}: <span className="font-semibold">{r.n}</span>
            </span>
          ))}
          {cap && cap.rolled_by_reason.length === 0 && (
            <span className="text-[11px] text-zinc-400">No roll-overs for this mode.</span>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="mb-2 text-xs font-semibold text-zinc-900">Most-loaded services</div>
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-zinc-500">
              <th className="pb-1">Service</th>
              <th className="pb-1">Lane</th>
              <th className="pb-1">Departs</th>
              <th className="pb-1 text-right">Load</th>
              <th className="pb-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {topLoaded.map((s) => (
              <tr key={s.service_id} className="border-t border-zinc-100">
                <td className="py-1 font-mono text-zinc-700">{s.service_no}</td>
                <td className="py-1 text-zinc-600">
                  {s.origin_facility}-{s.destination_facility}
                </td>
                <td className="py-1 text-zinc-500">{s.scheduled_depart_ts.slice(0, 10)}</td>
                <td className="py-1 text-right font-semibold text-zinc-900">
                  {(s.load_factor * 100).toFixed(0)}%
                </td>
                <td className="py-1">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] ${
                      s.status === "CANCELLED"
                        ? "bg-rose-100 text-rose-700"
                        : "bg-emerald-100 text-emerald-700"
                    }`}
                  >
                    {s.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, tone, sub }: { label: string; value: string | number; tone: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`mt-0.5 text-xl font-bold ${tone}`}>{value}</div>
      {sub && <div className="text-[10px] text-zinc-400">{sub}</div>}
    </div>
  );
}
