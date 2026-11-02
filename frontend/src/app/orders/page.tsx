"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

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
  DRAFT: "bg-slate-800/60 text-slate-400 border-slate-700",
  QUOTED: "bg-cyan-950/60 text-cyan-400 border-cyan-800",
  BOOKED: "bg-indigo-950/60 text-indigo-400 border-indigo-800",
  IN_PROGRESS: "bg-amber-950/60 text-amber-400 border-amber-800",
  COMPLETED: "bg-emerald-950/60 text-emerald-400 border-emerald-800",
  CANCELLED: "bg-rose-950/60 text-rose-400 border-rose-800",
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

export default function OrdersPage() {
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [customers, setCustomers] = useState<{ customer_id: string; customer_name: string }[]>([]);
  const [form, setForm] = useState({ ...emptyForm });
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const orders = await fetch(`${API_BASE}/api/orders`).then((r) => r.json());
    setOrders(orders);
  }, []);

  useEffect(() => {
    // customers list for the form dropdown
    fetch(`${API_BASE}/api/shipments?limit=1`)
      .then(() => fetch(`${API_BASE}/api/shipments?limit=60`))
      .then((r) => r.json())
      .then((rows: any[]) => {
        const seen = new Map<string, string>();
        for (const r of rows) seen.set(r.customer_id, r.customer_name);
        setCustomers([...seen].map(([customer_id, customer_name]) => ({ customer_id, customer_name })));
        if (seen.size) setForm((f) => ({ ...f, customer_id: f.customer_id || [...seen.keys()][0] }));
      })
      .catch(() => {});
    load().catch((e) => setError(String(e)));
  }, [load]);

  async function createOrder() {
    setBusy("create");
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      const d = await r.json();
      setMsg(`Order created: ${d.shipment_id}`);
      await load();
    } catch (e) {
      setError(String(e));
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ airline_code: "CX" }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      const d = await r.json();
      setMsg(`AWB ${d.awb_no} allocated to ${sid}`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function transition(sid: string, to: string) {
    setBusy(sid);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/api/orders/${sid}/transition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ to, note: "via workbench" }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      await load();
    } catch (e) {
      setError(String(e));
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_type: docType }),
      });
      if (!r.ok) throw new Error((await r.json()).detail ?? String(r.status));
      const d = await r.json();
      setMsg(`${docType} generated: ${d.doc_id} (e-AWB status: ${d.eawb_status})`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function settle(sid: string) {
    setBusy(`${sid}-settle`);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/settlement/${sid}/charges`, { method: "POST" });
      const inv = await fetch(`${API_BASE}/api/settlement/${sid}/invoice`, { method: "POST" });
      if (!inv.ok) throw new Error((await inv.json()).detail ?? String(inv.status));
      const d = await inv.json();
      setMsg(`Invoice ${d.invoice_id} created — USD ${d.amount_usd.toLocaleString()} (open)`);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {/* create form */}
      <div className="rounded-xl border border-slate-800 bg-[#0f1729] p-4">
        <h3 className="mb-3 text-sm font-semibold text-slate-300">New Order</h3>
        <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
          <select
            value={form.customer_id}
            onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
            className="rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-slate-200"
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
            className="rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-slate-200"
            placeholder="Origin (CNYTN)"
          />
          <input
            value={form.destination_location}
            onChange={(e) => setForm({ ...form, destination_location: e.target.value })}
            className="rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-slate-200"
            placeholder="Destination (LAX)"
          />
          <select
            value={form.transport_chain_type}
            onChange={(e) => setForm({ ...form, transport_chain_type: e.target.value })}
            className="rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-slate-200"
          >
            <option>SEA_AIR_TRUCK</option>
            <option>TRUCK_AIR_TRUCK</option>
            <option>DIRECT_AIR</option>
          </select>
          <select
            value={form.cargo_category}
            onChange={(e) => setForm({ ...form, cargo_category: e.target.value })}
            className="rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-slate-200"
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
            className="rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-slate-200"
          />
          <input
            type="number"
            value={form.contracted_revenue_usd}
            onChange={(e) => setForm({ ...form, contracted_revenue_usd: Number(e.target.value) })}
            className="rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-slate-200"
          />
          <button
            onClick={createOrder}
            disabled={busy === "create" || !form.customer_id}
            className="rounded bg-cyan-700 px-3 py-1.5 font-medium text-white hover:bg-cyan-600 disabled:opacity-40"
          >
            {busy === "create" ? "Creating…" : "Create DRAFT"}
          </button>
        </div>
      </div>

      {msg && <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 p-2.5 text-xs text-emerald-300">{msg}</div>}
      {error && <div className="rounded-lg border border-rose-900 bg-rose-950/40 p-2.5 text-xs text-rose-300">{error}</div>}

      {/* order list */}
      <div className="space-y-2">
        {orders === null && <div className="text-xs text-slate-500">Loading orders…</div>}
        {orders?.length === 0 && (
          <div className="text-xs text-slate-500">No workbench orders yet — create one above.</div>
        )}
        {orders?.map((o) => (
          <div key={o.shipment_id} className="rounded-xl border border-slate-800 bg-[#0f1729] p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-mono font-bold text-slate-200">{o.shipment_id}</span>
              <span className={`rounded border px-1.5 py-0.5 text-[9px] ${LC_STYLE[o.lifecycle] ?? ""}`}>
                {o.lifecycle}
              </span>
              {o.awb_no && (
                <span className="rounded border border-indigo-800 bg-indigo-950/40 px-1.5 py-0.5 font-mono text-[9px] text-indigo-300">
                  AWB {o.awb_no}
                </span>
              )}
              <span className="text-slate-500">{o.customer_name}</span>
              <span className="text-slate-400">
                {o.origin_location} → {o.destination_location} · {o.cargo_category} ·{" "}
                {Math.round(o.total_chargeable_weight_kg).toLocaleString()} kg · $
                {Math.round(o.contracted_revenue_usd).toLocaleString()}
              </span>
              <span className="ml-auto flex gap-1.5">
                {o.lifecycle === "QUOTED" && !o.awb_no && (
                  <button
                    onClick={() => allocateAwb(o.shipment_id)}
                    disabled={busy === o.shipment_id}
                    className="rounded-md border border-indigo-700 px-2 py-1 text-[10px] text-indigo-300 hover:bg-indigo-950/40 disabled:opacity-40"
                  >
                    Allocate AWB
                  </button>
                )}
                {(NEXT[o.lifecycle] ?? []).map((to) => (
                  <button
                    key={to}
                    onClick={() => transition(o.shipment_id, to)}
                    disabled={busy === o.shipment_id}
                    className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:border-cyan-700 hover:text-cyan-300 disabled:opacity-40"
                  >
                    → {to}
                  </button>
                ))}
                <button
                  onClick={() => generateDoc(o.shipment_id, "PACKING_LIST")}
                  disabled={busy === `${o.shipment_id}-PACKING_LIST`}
                  className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-400 hover:border-cyan-700 hover:text-cyan-300 disabled:opacity-40"
                >
                  📄 Packing list
                </button>
                {o.awb_no && (
                  <button
                    onClick={() => generateDoc(o.shipment_id, "AWB")}
                    disabled={busy === `${o.shipment_id}-AWB`}
                    className="rounded-md border border-indigo-700 px-2 py-1 text-[10px] text-indigo-300 hover:bg-indigo-950/40 disabled:opacity-40"
                  >
                    📄 AWB doc
                  </button>
                )}
                {o.cargo_category === "Dangerous_Goods" && (
                  <button
                    onClick={() => generateDoc(o.shipment_id, "DG_DECL")}
                    disabled={busy === `${o.shipment_id}-DG_DECL`}
                    className="rounded-md border border-rose-800 px-2 py-1 text-[10px] text-rose-300 hover:bg-rose-950/40 disabled:opacity-40"
                  >
                    📄 DG decl.
                  </button>
                )}
                <button
                  onClick={() => settle(o.shipment_id)}
                  disabled={busy === `${o.shipment_id}-settle`}
                  className="rounded-md border border-emerald-800 px-2 py-1 text-[10px] text-emerald-300 hover:bg-emerald-950/40 disabled:opacity-40"
                >
                  💰 Settle & invoice
                </button>
                {o.lifecycle !== "COMPLETED" && o.lifecycle !== "CANCELLED" && (
                  <button
                    onClick={() => transition(o.shipment_id, "CANCELLED")}
                    disabled={busy === o.shipment_id}
                    className="rounded-md border border-rose-900 px-2 py-1 text-[10px] text-rose-400 hover:bg-rose-950/40 disabled:opacity-40"
                  >
                    Cancel
                  </button>
                )}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
