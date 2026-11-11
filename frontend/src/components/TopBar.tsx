"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { API_BASE, ensureSession } from "@/lib/api";

const TITLES: Record<string, string> = {
  "/": "Overview",
  "/network": "Network",
  "/orders": "Orders",
  "/alerts": "Alerts",
  "/ingest": "Ingest",
  "/agent": "AI Agent",
  "/portal": "Portal",
};

export default function TopBar() {
  const pathname = usePathname();
  const [openCount, setOpenCount] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      await ensureSession();
      const res = await fetch(`${API_BASE}/api/alerts/summary`, {
        credentials: "include",
        cache: "no-store",
      });
      if (!res.ok) {
        setOpenCount(null);
        return;
      }
      const s = await res.json();
      setOpenCount(s.by_status?.OPEN ?? 0);
    } catch {
      setOpenCount(null);
    }
  }, []);

  useEffect(() => {
    // first pull asynchronously so the effect body stays setState-free
    const first = setTimeout(load, 0);
    const t = setInterval(load, 60000);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [load]);

  return (
    <header className="sticky top-0 z-10 flex h-[52px] items-center border-b border-zinc-200 bg-white px-6">
      <h1 className="text-sm font-semibold text-zinc-900">{TITLES[pathname] ?? "Overview"}</h1>
      <Link
        href="/alerts"
        title="Open exception alerts"
        className={`ml-auto inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors ${
          openCount === null
            ? "border-zinc-200 text-zinc-400"
            : openCount > 0
              ? "border-rose-200 bg-rose-50 text-rose-700 hover:border-rose-300"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
        }`}
      >
        <Bell className="h-3.5 w-3.5" strokeWidth={2} />
        {openCount === null ? "—" : `OPEN ${openCount.toLocaleString()}`}
      </Link>
    </header>
  );
}
