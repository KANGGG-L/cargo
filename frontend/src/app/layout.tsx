import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Ship } from "lucide-react";
import SidebarNav from "@/components/SidebarNav";
import TopBar from "@/components/TopBar";
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
            <SidebarNav />
            <div className="border-t border-zinc-200 px-5 py-3 text-[10px] leading-relaxed text-zinc-400">
              Synthetic operational data calibrated to public industry benchmarks.
              Portfolio project.
            </div>
          </aside>

          {/* Main */}
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar />
            <main className="mx-auto w-full max-w-[1440px] flex-1 px-6 py-6">
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
