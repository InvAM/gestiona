"use client";

// Dashboard gadgets backed by the flow metrics (kinds `control_chart` and `cycle_time`;
// labels come from GET /meta → gadget_kinds / analytics).

import Link from "next/link";
import { Field, Input } from "@/components/ui/primitives";
import { useMeta } from "@/lib/api/hooks";
import { fmtHours, fmtNum } from "./chart-kit";
import { ControlChartPlot, CycleHistogram } from "./charts";

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

function analyticsHref(data) {
  const q = new URLSearchParams();
  if (data.scope?.jql) q.set("jql", data.scope.jql);
  if (data.days) q.set("days", String(data.days));
  return `/analytics?${q}`;
}

export function ControlChartGadget({ data }) {
  const s = data.stats;
  if (!data.points?.length) return <p className="py-4 text-center text-sm text-fg-subtle">Ninguna incidencia resuelta en los últimos {data.days} días.</p>;
  return (
    <div>
      <div className="mb-1 flex flex-wrap gap-x-3 text-xs text-fg-subtle">
        <span><b className="tabular-nums text-fg">{fmtNum(s.count, 0)}</b> resueltas</span>
        <span>p50 <b className="tabular-nums text-fg">{fmtHours(s.p50_hours)}</b></span>
        <span>p85 <b className="tabular-nums text-fg">{fmtHours(s.p85_hours)}</b></span>
        <span>media <b className="tabular-nums text-fg">{fmtHours(s.mean_hours)}</b></span>
      </div>
      <ControlChartPlot data={data} height={200} compact />
      <div className="mt-1 flex justify-between text-xs text-fg-subtle">
        <span>{data.metric_label} · {data.days} días{data.truncated ? ` · ${data.points.length} más recientes` : ""}</span>
        <Link className="text-link hover:underline" href={analyticsHref(data)}>Ver en Analíticas</Link>
      </div>
    </div>
  );
}

export function CycleTimeGadget({ data }) {
  const c = data.cycle;
  return (
    <div>
      <dl className="mb-2 grid grid-cols-4 gap-2 text-center">
        {[["p50", c.p50], ["p85", c.p85], ["p95", c.p95], ["Media", c.avg]].map(([k, v]) => (
          <div key={k} className="rounded-[3px] bg-bg-subtle px-1 py-1.5">
            <dt className="text-[11px] text-fg-subtle">{k}</dt>
            <dd className="text-base font-semibold">{fmtHours(v)}</dd>
          </div>
        ))}
      </dl>
      <CycleHistogram bins={data.histogram} height={150} compact />
      <div className="mt-1 flex justify-between text-xs text-fg-subtle">
        <span>{fmtNum(data.cycle_count, 0)} de {fmtNum(data.resolved, 0)} resueltas con ciclo · {data.days} días</span>
        <Link className="text-link hover:underline" href={analyticsHref(data)}>Ver en Analíticas</Link>
      </div>
    </div>
  );
}

/** Extra config fields (the JQL/filter source is rendered by the dashboard's GadgetConfig). */
export function FlowGadgetConfig({ kind, config, set }) {
  const meta = useMeta();
  const a = meta.data?.analytics;
  return (
    <>
      <Field label="Días hacia atrás" hint={a ? `Máximo ${a.max_range_days}` : undefined}>
        <Input type="number" min={7} max={a?.max_range_days ?? 366} value={Number(config.days ?? 90)} onChange={(e) => set({ days: Number(e.target.value) })} />
      </Field>
      {kind === "control_chart" && (
        <Field label="Métrica">
          <select className={sel} value={String(config.metric ?? "cycle")} onChange={(e) => set({ metric: e.target.value })}>
            {(a?.metrics ?? []).map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </Field>
      )}
    </>
  );
}
