"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  Bot,
  ClipboardList,
  Network,
  Ship,
  Upload,
  Users,
  type LucideIcon,
} from "lucide-react";

const NAV_GROUPS: { group: string; items: { href: string; label: string; icon: LucideIcon }[] }[] = [
  {
    group: "Operations",
    items: [
      { href: "/", label: "Overview", icon: Ship },
      { href: "/network", label: "Network", icon: Network },
      { href: "/orders", label: "Orders", icon: ClipboardList },
    ],
  },
  {
    group: "Exceptions",
    items: [{ href: "/alerts", label: "Alerts", icon: Bell }],
  },
  {
    group: "Data",
    items: [{ href: "/ingest", label: "Ingest", icon: Upload }],
  },
  {
    group: "Insight",
    items: [{ href: "/agent", label: "AI Agent", icon: Bot }],
  },
  {
    group: "Account",
    items: [{ href: "/portal", label: "Portal", icon: Users }],
  },
];

export default function SidebarNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Primary" className="flex-1 overflow-y-auto px-3 py-4">
      {NAV_GROUPS.map((group) => (
        <div key={group.group} className="mb-5">
          <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
            {group.group}
          </div>
          {group.items.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`mb-0.5 flex items-center gap-2.5 rounded-md border-l-2 px-2 py-1.5 text-[13px] transition-colors ${
                  active
                    ? "border-indigo-600 bg-zinc-100 font-medium text-zinc-900"
                    : "border-transparent text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
                }`}
              >
                <item.icon
                  className={`h-4 w-4 ${active ? "text-indigo-600" : "text-zinc-400"}`}
                  strokeWidth={2}
                />
                {item.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
