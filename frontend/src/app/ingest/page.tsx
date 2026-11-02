"use client";

import { useState } from "react";
import { API_BASE } from "@/lib/api";

interface IngestResult {
  parsed: number;
  ingested: number;
  duplicates: number;
  rejected: number;
  rejects: { line_no: number; reason: string; raw_line: string }[];
  auto_resolved_alerts: string[];
}

export default function IngestPage() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<IngestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadSample() {
    const res = await fetch(`${API_BASE}/api/ingest/sample`);
    const data = await res.json();
    setText(data.text ?? "");
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/ingest/fsu`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, source_name: "workbench" }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setResult(await res.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-zinc-900">FSU milestone feed ingest</h2>
        <p className="mt-1 text-[11px] leading-relaxed text-zinc-500">
          Real feeds deliver milestones late, duplicated and out of order. This layer
          parses CIMP-style lines (<code className="text-indigo-600">FSU|code|shipment|station|ts</code>),
          anchors every event to its planned milestone, deduplicates, and auto-resolves
          missing-milestone alerts when a late report arrives. Duplicates and unknown
          codes never enter the ledger silently — check the reject list.
        </p>
        <div className="mt-3 flex gap-2">
          <button
            onClick={loadSample}
            className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs text-zinc-700 hover:border-zinc-400 hover:text-indigo-600"
          >
            Load dirty sample (dups + out-of-order + rejects)
          </button>
          <button
            onClick={submit}
            disabled={busy || !text.trim()}
            className="rounded-lg bg-zinc-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-zinc-700 disabled:opacity-40"
          >
            {busy ? "Ingesting…" : "Ingest"}
          </button>
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={12}
          placeholder="FSU|ARR|SHP-2025-007919|FRA|2026-10-30T09:37:43Z"
          className="mt-3 w-full rounded-lg border border-zinc-300 bg-white p-3 font-mono text-[11px] text-zinc-700 placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none"
        />
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Parsed" value={result.parsed} tone="text-zinc-900" />
            <Stat label="Ingested" value={result.ingested} tone="text-emerald-700" />
            <Stat label="Duplicates" value={result.duplicates} tone="text-amber-700" />
            <Stat label="Rejected" value={result.rejected} tone="text-rose-700" />
          </div>
          {result.auto_resolved_alerts.length > 0 && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">
              Auto-resolved missing-milestone alerts:{" "}
              <span className="font-mono">{result.auto_resolved_alerts.join(", ")}</span>
            </div>
          )}
          {result.rejects.length > 0 && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-3">
              <div className="mb-1.5 text-xs font-semibold text-rose-700">Reject list</div>
              <div className="space-y-1">
                {result.rejects.map((r, i) => (
                  <div key={i} className="flex items-center gap-3 text-[11px] text-rose-800">
                    <span className="w-14 font-mono">L{r.line_no}</span>
                    <span className="w-56">{r.reason}</span>
                    <span className="truncate font-mono text-rose-700/60">{r.raw_line}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`mt-0.5 text-xl font-bold ${tone}`}>{value}</div>
    </div>
  );
}
