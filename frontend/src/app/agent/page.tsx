"use client";

import { useEffect, useRef, useState } from "react";
import { Radar, TriangleAlert } from "lucide-react";
import { API_BASE } from "@/lib/api";
import ToolActivityCard, { type ToolEvent } from "@/components/ToolActivityCard";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolEvents?: ToolEvent[];
}

const SUGGESTED_PROMPTS = [
  "What happened to air OTP during the September 2025 typhoon?",
  "How bad was the Yantian feeder congestion in March 2026?",
  "Show the HKG-ORD monthly gross margin in 2026",
  "What is the average hub dwell time at HKG?",
  "Which air lanes carry the most tonnage?",
];

export default function AgentPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [llmMode, setLlmMode] = useState<string>("…");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/chat/mode`)
      .then((r) => r.json())
      .then((d) => setLlmMode(d.llm_mode))
      .catch(() => setLlmMode("offline"));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || streaming) return;

    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", toolEvents: [] },
    ]);
    setInput("");
    setStreaming(true);

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, history }),
      });
      if (!res.body) throw new Error("no response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          const event = JSON.parse(part.slice(6));
          applyEvent(event);
        }
      }
    } catch (e) {
      appendToLastAssistant(`\n\nConnection error: ${e}`);
    } finally {
      setStreaming(false);
    }
  }

  function applyEvent(event: Record<string, unknown>) {
    const type = event.type as string;
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (!last || last.role !== "assistant") return prev;

      if (type === "token") {
        last.content += event.content as string;
      } else if (type === "tool_start") {
        last.toolEvents = [
          ...(last.toolEvents ?? []),
          {
            name: event.name as string,
            summary: "",
            payload: {},
            running: true,
          },
        ];
      } else if (type === "tool_end") {
        const events = [...(last.toolEvents ?? [])];
        const idx = events.findIndex((t) => t.running);
        if (idx >= 0) {
          events[idx] = {
            name: event.name as string,
            summary: event.summary as string,
            payload: event.payload as ToolEvent["payload"],
            running: false,
          };
        }
        last.toolEvents = events;
      } else if (type === "error") {
        last.content += `\n\n${event.content as string}`;
      }
      next[next.length - 1] = { ...last };
      return next;
    });
  }

  function appendToLastAssistant(text: string) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant") {
        last.content += text;
        next[next.length - 1] = { ...last };
      }
      return next;
    });
  }

  return (
    <div className="flex h-[calc(100vh-7.5rem)] gap-4">
      {/* Sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 lg:flex">
        <div className="flex items-center justify-between text-xs">
          <span className="font-semibold uppercase tracking-wider text-zinc-500">
            Agent Mode
          </span>
          <span
            className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${
              llmMode === "live"
                ? "border-emerald-700 bg-emerald-950/50 text-emerald-700"
                : "border-amber-700 bg-amber-950/50 text-amber-700"
            }`}
          >
            {llmMode.toUpperCase()}
          </span>
        </div>
        <p className="text-[11px] leading-relaxed text-zinc-500">
          One agent, ten tools: Text-to-SQL querying, anomaly diagnosis,
          disruption simulation (fifo/des A/B), freight quotes, alert creation,
          ETA prediction, plus network load, capacity impact, reroute options and
          manifest lookup. {llmMode === "mock" && "Mock mode replays verified traces against the real database — no API key needed."}
        </p>
        <div className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Try asking
        </div>
        <div className="flex flex-col gap-1.5 overflow-y-auto">
          {SUGGESTED_PROMPTS.map((p) => (
            <button
              key={p}
              onClick={() => send(p)}
              disabled={streaming}
              className="rounded-lg border border-zinc-200 px-2.5 py-2 text-left text-[11px] leading-snug text-zinc-500 transition-colors hover:border-zinc-300 hover:text-indigo-600 disabled:opacity-40"
            >
              {p}
            </button>
          ))}
        </div>
      </aside>

      {/* Chat column */}
      <section className="flex min-w-0 flex-1 flex-col rounded-xl border border-zinc-200 bg-white">
        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
          {messages.length === 0 && (
            <div className="mt-24 text-center text-sm text-zinc-400">
              <Radar className="mx-auto h-10 w-10 text-zinc-300" />
              <p className="mt-3">
                Ask anything about the cargo network — KPIs, bottlenecks,
                disruptions, quotes.
              </p>
            </div>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-zinc-100 px-4 py-2.5 text-sm text-zinc-900">
                  {m.content}
                </div>
              </div>
            ) : (
              <div key={i} className="flex flex-col items-start gap-1">
                {(m.toolEvents ?? []).map((ev, j) => (
                  <ToolActivityCard key={j} ev={ev} />
                ))}
                {m.content && (
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-zinc-100 px-4 py-2.5 text-sm leading-relaxed text-zinc-900">
                    {m.content}
                  </div>
                )}
              </div>
            )
          )}
          {streaming && messages.at(-1)?.content === "" && (
            <div className="text-xs text-zinc-400">analyst is thinking…</div>
          )}
        </div>

        <div className="border-t border-zinc-200 p-3">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send(input)}
              placeholder="e.g. Why did sea OTP drop in March 2026?"
              aria-label="Ask the operations analyst"
              disabled={streaming}
              className="flex-1 rounded-lg border border-zinc-300 bg-white px-4 py-2.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none disabled:opacity-50"
            />
            <button
              onClick={() => send(input)}
              disabled={streaming || !input.trim()}
              className="rounded-lg bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
