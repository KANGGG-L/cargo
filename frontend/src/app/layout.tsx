import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "HKG Cargo Control Tower",
  description:
    "Multimodal (Sea-Air-Land) AI cargo control tower centered on the Hong Kong hub",
};

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

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-white text-zinc-950">
        <div className="flex min-h-screen">
          {/* Sidebar */}
          <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-zinc-200 bg-white">
            <div className="flex items-center gap-2.5 border-b border-zinc-200 px-5 py-4">
              <Ship className="h-5 w-5 text-indigo-600" strokeWidth={2} />
              <div className="leading-tight">
                <div className="text-[13px] font-semibold text-zinc-900">
                  HKG Cargo Control Tower
                </div>
                <div className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                  Sea · Land · Air
                </div>
              </div>
            </div>
            <nav className="flex-1 overflow-y-auto px-3 py-4">
              {NAV_GROUPS.map((group) => (
                <div key={group.group} className="mb-5">
                  <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                    {group.group}
                  </div>
                  {group.items.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="mb-0.5 flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
                    >
                      <item.icon className="h-4 w-4 text-zinc-400" strokeWidth={2} />
                      {item.label}
                    </Link>
                  ))}
                </div>
              ))}
            </nav>
            <div className="border-t border-zinc-200 px-5 py-3 text-[10px] leading-relaxed text-zinc-400">
              Synthetic operational data calibrated to public industry benchmarks.
              Portfolio project.
            </div>
          </aside>

          {/* Main */}
          <div className="flex min-w-0 flex-1 flex-col">
            <main className="mx-auto w-full max-w-[1440px] flex-1 px-6 py-6">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
