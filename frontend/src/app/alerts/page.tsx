"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AlertItem, AlertSummary } from "@/lib/api";

const SEVERITY_STYLE: Record<string, string> = {
  high: "bg-rose-950/60 text-rose-300 border-rose-800",
  medium: "bg-amber-950/60 text-amber-300 border-amber-800",
  info: "bg-slate-800/60 text-slate-300 border-slate-700",
};

const STATUS_STYLE: Record<string, string> = {
  OPEN: "bg-rose-950/60 text-rose-400 border-rose-800",
  ACKNOWLEDGED: "bg-cyan-950/60 text-cyan-400 border-cyan-800",
  RESOLVED: "bg-emerald-950/60 text-emerald-400 border-emerald-800",
  CLOSED: "bg-slate-800/60 text-slate-400 border-slate-700",
};

const NEXT_ACTION: Record<string, { to: string; label: string }[]> = {
  OPEN: [{ to: "ACKNOWLEDGED", label: "Acknowledge" }],
  ACKNOWLEDGED: [
    { to: "RESOLVED", label: "Resolve" },
    { to: "CLOSED", label: "Close" },
  ],
  RESOLVED: [{ to: "CLOSED", label: "Close" }],
  CLOSED: [],
};

const STATUSES = ["", "OPEN", "ACKNOWLEDGED", "RESOLVED", "CLOSED"];

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null);
  const [summary, setSummary] = useState<AlertSummary | null>(null);
  const [status, setStatus] = useState("OPEN");
  const [severity, setSeverity] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setAlerts(null);
    const [list, sum] = await Promise.all([
      api.alerts(status || undefined, severity || undefined),
      api.alertSummary(),
    ]);
    setAlerts(list);
    setSummary(sum);
  }, [status, severity]);

  useEffect(() => {
    load().catch((e) => setError(String(e)));
  }, [load]);

  async function runScan() {
    setBusy("scan");
    try {
      await api.syncAlerts();
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function transition(id: string, to: string) {
    setBusy(id);
    setError(null);
    try {
      const assignee = to === "ACKNOWLEDGED" ? "ops.demo" : undefined;
      const note = to === "RESOLVED" || to === "CLOSED" ? "handled via workbench" : undefined;
      await api.transitionAlert(id, to, note, assignee);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {/* summary strip */}
      <div className="flex flex-wrap items-center gap-3 text-xs">
        {summary &&
          Object.entries(summary.by_status).map(([s, n]) => (
            <span
              key={s}
              className={`rounded-lg border px-2.5 py-1 ${STATUS_STYLE[s] ?? "border-slate-700 text-slate-400"}`}
            >
              {s} · <span className="font-bold">{n}</span>
            </span>
          ))}
        {summary && (
          <span className="text-slate-500">
            open high: {summary.open_by_severity.high ?? 0} · medium:{" "}
            {summary.open_by_severity.medium ?? 0}
          </span>
        )}
        <button
          onClick={runScan}
          disabled={busy === "scan"}
          className="ml-auto rounded-lg border border-cyan-800 bg-cyan-950/50 px-3 py-1.5 font-medium text-cyan-300 transition-colors hover:bg-cyan-900/50 disabled:opacity-40"
        >
          {busy === "scan" ? "Scanning…" : "Run rule scan"}
        </button>
      </div>

      {/* filters */}
      <div className="flex flex-wrap gap-1">
        {STATUSES.map((s) => (
          <button
            key={s || "all"}
            onClick={() => setStatus(s)}
            className={`rounded-md border px-2 py-1 text-[10px] font-medium ${
              status === s
                ? "border-cyan-700 bg-cyan-950/60 text-cyan-300"
                : "border-slate-800 text-slate-500 hover:text-slate-300"
            }`}
          >
            {s || "ALL STATUS"}
          </button>
        ))}
        <span className="mx-2 w-px bg-slate-800" />
        {["", "high", "medium", "info"].map((sv) => (
          <button
            key={sv || "any"}
            onClick={() => setSeverity(sv)}
            className={`rounded-md border px-2 py-1 text-[10px] font-medium ${
              severity === sv
                ? "border-slate-600 bg-slate-800 text-slate-200"
                : "border-slate-800 text-slate-500 hover:text-slate-300"
            }`}
          >
            {sv ? sv.toUpperCase() : "ANY SEVERITY"}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-rose-900 bg-rose-950/40 p-3 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* list */}
      <div className="space-y-2">
        {alerts === null && <div className="text-xs text-slate-500">Loading alerts…</div>}
        {alerts?.length === 0 && (
          <div className="text-xs text-slate-500">No alerts match the filter.</div>
        )}
        {alerts?.map((a) => (
          <div key={a.alert_id} className="rounded-xl border border-slate-800 bg-[#0f1729] p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-mono font-bold text-slate-200">{a.alert_id}</span>
              <span className={`rounded border px-1.5 py-0.5 text-[9px] ${SEVERITY_STYLE[a.severity] ?? ""}`}>
                {a.severity.toUpperCase()}
              </span>
              <span className={`rounded border px-1.5 py-0.5 text-[9px] ${STATUS_STYLE[a.status] ?? ""}`}>
                {a.status}
              </span>
              {a.rule_id && (
                <span className="rounded border border-slate-700 px-1.5 py-0.5 text-[9px] text-slate-400">
                  {a.rule_id}
                </span>
              )}
              <span className="text-[10px] text-slate-600">source: {a.source}</span>
              <span className="ml-auto font-mono text-[11px] text-cyan-300">{a.shipment_id}</span>
              <span className="text-[10px] text-slate-500">
                {a.transport_chain_type} → {a.destination_location}
              </span>
            </div>
            <div className="mt-1.5 text-sm font-medium text-slate-200">{a.title}</div>
            <div className="mt-0.5 text-[11px] text-slate-500">{a.detail}</div>
            <div className="mt-2 flex items-center gap-2">
              {(NEXT_ACTION[a.status] ?? []).map((act) => (
                <button
                  key={act.to}
                  onClick={() => transition(a.alert_id, act.to)}
                  disabled={busy === a.alert_id}
                  className="rounded-md border border-slate-700 px-2.5 py-1 text-[10px] font-medium text-slate-300 transition-colors hover:border-cyan-700 hover:text-cyan-300 disabled:opacity-40"
                >
                  {busy === a.alert_id ? "…" : act.label}
                </button>
              ))}
              {(a.assignee || a.resolution_note) && (
                <span className="text-[10px] text-slate-600">
                  {a.assignee && `assignee: ${a.assignee}`}
                  {a.assignee && a.resolution_note && " · "}
                  {a.resolution_note}
                </span>
              )}
              <span className="ml-auto text-[10px] text-slate-600">
                raised {a.created_ts.slice(0, 16).replace("T", " ")}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
