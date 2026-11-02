import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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

const NAV_ITEMS = [
  { href: "/", label: "Control Tower" },
  { href: "/network", label: "Network" },
  { href: "/alerts", label: "Alerts" },
  { href: "/agent", label: "AI Agent" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-[#0a0f1d] text-slate-200">
        <header className="border-b border-slate-800 bg-[#0c1322]/90 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-7xl items-center gap-8 px-6">
            <Link href="/" className="flex items-center gap-2">
              <span className="text-lg">✈️</span>
              <span className="text-sm font-bold tracking-wide text-white">
                HKG CARGO CONTROL TOWER
              </span>
              <span className="rounded border border-cyan-800 bg-cyan-950/50 px-1.5 py-0.5 text-[10px] font-medium text-cyan-400">
                SEA · LAND · AIR
              </span>
            </Link>
            <nav className="flex gap-1 text-sm">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-md px-3 py-1.5 text-slate-400 transition-colors hover:bg-slate-800/60 hover:text-white"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
          {children}
        </main>
        <footer className="border-t border-slate-800 py-3 text-center text-[11px] text-slate-600">
          Synthetic operational data calibrated to public industry benchmarks ·
          HKAA / SCFI macro series · Portfolio project
        </footer>
      </body>
    </html>
  );
}
