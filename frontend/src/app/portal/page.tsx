"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

interface PortalShipment {
  shipment_id: string;
  origin_location: string;
  destination_location: string;
  status: string;
  transport_chain_type: string;
  total_chargeable_weight_kg: number;
  contracted_revenue_usd: number;
  booking_ts: string;
}

export default function PortalPage() {
  const [email, setEmail] = useState("ops@demo.local");
  const [password, setPassword] = useState("demo1234");
  const [viewer, setViewer] = useState<{ email: string; role: string } | null>(null);
  const [shipments, setShipments] = useState<PortalShipment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function login() {
    setError(null);
    const res = await fetch(`${API_BASE}/api/portal/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      setError((await res.json()).detail ?? "login failed");
      return;
    }
    const v = await res.json();
    setViewer({ email: v.email, role: v.role });
    const p = await fetch(`${API_BASE}/api/portal/shipments`).then((r) => r.json());
    setShipments(p.shipments);
  }

  useEffect(() => {
    login();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="rounded-xl border border-slate-800 bg-[#0f1729] p-4">
        <h3 className="text-sm font-semibold text-slate-300">Portal sign-in</h3>
        <p className="mt-1 text-[11px] text-slate-500">
          Demo accounts: <code className="text-cyan-300">ops@demo.local</code> (full network) ·{" "}
          <code className="text-cyan-300">acme@demo.local</code> (customer scope, row-level filtered) — password{" "}
          <code className="text-cyan-300">demo1234</code>
        </p>
        <div className="mt-2 flex gap-2">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="flex-1 rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-xs text-slate-200"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-40 rounded border border-slate-700 bg-[#0a0f1d] px-2 py-1.5 text-xs text-slate-200"
          />
          <button onClick={login} className="rounded bg-cyan-700 px-4 py-1.5 text-xs text-white hover:bg-cyan-600">
            Sign in
          </button>
        </div>
        {error && <div className="mt-2 text-[11px] text-rose-400">{error}</div>}
      </div>

      {viewer && (
        <div className="rounded-xl border border-slate-800 bg-[#0f1729] p-4">
          <div className="mb-2 text-xs text-slate-400">
            Signed in as <span className="text-cyan-300">{viewer.email}</span> · role{" "}
            <span className="font-semibold uppercase">{viewer.role}</span>
            {viewer.role === "customer" && " — row-level scope active, you only see your own shipments"}
          </div>
          <div className="space-y-1.5">
            {(shipments ?? []).map((s) => (
              <div key={s.shipment_id} className="flex items-center gap-3 rounded-lg border border-slate-800/60 px-2.5 py-1.5 text-[11px]">
                <span className="font-mono text-slate-200">{s.shipment_id}</span>
                <span className="text-slate-400">
                  {s.origin_location} → {s.destination_location}
                </span>
                <span className="text-slate-600">{s.transport_chain_type}</span>
                <span className="ml-auto text-slate-400">{s.status}</span>
                <span className="text-slate-500">${Math.round(s.contracted_revenue_usd).toLocaleString()}</span>
              </div>
            ))}
            {shipments?.length === 0 && (
              <div className="text-xs text-slate-500">No shipments in your scope.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
