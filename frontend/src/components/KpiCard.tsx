/** Tremor-style KPI card: label / value / hint. Colour lives only in the tone
 * accent — the value itself stays neutral. */
export default function KpiCard({
  label,
  value,
  unit,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  unit?: string;
  hint?: string;
  tone?: "default" | "good" | "warn";
}) {
  const delta =
    tone === "good" ? (
      <span className="rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
        healthy
      </span>
    ) : tone === "warn" ? (
      <span className="rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
        watch
      </span>
    ) : null;
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
          {label}
        </div>
        {delta}
      </div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums text-zinc-900">
        {value}
        {unit && <span className="ml-1 text-sm font-medium text-zinc-500">{unit}</span>}
      </div>
      {hint && <div className="mt-1 text-[11px] text-zinc-500">{hint}</div>}
    </div>
  );
}
