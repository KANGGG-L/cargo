"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AlertItem, AlertSummary, OutboxRow } from "@/lib/api";

const SEVERITY_STYLE: Record<string, string> = {
  high: "bg-rose-50 text-rose-700 border-rose-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  info: "bg-zinc-100 text-zinc-700 border-zinc-300",
};

const STATUS_STYLE: Record<string, string> = {
  OPEN: "bg-rose-50 text-rose-700 border-rose-200",
  ACKNOWLEDGED: "bg-zinc-100 text-indigo-600 border-zinc-300",
  RESOLVED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  CLOSED: "bg-zinc-100 text-zinc-500 border-zinc-300",
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
    const [list, sum, box] = await Promise.all([
      api.alerts(status || undefined, severity || undefined),
      api.alertSummary(),
      api.outbox(),
    ]);
    setAlerts(list);
    setSummary(sum);
    setOutbox(box);
  }, [status, severity]);

  const [outbox, setOutbox] = useState<OutboxRow[] | null>(null);

  useEffect(() => {
    load().catch((e) => setError(String(e)));
    const t = setInterval(() => load().catch(() => {}), 8000);
    return () => clearInterval(t);
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

  async function dispatchAll() {
    setBusy("dispatch");
    try {
      await api.dispatchNotifications();
      await load();
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
              className={`rounded-lg border px-2.5 py-1 ${STATUS_STYLE[s] ?? "border-zinc-300 text-zinc-500"}`}
            >
              {s} · <span className="font-bold">{n}</span>
            </span>
          ))}
        {summary && (
          <span className="text-zinc-500">
            open high: {summary.open_by_severity.high ?? 0} · medium:{" "}
            {summary.open_by_severity.medium ?? 0}
          </span>
        )}
        <button
          onClick={runScan}
          disabled={busy === "scan"}
          className="ml-auto rounded-lg border border-zinc-300 bg-zinc-100 px-3 py-1.5 font-medium text-indigo-600 transition-colors hover:bg-cyan-900/50 disabled:opacity-40"
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
                ? "border-zinc-300 bg-zinc-100 text-indigo-600"
                : "border-zinc-200 text-zinc-500 hover:text-zinc-700"
            }`}
          >
            {s || "ALL STATUS"}
          </button>
        ))}
        <span className="mx-2 w-px bg-zinc-100" />
        {["", "high", "medium", "info"].map((sv) => (
          <button
            key={sv || "any"}
            onClick={() => setSeverity(sv)}
            className={`rounded-md border px-2 py-1 text-[10px] font-medium ${
              severity === sv
                ? "border-zinc-400 bg-zinc-100 text-zinc-900"
                : "border-zinc-200 text-zinc-500 hover:text-zinc-700"
            }`}
          >
            {sv ? sv.toUpperCase() : "ANY SEVERITY"}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
          {error}
        </div>
      )}

      {/* list */}
      <div className="space-y-2">
        {alerts === null && <div className="text-xs text-zinc-500">Loading alerts…</div>}
        {alerts?.length === 0 && (
          <div className="text-xs text-zinc-500">No alerts match the filter.</div>
        )}
        {alerts?.map((a) => (
          <div key={a.alert_id} className="rounded-xl border border-zinc-200 bg-white p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-mono font-bold text-zinc-900">{a.alert_id}</span>
              <span className={`rounded border px-1.5 py-0.5 text-[9px] ${SEVERITY_STYLE[a.severity] ?? ""}`}>
                {a.severity.toUpperCase()}
              </span>
              <span className={`rounded border px-1.5 py-0.5 text-[9px] ${STATUS_STYLE[a.status] ?? ""}`}>
                {a.status}
              </span>
              {a.rule_id && (
                <span className="rounded border border-zinc-300 px-1.5 py-0.5 text-[9px] text-zinc-500">
                  {a.rule_id}
                </span>
              )}
              <span className="text-[10px] text-zinc-400">source: {a.source}</span>
              <span className="ml-auto font-mono text-[11px] text-indigo-600">{a.shipment_id}</span>
              <span className="text-[10px] text-zinc-500">
                {a.transport_chain_type} → {a.destination_location}
              </span>
            </div>
            <div className="mt-1.5 text-sm font-medium text-zinc-900">{a.title}</div>
            <div className="mt-0.5 text-[11px] text-zinc-500">{a.detail}</div>
            <div className="mt-2 flex items-center gap-2">
              {(NEXT_ACTION[a.status] ?? []).map((act) => (
                <button
                  key={act.to}
                  onClick={() => transition(a.alert_id, act.to)}
                  disabled={busy === a.alert_id}
                  className="rounded-md border border-zinc-300 px-2.5 py-1 text-[10px] font-medium text-zinc-700 transition-colors hover:border-zinc-400 hover:text-indigo-600 disabled:opacity-40"
                >
                  {busy === a.alert_id ? "…" : act.label}
                </button>
              ))}
              {(a.assignee || a.resolution_note) && (
                <span className="text-[10px] text-zinc-400">
                  {a.assignee && `assignee: ${a.assignee}`}
                  {a.assignee && a.resolution_note && " · "}
                  {a.resolution_note}
                </span>
              )}
              <span className="ml-auto text-[10px] text-zinc-400">
                raised {a.created_ts.slice(0, 16).replace("T", " ")}
              </span>
            </div>
          </div>
        ))}
      </div>
      {/* notification outbox */}
      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-zinc-700">
            Notification Outbox <span className="ml-2 text-[10px] font-normal text-zinc-500">transactional · SMTP worker simulated</span>
          </h3>
          <button
            onClick={dispatchAll}
            disabled={busy === "dispatch"}
            className="rounded-lg border border-zinc-300 px-3 py-1 text-[10px] font-medium text-zinc-700 hover:border-zinc-400 hover:text-indigo-600 disabled:opacity-40"
          >
            {busy === "dispatch" ? "Dispatching…" : "Dispatch pending"}
          </button>
        </div>
        {outbox?.length === 0 && <div className="text-xs text-zinc-500">Outbox empty — subscribe on the Network page.</div>}
        <div className="space-y-1.5">
          {(outbox ?? []).slice(0, 12).map((o) => (
            <div key={o.id} className="flex items-center gap-3 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-[11px]">
              <span className={`rounded border px-1.5 py-0.5 text-[9px] ${o.sent_ts ? "border-emerald-200 text-emerald-700" : "border-amber-200 text-amber-700"}`}>
                {o.sent_ts ? "SENT" : "PENDING"}
              </span>
              <span className="text-zinc-700">{o.subscriber_email}</span>
              <span className="min-w-0 flex-1 truncate text-zinc-500">{o.subject}</span>
              <span className="font-mono text-indigo-600">{o.shipment_id}</span>
              <span className="text-zinc-400">{o.created_ts.slice(5, 16).replace("T", " ")}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

