"use client";

// Flow-analytics charts. Each takes the API payload as-is (GET /analytics/*), renders one
// y-axis, a legend for >= 2 series, a hover tooltip and a table/CSV view via ChartCard.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer,
  Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import { IssueTypeIcon } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/primitives";
import { fmtDate } from "@/lib/utils";
import {
  AXIS, BAR_CURSOR, CURSOR, ChartCard, GRID, LegendRow, OTHER_KEY, SERIES, StatTile, TooltipCard,
  durationUnit, fmtHours, fmtNum, fmtPeriod, groupPalette,
} from "./chart-kit";

const LINE = { strokeWidth: 2, dot: false, isAnimationActive: false, activeDot: { r: 4, stroke: "var(--bg)", strokeWidth: 2 } };
const BAR = { maxBarSize: 24, isAnimationActive: false };

/* ------------------------------------------------------------------ KPIs */

export function KpiRow({ kpis, days }) {
  if (!kpis) return null;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <StatTile label="Resueltas" value={fmtNum(kpis.resolved, 0)} hint={`${fmtNum(kpis.throughput_per_week)} por semana${days ? ` · ${days} días` : ""}`} />
      <StatTile label="Tiempo de ciclo (p50)" value={fmtHours(kpis.cycle.p50)} hint={`${fmtNum(kpis.cycle_count, 0)} con ciclo medido`} />
      <StatTile label="Tiempo de ciclo (p85)" value={fmtHours(kpis.cycle.p85)} hint={`p95 ${fmtHours(kpis.cycle.p95)}`} />
      <StatTile label="Tiempo de entrega (p50)" value={fmtHours(kpis.lead.p50)} hint={`p85 ${fmtHours(kpis.lead.p85)}`} />
      <StatTile label="En curso (WIP)" value={fmtNum(kpis.wip, 0)} hint={kpis.wip ? `antigüedad p50 ${fmtHours(kpis.wip_age.p50)}` : "Nada en curso ahora"} />
      <StatTile label="Creadas" value={fmtNum(kpis.created, 0)} hint={kpis.reopened ? `${fmtNum(kpis.reopened, 0)} resueltas tras reabrirse` : "Sin reaperturas"} />
    </div>
  );
}

/* ------------------------------------------------------------------ created vs resolved */

export function CreatedResolvedChart({ rows, interval, busy, height = 240 }) {
  const total = rows.reduce((s, r) => s + r.created + r.resolved, 0);
  const columns = [
    { key: "period", label: "Periodo", format: (v) => fmtPeriod(v, interval) },
    { key: "created", label: "Creadas", numeric: true },
    { key: "resolved", label: "Resueltas", numeric: true },
  ];
  const legend = [
    { label: "Creadas", color: SERIES[0], kind: "line" },
    { label: "Resueltas", color: SERIES[1], kind: "line" },
  ];
  return (
    <ChartCard title="Creadas frente a resueltas" subtitle={`Por ${interval === "day" ? "día" : interval === "month" ? "mes" : "semana"}`}
               columns={columns} rows={rows} csvName="creadas-vs-resueltas" busy={busy}
               empty={!total && "No se crearon ni resolvieron incidencias en el rango."} legend={<LegendRow items={legend} />}>
      <div style={{ height }}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="period" {...AXIS} minTickGap={24} tickFormatter={(v) => fmtPeriod(v, interval, true)} />
            <YAxis {...AXIS} allowDecimals={false} />
            <Tooltip cursor={CURSOR} content={({ active, payload, label }) => active && payload?.length ? (
              <TooltipCard title={fmtPeriod(label, interval)} rows={[
                { label: "creadas", value: fmtNum(payload[0].payload.created, 0), color: SERIES[0] },
                { label: "resueltas", value: fmtNum(payload[0].payload.resolved, 0), color: SERIES[1] },
              ]} />
            ) : null} />
            <Line name="Creadas" dataKey="created" stroke={SERIES[0]} {...LINE} />
            <Line name="Resueltas" dataKey="resolved" stroke={SERIES[1]} {...LINE} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ throughput */

export function ThroughputChart({ rows, groups, groupLabel, interval, busy, height = 240 }) {
  const grouped = !!groupLabel && groups?.length > 0;
  const palette = useMemo(() => {
    const weight = new Map();
    rows.forEach((r) => Object.entries(r.counts).forEach(([k, n]) => weight.set(k, (weight.get(k) ?? 0) + n)));
    return groupPalette(groups ?? [], weight);
  }, [rows, groups]);
  const series = grouped ? palette.items : [{ key: "total", label: "Resueltas", color: SERIES[0] }];
  const data = useMemo(() => rows.map((r) => {
    const out = { period: r.period, total: r.total };
    if (grouped) {
      palette.items.forEach((it) => { out[`g:${it.key}`] = 0; });
      Object.entries(r.counts).forEach(([k, n]) => { out[`g:${palette.slot(k)}`] = (out[`g:${palette.slot(k)}`] ?? 0) + n; });
    } else out["g:total"] = r.total;
    return out;
  }), [rows, grouped, palette]);
  const columns = [
    { key: "period", label: "Periodo", format: (v) => fmtPeriod(v, interval) },
    ...(grouped ? palette.items.map((it) => ({ key: `g:${it.key}`, label: it.label, numeric: true })) : []),
    { key: "total", label: "Total resueltas", numeric: true },
  ];
  const total = rows.reduce((s, r) => s + r.total, 0);
  const last = series.length - 1;
  return (
    <ChartCard title="Throughput" subtitle={`Incidencias resueltas por ${interval === "day" ? "día" : interval === "month" ? "mes" : "semana"}${grouped ? ` · por ${groupLabel.toLowerCase()}` : ""}`}
               columns={columns} rows={data} csvName="throughput" busy={busy}
               empty={!total && "No se resolvieron incidencias en el rango."}
               legend={grouped ? <LegendRow items={series} /> : null}>
      <div style={{ height }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }} barCategoryGap={2}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="period" {...AXIS} minTickGap={16} tickFormatter={(v) => fmtPeriod(v, interval, true)} />
            <YAxis {...AXIS} allowDecimals={false} />
            <Tooltip cursor={BAR_CURSOR} content={({ active, payload, label }) => active && payload?.length ? (
              <TooltipCard title={fmtPeriod(label, interval)} footer={grouped ? `Total: ${payload[0].payload.total}` : null}
                           rows={series.filter((s) => !grouped || payload[0].payload[`g:${s.key}`]).map((s) => ({
                             label: grouped ? s.label : "resueltas", value: fmtNum(payload[0].payload[`g:${s.key}`], 0), color: s.color,
                           }))} />
            ) : null} />
            {series.map((s, i) => (
              <Bar key={s.key} dataKey={`g:${s.key}`} name={s.label} stackId="tp" fill={s.color} {...BAR}
                   stroke="var(--bg)" strokeWidth={grouped ? 2 : 0} radius={i === last ? [4, 4, 0, 0] : 0} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ cycle-time histogram */

export function CycleHistogram({ bins, busy, height = 240, title = "Distribución del tiempo de ciclo", compact }) {
  const total = bins.reduce((s, b) => s + b.count, 0);
  const columns = [
    { key: "label", label: "Tiempo de ciclo" },
    { key: "count", label: "Incidencias", numeric: true },
    { label: "%", numeric: true, value: (r) => (total ? Math.round((r.count / total) * 1000) / 10 : 0) },
  ];
  const chart = (
    <div style={{ height }}>
      <ResponsiveContainer>
        <BarChart data={bins} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="label" {...AXIS} interval={0} tick={{ ...AXIS.tick, fontSize: 10 }} />
          <YAxis {...AXIS} allowDecimals={false} />
          <Tooltip cursor={BAR_CURSOR} content={({ active, payload }) => active && payload?.length ? (
            <TooltipCard title={payload[0].payload.label} rows={[
              { label: "incidencias", value: fmtNum(payload[0].payload.count, 0), color: SERIES[0] },
              { label: "del total", value: `${fmtNum(total ? (payload[0].payload.count / total) * 100 : 0)} %` },
            ]} />
          ) : null} />
          <Bar dataKey="count" name="Incidencias" fill={SERIES[0]} radius={[4, 4, 0, 0]} {...BAR} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
  if (compact) return total ? chart : <p className="py-6 text-center text-sm text-fg-subtle">Sin incidencias con ciclo medido.</p>;
  return (
    <ChartCard title={title} subtitle="Incidencias resueltas en el rango, por días de ciclo" columns={columns} rows={bins}
               csvName="distribucion-tiempo-de-ciclo" busy={busy} empty={!total && "Ninguna incidencia resuelta en el rango llegó a empezarse (estado en curso)."}>
      {chart}
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ time in status */

export function TimeInStatusChart({ data, busy, categories }) {
  const statuses = data?.statuses ?? [];
  const unit = durationUnit(Math.max(0, ...statuses.map((s) => s.avg_hours ?? 0)));
  const rows = statuses.map((s) => ({ ...s, avg: (s.avg_hours ?? 0) / unit.div }));
  const catLabel = (c) => categories?.find((x) => x.value === c)?.label ?? c;
  const columns = [
    { key: "name", label: "Estado" },
    { key: "category", label: "Categoría", format: (v) => catLabel(v) },
    { key: "issues", label: "Incidencias", numeric: true },
    { key: "visits", label: "Visitas", numeric: true },
    { key: "avg_hours", label: "Media (h)", numeric: true, format: (v) => fmtHours(v) },
    { key: "p50_hours", label: "Mediana (h)", numeric: true, format: (v) => fmtHours(v) },
    { key: "p85_hours", label: "p85 (h)", numeric: true, format: (v) => fmtHours(v) },
    { key: "total_hours", label: "Total (h)", numeric: true, format: (v) => fmtHours(v) },
  ];
  return (
    <ChartCard title="Tiempo en cada estado" subtitle={`Media por incidencia que pasó por el estado · ${fmtNum(data?.issues ?? 0, 0)} resueltas en el rango`}
               columns={columns} rows={statuses} csvName="tiempo-en-estado" busy={busy}
               empty={!statuses.length && "No hay transiciones de las incidencias resueltas en el rango."}>
      <div style={{ height: Math.max(140, rows.length * 34 + 40) }}>
        <ResponsiveContainer>
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" horizontal={false} />
            <XAxis type="number" {...AXIS} tickFormatter={(v) => `${fmtNum(v)} ${unit.suffix}`} />
            <YAxis type="category" dataKey="name" {...AXIS} width={120} tick={{ ...AXIS.tick, fill: "var(--text-subtle)" }} />
            <Tooltip cursor={BAR_CURSOR} content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const s = payload[0].payload;
              return (
                <TooltipCard title={`${s.name} · ${catLabel(s.category)}`} footer={`${s.issues} incidencias · ${s.visits} visitas`} rows={[
                  { label: "media", value: fmtHours(s.avg_hours), color: SERIES[0] },
                  { label: "mediana", value: fmtHours(s.p50_hours) },
                  { label: "p85", value: fmtHours(s.p85_hours) },
                ]} />
              );
            }} />
            <Bar dataKey="avg" name="Media" fill={SERIES[0]} radius={[0, 4, 4, 0]} {...BAR} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ control chart */

function controlRows(points, palette) {
  return points.map((p) => {
    const avg = p.avg_hours ?? 0;
    const std = p.std_hours ?? 0;
    return {
      t: Date.parse(p.resolved_at), v: p.value_hours, avg, band: [Math.max(0, avg - std), avg + std],
      key: p.key, summary: p.summary, type: p.type, group: p.group, reopened: p.reopened,
      color: palette ? palette.color(palette.slot(p.group)) : SERIES[0],
    };
  });
}

export function ControlChartPlot({ data, height = 320, compact }) {
  const router = useRouter();
  const [scale, setScale] = useState("linear");
  const grouped = !!data.scope?.group_by && data.groups?.length > 0;
  const palette = useMemo(() => {
    if (!grouped) return null;
    const weight = new Map();
    data.points.forEach((p) => weight.set(p.group, (weight.get(p.group) ?? 0) + 1));
    return groupPalette(data.groups, weight);
  }, [data, grouped]);
  const rows = useMemo(() => controlRows(data.points, palette), [data.points, palette]);
  const unit = durationUnit(Math.max(0, ...rows.map((r) => r.v ?? 0)));
  const fmtY = (h) => `${fmtNum(h / unit.div)} ${unit.suffix}`;
  const legend = [
    ...(grouped ? palette.items.map((it) => ({ ...it, kind: "dot" })) : [{ label: "Incidencia", color: SERIES[0], kind: "dot" }]),
    { label: "Media móvil", color: "var(--text-subtle)", kind: "line" },
    { label: "Desviación estándar", color: "var(--series-other)", kind: "band" },
  ];
  const open = (row) => row?.key && router.push(`/browse/${row.key}`);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <LegendRow items={legend} className="mb-0 flex-1" />
        {!compact && (
          <div className="flex gap-1" role="group" aria-label="Escala del eje">
            <Button size="sm" variant={scale === "linear" ? "selected" : "subtle"} onClick={() => setScale("linear")}>Lineal</Button>
            <Button size="sm" variant={scale === "sqrt" ? "selected" : "subtle"} onClick={() => setScale("sqrt")} title="Comprime los valores altos para ver mejor los bajos">Comprimida</Button>
          </div>
        )}
      </div>
      <div className="mt-2" style={{ height }}>
        <ResponsiveContainer>
          <ComposedChart data={rows} margin={{ top: 8, right: 12, left: compact ? -12 : 0, bottom: 0 }}
                         onClick={(s) => { const i = s?.activeTooltipIndex ?? s?.activeIndex; if (i !== undefined && i !== null) open(rows[Number(i)]); }}
                         style={{ cursor: "pointer" }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} {...AXIS} minTickGap={32}
                   tickFormatter={(t) => fmtDate(new Date(t), "d MMM")} />
            <YAxis {...AXIS} scale={scale} domain={[0, "auto"]} tickFormatter={fmtY} width={compact ? 44 : 56} />
            <Tooltip cursor={CURSOR} isAnimationActive={false} content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const r = payload[0].payload;
              return (
                <div className="pointer-events-none max-w-xs rounded-[3px] border border-line bg-bg-overlay px-3 py-2 text-xs shadow-[var(--shadow-overlay)]">
                  <div className="flex items-center gap-1.5 font-medium text-fg">{r.type && <IssueTypeIcon type={r.type} size={14} />}{r.key}{r.reopened && <span className="font-normal text-fg-subtle">· reabierta</span>}</div>
                  <div className="mb-1 line-clamp-2 text-fg-subtle">{r.summary}</div>
                  <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full" style={{ background: r.color }} /><b className="tabular-nums text-fg">{fmtHours(r.v)}</b><span className="text-fg-subtle">{data.metric_label.toLowerCase()}</span></div>
                  <div className="flex items-center gap-2"><span className="h-0.5 w-3 rounded-full bg-[var(--text-subtle)]" /><b className="tabular-nums text-fg">{fmtHours(r.avg)}</b><span className="text-fg-subtle">media móvil</span></div>
                  <div className="mt-1 text-fg-subtlest">Resuelta el {fmtDate(new Date(r.t), "d MMM yyyy, HH:mm")} · clic para abrir</div>
                </div>
              );
            }} />
            <Area dataKey="band" type="linear" stroke="none" fill="var(--series-other)" fillOpacity={0.22} isAnimationActive={false} activeDot={false} />
            <Line dataKey="avg" type="linear" stroke="var(--text-subtle)" strokeWidth={2} dot={false} activeDot={false} isAnimationActive={false} />
            <Scatter dataKey="v" isAnimationActive={false} shape={(p) => (
              <circle cx={p.cx} cy={p.cy} r={compact ? 3.5 : 4.5} fill={p.payload.color} stroke="var(--bg)" strokeWidth={2} />
            )} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function ControlChartCard({ data, busy, actions, height }) {
  const points = data?.points ?? [];
  const s = data?.stats;
  const columns = [
    { key: "key", label: "Clave", render: (r) => <Link className="text-link hover:underline" href={`/browse/${r.key}`}>{r.key}</Link> },
    { key: "summary", label: "Resumen" },
    { key: "resolved_at", label: "Resuelta", format: (v) => fmtDate(v, "d MMM yyyy HH:mm") },
    { key: "value_hours", label: `${data?.metric_label ?? "Tiempo"} (h)`, numeric: true, format: (v) => fmtHours(v) },
    { key: "avg_hours", label: "Media móvil (h)", numeric: true, format: (v) => fmtHours(v) },
    { key: "std_hours", label: "Desv. estándar (h)", numeric: true, format: (v) => fmtHours(v) },
    { label: "Reabierta", value: (r) => (r.reopened ? "Sí" : "No") },
  ];
  const subtitle = s?.count
    ? `${fmtNum(s.count, 0)} incidencias · media ${fmtHours(s.mean_hours)} · p50 ${fmtHours(s.p50_hours)} · p85 ${fmtHours(s.p85_hours)} · p95 ${fmtHours(s.p95_hours)} · ventana de ${data.window}`
      + (data.truncated ? ` · se muestran las ${fmtNum(points.length, 0)} más recientes` : "")
    : "Cada punto es una incidencia resuelta";
  return (
    <ChartCard title={`Gráfico de control · ${data?.metric_label ?? ""}`} subtitle={subtitle} columns={columns} rows={points}
               csvName="grafico-de-control" busy={busy} actions={actions}
               empty={data && !points.length && "Ninguna incidencia resuelta en el rango tiene este tiempo medido."}>
      {data && <ControlChartPlot data={data} height={height} />}
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ per-group table & WIP */

export function GroupTable({ rows, label, busy }) {
  const columns = [
    { key: "label", label },
    { key: "created", label: "Creadas", numeric: true },
    { key: "resolved", label: "Resueltas", numeric: true },
    { key: "wip", label: "En curso", numeric: true },
    { key: "cycle_p50", label: "Ciclo p50 (h)", numeric: true, format: (v) => fmtHours(v) },
    { key: "cycle_p85", label: "Ciclo p85 (h)", numeric: true, format: (v) => fmtHours(v) },
    { key: "lead_p50", label: "Entrega p50 (h)", numeric: true, format: (v) => fmtHours(v) },
    { key: "lead_p85", label: "Entrega p85 (h)", numeric: true, format: (v) => fmtHours(v) },
  ];
  return (
    <ChartCard title={`Por ${label.toLowerCase()}`} columns={columns} rows={rows} csvName={`por-${label.toLowerCase()}`} busy={busy}
               empty={!rows.length && "Sin datos para agrupar."}>
      <TableOnly columns={columns} rows={rows} />
    </ChartCard>
  );
}

function TableOnly({ columns, rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr>{columns.map((c) => <th key={c.label} scope="col" className={`whitespace-nowrap px-2 pb-1 text-xs font-semibold text-fg-subtle ${c.numeric ? "text-right" : "text-left"}`}>{c.label}</th>)}</tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.key ?? r.label} className="border-t border-line">
            {columns.map((c) => <td key={c.label} className={`px-2 py-1 ${c.numeric ? "text-right tabular-nums" : ""}`}>{c.format ? c.format(r[c.key]) : r[c.key]}</td>)}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function WipList({ items, busy, groupLabels }) {
  const columns = [
    { key: "key", label: "Clave", render: (r) => <Link className="text-link hover:underline" href={`/browse/${r.key}`}>{r.key}</Link> },
    { key: "summary", label: "Resumen" },
    { key: "status", label: "Estado", render: (r) => <Lozenge category={r.status_category}>{r.status}</Lozenge> },
    { key: "age_hours", label: "Antigüedad (h)", numeric: true, format: (v) => fmtHours(v) },
    ...(groupLabels ? [{ key: "group", label: "Grupo", value: (r) => groupLabels.get(r.group) ?? "" }] : []),
  ];
  return (
    <ChartCard title="Trabajo en curso más antiguo" subtitle="Antigüedad desde que empezó el trabajo" columns={columns} rows={items}
               csvName="wip-mas-antiguo" busy={busy} empty={!items.length && "No hay incidencias en curso."}>
      <ul className="divide-y divide-line">
        {items.map((r) => (
          <li key={r.key} className="flex items-center gap-2 py-1.5 text-sm">
            <Link className="shrink-0 text-link hover:underline" href={`/browse/${r.key}`}>{r.key}</Link>
            <span className="min-w-0 flex-1 truncate" title={r.summary}>{r.summary}</span>
            <Lozenge category={r.status_category}>{r.status}</Lozenge>
            <span className="w-16 shrink-0 text-right tabular-nums text-fg-subtle">{fmtHours(r.age_hours)}</span>
          </li>
        ))}
      </ul>
    </ChartCard>
  );
}

export { OTHER_KEY };
