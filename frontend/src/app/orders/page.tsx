"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Download, FileText, ReceiptText } from "lucide-react";
import { API_BASE, ensureSession } from "@/lib/api";

interface OrderDoc {
  doc_id: string;
  doc_type: string;
  eawb_status: string;
  created_ts: string;
}

interface OrderDetail {
  shipment_id: string;
  lifecycle: { status: string; note: string | null; ts: string }[];
  current: string;
  awb: { awb_no: string; airline_code: string; created_ts: string } | null;
  documents: OrderDoc[];
}

interface OrderRow {
  shipment_id: string;
  lifecycle: string;
  since: string;
  transport_chain_type: string;
  cargo_category: string;
  origin_location: string;
  destination_location: string;
  total_chargeable_weight_kg: number;
  contracted_revenue_usd: number;
  customer_name: string;
  awb_no: string | null;
}

const LC_STYLE: Record<string, string> = {
  DRAFT: "bg-zinc-100 text-zinc-500 border-zinc-300",
  QUOTED: "bg-zinc-100 text-indigo-600 border-zinc-300",
  BOOKED: "bg-indigo-950/60 text-indigo-400 border-indigo-800",
  IN_PROGRESS: "bg-amber-50 text-amber-700 border-amber-200",
  COMPLETED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  CANCELLED: "bg-rose-50 text-rose-700 border-rose-200",
};

const NEXT: Record<string, string[]> = {
  DRAFT: ["QUOTED"],
  QUOTED: ["BOOKED"],
  BOOKED: ["IN_PROGRESS"],
  IN_PROGRESS: ["COMPLETED"],
};

const emptyForm = {
  customer_id: "",
  origin_location: "CNYTN",
  destination_location: "LAX",
  transport_chain_type: "SEA_AIR_TRUCK",
  cargo_category: "General",
  total_chargeable_weight_kg: 500,
  contracted_revenue_usd: 2350,
};

/** Render an API failure as a readable message, not "Error: ...". */
function cleanError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  return raw.startsWith("Error: ") ? raw.slice(7) : raw;
}

export default function OrdersPage() {
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [customers, setCustomers] = useState<{ customer_id: string; customer_name: string }[]>([]);
  const [form, setForm] = useState({ ...emptyForm });
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, OrderDetail | null | undefined>>({});
  const [cancelArmed, setCancelArmed] = useState<string | null>(null);

  async function fetchDetail(sid: string): Promise<void> {
    try {
      const r = await fetch(`${API_BASE}/api/orders/${sid}`, { credentials: "include" });
      if (!r.ok) throw new Error(`detail ${r.status}`);
      const d: OrderDetail = await r.json();
      setDetail((m) => ({ ...m, [sid]: d }));
    } catch {
      setDetail((m) => ({ ...m, [sid]: null }));
    }
  }

  const toggleDetail = useCallback(async (sid: string) => {
    if (expanded === sid) {
      setExpanded(null);
      return;
    }
    setExpanded(sid);
    setCancelArmed(null);
    if (detail[sid] === undefined) await fetchDetail(sid); // cached (including failed null)
  }, [detail, expanded]);

  async function downloadDoc(doc: OrderDoc) {
    setBusy(doc.doc_id);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/documents/file/${doc.doc_id}`, {
        credentials: "include",
      });
      if (!r.ok) throw new Error(`download ${r.status}`);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${doc.doc_type}_${doc.doc_id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setMsg(`Downloaded ${doc.doc_type} ${doc.doc_id}`);
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setBusy(null);
    }
  }

  const load = useCallback(async () => {
    await ensureSession();
    const r = await fetch(`${API_BASE}/api/orders`, { credentials: "include", cache: "no-store" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `orders ${r.status}`);
    const rows = await r.json();
    setOrders(Array.isArray(rows) ? rows : []);
  }, []);

  useEffect(() => {
    let alive = true;
    async function init() {
      // customers list for the form dropdown
      try {
        await ensureSession();
        await fetch(`${API_BASE}/api/shipments?limit=1`, { credentials: "include" });
        const r = await fetch(`${API_BASE}/api/shipments?limit=60`, { credentials: "include" });
        const rows: unknown = r.ok ? await r.json() : [];
        if (alive && Array.isArray(rows)) {
          const seen = new Map<string, string>();
          for (const row of rows as { customer_id: string; customer_name: string }[]) {
            seen.set(row.customer_id, row.customer_name);
          }
          setCustomers([...seen].map(([customer_id, customer_name]) => ({ customer_id, customer_name })));
          if (seen.size) setForm((f) => ({ ...f, customer_id: f.customer_id || [...seen.keys()][0] }));
        }
      } catch {
        /* dropdown is best-effort */
      }
      try {
        await load();
      } catch (e) {
        if (alive) setError(cleanError(e));
      }
    }
    init();
    return () => {
      alive = false;
    };
  }, [load]);

  async function createOrder() {
    setBusy("create");
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/orders`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      const d = await r.json();
      setMsg(`Order created: ${d.shipment_id}`);
      await load();
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setBusy(null);
    }
  }

  async function allocateAwb(sid: string) {
    setBusy(sid);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/orders/${sid}/awb`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ airline_code: "CX" }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      const d = await r.json();
      setMsg(`AWB ${d.awb_no} allocated to ${sid}`);
      await load();
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setBusy(null);
    }
  }

  async function transition(sid: string, to: string) {
    setBusy(sid);
    setError(null);
    setCancelArmed(null);
    try {
      const r = await fetch(`${API_BASE}/api/orders/${sid}/transition`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to, note: "via workbench" }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      await load();
      if (expanded === sid) await fetchDetail(sid);
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setBusy(null);
    }
  }

  async function generateDoc(sid: string, docType: string) {
    setBusy(`${sid}-${docType}`);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/documents/${sid}/generate`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_type: docType }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      const d = await r.json();
      setMsg(`${docType} generated: ${d.doc_id} (e-AWB status: ${d.eawb_status})`);
      await load();
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setBusy(null);
    }
  }

  async function showEta(sid: string) {
    setBusy(`${sid}-eta`);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/orders/${sid}/eta`, { credentials: "include" });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      const d = await r.json();
      const b = d.eta_end_to_end_bands_min;
      setMsg(
        `ETA ${sid}: P50 ${(b.p50 / 1440).toFixed(1)} d · P80 ${(b.p80 / 1440).toFixed(1)} d · P95 ${(b.p95 / 1440).toFixed(1)} d ${d.at_risk ? "(at risk)" : "(on plan)"} — empirical quantiles per mode+lane`
      );
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setBusy(null);
    }
  }

  async function settle(sid: string) {
    setBusy(`${sid}-settle`);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/settlement/${sid}/charges`, { method: "POST", credentials: "include" });
      const inv = await fetch(`${API_BASE}/api/settlement/${sid}/invoice`, { method: "POST", credentials: "include" });
      if (!inv.ok) throw new Error((await inv.json()).detail ?? String(inv.status));
      const d = await inv.json();
      setMsg(`Invoice ${d.invoice_id} created — USD ${d.amount_usd.toLocaleString()} (open)`);
      await load();
    } catch (e) {
      setError(cleanError(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {/* create form */}
      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-semibold text-zinc-700">New Order</h3>
        <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
          <select
            value={form.customer_id}
            onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900"
          >
            {(customers.length ? customers : [{ customer_id: "", customer_name: "loading…" }]).map((c) => (
              <option key={c.customer_id} value={c.customer_id}>
                {c.customer_name}
              </option>
            ))}
          </select>
          <input
            value={form.origin_location}
            onChange={(e) => setForm({ ...form, origin_location: e.target.value })}
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900"
            placeholder="Origin (CNYTN)"
          />
          <input
            value={form.destination_location}
            onChange={(e) => setForm({ ...form, destination_location: e.target.value })}
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900"
            placeholder="Destination (LAX)"
          />
          <select
            value={form.transport_chain_type}
            onChange={(e) => setForm({ ...form, transport_chain_type: e.target.value })}
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900"
          >
            <option>SEA_AIR_TRUCK</option>
            <option>TRUCK_AIR_TRUCK</option>
            <option>DIRECT_AIR</option>
          </select>
          <select
            value={form.cargo_category}
            onChange={(e) => setForm({ ...form, cargo_category: e.target.value })}
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900"
          >
            <option>General</option>
            <option>High_Tech</option>
            <option>E_Commerce</option>
            <option>Pharma_Cold_Chain</option>
            <option>Dangerous_Goods</option>
          </select>
          <input
            type="number"
            value={form.total_chargeable_weight_kg}
            onChange={(e) => setForm({ ...form, total_chargeable_weight_kg: Number(e.target.value) })}
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900"
          />
          <input
            type="number"
            value={form.contracted_revenue_usd}
            onChange={(e) => setForm({ ...form, contracted_revenue_usd: Number(e.target.value) })}
            className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-zinc-900"
          />
          <button
            onClick={createOrder}
            disabled={busy === "create" || !form.customer_id}
            className="rounded bg-zinc-900 px-3 py-1.5 font-medium text-white hover:bg-zinc-700 disabled:opacity-40"
          >
            {busy === "create" ? "Creating…" : "Create DRAFT"}
          </button>
        </div>
      </div>

      {msg && <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-2.5 text-xs text-emerald-700">{msg}</div>}
      {error && <div className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">{error}</div>}

      {/* order list */}
      <div className="space-y-2">
        {orders === null && <div className="text-xs text-zinc-500">Loading orders…</div>}
        {orders?.length === 0 && (
          <div className="text-xs text-zinc-500">No workbench orders yet — create one above.</div>
        )}
        {orders?.map((o) => (
          <div key={o.shipment_id} className="rounded-xl border border-zinc-200 bg-white p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <button
                onClick={() => toggleDetail(o.shipment_id)}
                aria-expanded={expanded === o.shipment_id}
                aria-label={`${expanded === o.shipment_id ? "Hide" : "Show"} detail for ${o.shipment_id}`}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                {expanded === o.shipment_id ? (
                  <ChevronUp className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                )}
                <span className="font-mono font-bold text-zinc-900">{o.shipment_id}</span>
                <span className={`rounded border px-1.5 py-0.5 text-[9px] ${LC_STYLE[o.lifecycle] ?? ""}`}>
                  {o.lifecycle}
                </span>
                {o.awb_no && (
                  <span className="rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 font-mono text-[9px] text-indigo-700">
                    AWB {o.awb_no}
                  </span>
                )}
                <span className="truncate text-zinc-500">{o.customer_name}</span>
                <span className="shrink-0 text-zinc-500">
                  {o.origin_location} → {o.destination_location} · {o.cargo_category} ·{" "}
                  {Math.round(o.total_chargeable_weight_kg).toLocaleString()} kg · $
                  {Math.round(o.contracted_revenue_usd).toLocaleString()}
                </span>
              </button>
              <span className="ml-auto flex gap-1.5">
                {o.lifecycle === "QUOTED" && !o.awb_no && (
                  <button
                    onClick={() => allocateAwb(o.shipment_id)}
                    disabled={busy === o.shipment_id}
                    className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-[10px] text-indigo-700 hover:bg-indigo-100 disabled:opacity-40"
                  >
                    Allocate AWB
                  </button>
                )}
                {(NEXT[o.lifecycle] ?? []).map((to) => (
                  <button
                    key={to}
                    onClick={() => transition(o.shipment_id, to)}
                    disabled={busy === o.shipment_id}
                    className="rounded-md border border-zinc-300 px-2 py-1 text-[10px] text-zinc-700 hover:border-zinc-400 hover:text-indigo-600 disabled:opacity-40"
                  >
                    → {to}
                  </button>
                ))}
                <button
                  onClick={() => generateDoc(o.shipment_id, "PACKING_LIST")}
                  disabled={busy === `${o.shipment_id}-PACKING_LIST`}
                  className="rounded-md border border-zinc-300 px-2 py-1 text-[10px] text-zinc-500 hover:border-zinc-400 hover:text-indigo-600 disabled:opacity-40"
                >
                  <FileText className="inline h-3 w-3" /> Packing list
                </button>
                {o.awb_no && (
                  <button
                    onClick={() => generateDoc(o.shipment_id, "AWB")}
                    disabled={busy === `${o.shipment_id}-AWB`}
                    className="rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1 text-[10px] text-indigo-700 hover:bg-indigo-100 disabled:opacity-40"
                  >
                    <FileText className="inline h-3 w-3" /> AWB doc
                  </button>
                )}
                {o.cargo_category === "Dangerous_Goods" && (
                  <button
                    onClick={() => generateDoc(o.shipment_id, "DG_DECL")}
                    disabled={busy === `${o.shipment_id}-DG_DECL`}
                    className="rounded-md border border-rose-200 px-2 py-1 text-[10px] text-rose-700 hover:bg-rose-50 disabled:opacity-40"
                  >
                    <FileText className="inline h-3 w-3" /> DG decl.
                  </button>
                )}
                {(o.lifecycle === "BOOKED" || o.lifecycle === "IN_PROGRESS") && (
                  <button
                    onClick={() => showEta(o.shipment_id)}
                    disabled={busy === `${o.shipment_id}-eta`}
                    className="rounded-md border border-zinc-400 px-2 py-1 text-[10px] text-zinc-500 hover:text-zinc-900 disabled:opacity-40"
                  >
                    ETA
                  </button>
                )}
                <button
                  onClick={() => settle(o.shipment_id)}
                  disabled={busy === `${o.shipment_id}-settle`}
                  className="rounded-md border border-emerald-200 px-2 py-1 text-[10px] text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                >
                  <ReceiptText className="inline h-3 w-3" /> Settle & invoice
                </button>
                {o.lifecycle !== "COMPLETED" && o.lifecycle !== "CANCELLED" && (
                  cancelArmed === o.shipment_id ? (
                    <span className="flex items-center gap-1">
                      <button
                        onClick={() => transition(o.shipment_id, "CANCELLED")}
                        disabled={busy === o.shipment_id}
                        className="rounded-md bg-red-600 px-2 py-1 text-[10px] font-medium text-white hover:bg-red-700 disabled:opacity-40"
                      >
                        Confirm cancel
                      </button>
                      <button
                        onClick={() => setCancelArmed(null)}
                        className="rounded-md border border-zinc-300 px-2 py-1 text-[10px] text-zinc-500 hover:text-zinc-700"
                      >
                        Keep
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => setCancelArmed(o.shipment_id)}
                      disabled={busy === o.shipment_id}
                      className="rounded-md border border-rose-200 px-2 py-1 text-[10px] text-rose-700 hover:bg-rose-50 disabled:opacity-40"
                    >
                      Cancel
                    </button>
                  )
                )}
              </span>
            </div>
            {expanded === o.shipment_id && (
              <div className="mt-3 border-t border-zinc-100 pt-3">
                {detail[o.shipment_id] === undefined && (
                  <div className="text-xs text-zinc-500">Loading detail…</div>
                )}
                {detail[o.shipment_id] === null && (
                  <div className="text-xs text-rose-700">Order detail unavailable.</div>
                )}
                {detail[o.shipment_id] && (
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                        Lifecycle history
                      </div>
                      <div className="space-y-1">
                        {detail[o.shipment_id]!.lifecycle.map((h, i) => (
                          <div key={i} className="flex items-center gap-2 text-[11px]">
                            <span className={`rounded border px-1.5 py-0.5 text-[9px] ${LC_STYLE[h.status] ?? ""}`}>
                              {h.status}
                            </span>
                            <span className="font-mono text-zinc-500">
                              {h.ts.slice(0, 16).replace("T", " ")}
                            </span>
                            {h.note && <span className="truncate text-zinc-400">{h.note}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                        Documents
                      </div>
                      {detail[o.shipment_id]!.awb && (
                        <div className="mb-1.5 text-[11px] text-zinc-500">
                          AWB{" "}
                          <span className="font-mono text-indigo-600">
                            {detail[o.shipment_id]!.awb!.awb_no}
                          </span>{" "}
                          · carrier {detail[o.shipment_id]!.awb!.airline_code}
                        </div>
                      )}
                      {(detail[o.shipment_id]!.documents ?? []).length === 0 ? (
                        <div className="text-[11px] text-zinc-400">
                          No documents yet — generate one from the actions above.
                        </div>
                      ) : (
                        <div className="space-y-1">
                          {detail[o.shipment_id]!.documents.map((d) => (
                            <div key={d.doc_id} className="flex items-center gap-2 text-[11px]">
                              <span className="rounded border border-zinc-300 bg-zinc-100 px-1.5 py-0.5 text-[9px] text-zinc-700">
                                {d.doc_type}
                              </span>
                              <span
                                className={`rounded border px-1.5 py-0.5 text-[9px] ${
                                  d.eawb_status === "accepted"
                                    ? "border-emerald-200 text-emerald-700"
                                    : d.eawb_status === "sent"
                                      ? "border-sky-200 text-sky-700"
                                      : "border-zinc-300 text-zinc-500"
                                }`}
                              >
                                {d.eawb_status === "none" ? "—" : d.eawb_status}
                              </span>
                              <span className="font-mono text-zinc-500">{d.doc_id}</span>
                              <button
                                onClick={() => downloadDoc(d)}
                                disabled={busy === d.doc_id}
                                className="ml-auto inline-flex items-center gap-1 rounded-md border border-zinc-300 px-2 py-0.5 text-[10px] text-zinc-700 hover:border-zinc-400 hover:text-indigo-600 disabled:opacity-40"
                              >
                                <Download className="h-3 w-3" />
                                {busy === d.doc_id ? "…" : "PDF"}
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
