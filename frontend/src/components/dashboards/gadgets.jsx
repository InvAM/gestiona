"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ControlChartGadget, CycleTimeGadget, FlowGadgetConfig } from "@/components/analytics/gadgets";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { Spinner } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Avatar, Field, Input, Lozenge, Textarea } from "@/components/ui/primitives";
import { ApiError, api, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta, useProjectMeta, useProjects } from "@/lib/api/hooks";
import { cn, fmtDate, fmtRelative } from "@/lib/utils";

// Gadget kinds and group-by fields (with labels) come from GET /meta.
function useGroupLabel() {
  const meta = useMeta();
  const fields = meta.data?.group_by_fields ?? [];
  return (v) => fields.find((f) => f.value === v)?.label ?? v;
}

const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
const OTHER = "var(--series-other)";

export function defaultConfig(kind) {
  switch (kind) {
    case "filter_results": return { jql: "resolution = Unresolved ORDER BY updated DESC", limit: 10 };
    case "pie": case "stats": return { jql: "resolution = Unresolved", group_by: "status" };
    case "two_d": return { jql: "resolution = Unresolved", x: "status", y: "assignee" };
    case "created_vs_resolved": return { jql: "", days: 30, period: "day" };
    case "activity": return { limit: 15 };
    case "assigned_to_me": return { limit: 10 };
    case "text": return { text: "" };
    case "control_chart": return { jql: "", days: 90, metric: "cycle" };
    case "cycle_time": return { jql: "", days: 90 };
    default: return {};
  }
}

/* ------------------------------------------------------------------ body */

export function GadgetBody({ dashboardId, gadget }) {
  const q = useQuery({
    queryKey: ["gadget", gadget.id, gadget.config],
    queryFn: () => unwrap(api.GET("/api/v1/dashboards/{did}/gadgets/{gid}/data", { params: { path: { did: dashboardId, gid: gadget.id } } })),
    refetchInterval: 5 * 60_000,
    retry: false,
  });
  if (q.isPending) return <div className="flex h-24 items-center justify-center"><Spinner /></div>;
  if (q.error) return <p className="text-sm text-danger">{q.error instanceof ApiError ? q.error.message : "No se pudo cargar"}</p>;
  return <GadgetView kind={gadget.kind} config={gadget.config} data={q.data} />;
}

export function GadgetView({ kind, config, data }) {
  switch (kind) {
    case "filter_results": case "assigned_to_me":
      return <IssueTable rows={data.issues} total={data.total} jql={kind === "assigned_to_me" ? "assignee = currentUser() AND resolution = Unresolved" : String(config.jql ?? "")} />;
    case "pie": return <Donut groups={data.groups} total={data.total} field={String(data.group_by)} />;
    case "stats": return <StatBars groups={data.groups} total={data.total} field={String(data.group_by)} />;
    case "two_d": return <TwoD data={data} />;
    case "created_vs_resolved": return <CreatedResolved data={data} />;
    case "sprint_burndown": return <Burndown data={data} />;
    case "activity": return <Activity items={data.items} />;
    case "control_chart": return <ControlChartGadget data={data} />;
    case "cycle_time": return <CycleTimeGadget data={data} />;
    case "text": return <p className="whitespace-pre-wrap text-sm">{String(data.text || "") || <span className="text-fg-subtlest">Sin texto. Configura el gadget para escribir.</span>}</p>;
    default: return null;
  }
}

function IssueTable({ rows, total, jql }) {
  if (!rows.length) return <p className="py-4 text-center text-sm text-fg-subtle">No hay incidencias.</p>;
  return (
    <div>
      <table className="w-full text-sm">
        <tbody>{rows.map((i) => (
          <tr key={i.key} className="border-b border-line last:border-0">
            <td className="w-6 py-1.5"><IssueTypeIcon type={i.type} /></td>
            <td className="whitespace-nowrap py-1.5 pr-2"><Link className="text-link hover:underline" href={`/browse/${i.key}`}>{i.key}</Link></td>
            <td className="max-w-0 truncate py-1.5 pr-2" title={i.summary}>{i.summary}</td>
            <td className="w-5 py-1.5"><PriorityIcon priority={i.priority} /></td>
            <td className="py-1.5 pr-2"><Lozenge category={i.status.category}>{i.status.name}</Lozenge></td>
            <td className="w-6 py-1.5"><Avatar user={i.assignee} size="xs" /></td>
          </tr>
        ))}</tbody>
      </table>
      <div className="mt-2 flex justify-between text-xs text-fg-subtle">
        <span>{rows.length} de {total}</span>
        <Link className="text-link hover:underline" href={`/issues?jql=${encodeURIComponent(jql)}`}>Ver todas</Link>
      </div>
    </div>
  );
}

/** Colour follows the entity (sorted by key), not its rank; past 7 groups fold into "Otros". */
function colorize(groups) {
  const shown = groups.slice(0, 7);
  const rest = groups.slice(7);
  const byKey = [...shown].sort((a, b) => String(a.key ?? "").localeCompare(String(b.key ?? ""), undefined, { numeric: true }));
  const colorOf = new Map(byKey.map((g, i) => [String(g.key), SERIES[i]]));
  const out = shown.map((g) => ({ ...g, color: colorOf.get(String(g.key)) }));
  if (rest.length) out.push({ key: "__other__", label: `Otros (${rest.length})`, count: rest.reduce((s, g) => s + g.count, 0), color: OTHER });
  return out;
}

const pct = (n, total) => (total ? `${Math.round((n / total) * 100)}%` : "0%");

function Donut({ groups, total, field }) {
  const groupLabel = useGroupLabel();
  const data = colorize(groups);
  if (!total) return <p className="py-4 text-center text-sm text-fg-subtle">No hay incidencias.</p>;
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="relative h-44 w-44 shrink-0">
        <ResponsiveContainer>
          <PieChart>
            <Pie data={data} dataKey="count" nameKey="label" innerRadius="58%" outerRadius="100%" stroke="var(--bg)" strokeWidth={2} isAnimationActive={false}>
              {data.map((g) => <Cell key={String(g.key)} fill={g.color} />)}
            </Pie>
            <Tooltip formatter={(v) => [`${v} (${pct(Number(v), total)})`, ""]} contentStyle={{ background: "var(--bg-overlay)", border: "1px solid var(--border)", color: "var(--text)", fontSize: 12 }} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"><b className="text-xl">{total}</b><span className="text-xs text-fg-subtle">incidencias</span></div>
      </div>
      <table className="min-w-[160px] flex-1 text-sm" aria-label={`Incidencias por ${groupLabel(field)}`}>
        <thead><tr className="text-left text-xs text-fg-subtle"><th className="pb-1">{groupLabel(field)}</th><th className="pb-1 text-right">N.º</th><th className="pb-1 text-right">%</th></tr></thead>
        <tbody>{data.map((g) => (
          <tr key={String(g.key)}>
            <td className="py-0.5"><span className="flex items-center gap-2"><span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: g.color }} /><span className="truncate">{g.label}</span></span></td>
            <td className="py-0.5 text-right tabular-nums">{g.count}</td>
            <td className="py-0.5 text-right tabular-nums text-fg-subtle">{pct(g.count, total)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function StatBars({ groups, total, field }) {
  const groupLabel = useGroupLabel();
  if (!total) return <p className="py-4 text-center text-sm text-fg-subtle">No hay incidencias.</p>;
  const max = Math.max(...groups.map((g) => g.count));
  return (
    <table className="w-full text-sm" aria-label={`Incidencias por ${groupLabel(field)}`}>
      <thead><tr className="text-left text-xs text-fg-subtle"><th className="pb-1">{groupLabel(field)}</th><th className="pb-1 text-right">N.º</th><th className="w-1/2 pb-1 pl-3">%</th></tr></thead>
      <tbody>{groups.slice(0, 20).map((g) => (
        <tr key={String(g.key)} className="group">
          <td className="max-w-0 truncate py-1 pr-2" title={g.label}>{g.label}</td>
          <td className="py-1 text-right tabular-nums">{g.count}</td>
          <td className="py-1 pl-3">
            <div className="flex items-center gap-2" title={`${g.label}: ${g.count} (${pct(g.count, total)})`}>
              <div className="h-3 rounded-r-[4px] bg-[var(--series-1)] group-hover:opacity-80" style={{ width: `${Math.max(2, (g.count / max) * 85)}%` }} />
              <span className="text-xs tabular-nums text-fg-subtle">{pct(g.count, total)}</span>
            </div>
          </td>
        </tr>
      ))}</tbody>
      <tfoot><tr className="border-t border-line text-xs text-fg-subtle"><td className="pt-1">Total</td><td className="pt-1 text-right tabular-nums">{total}</td><td /></tr></tfoot>
    </table>
  );
}

function TwoD({ data }) {
  const groupLabel = useGroupLabel();
  if (!data.total) return <p className="py-4 text-center text-sm text-fg-subtle">No hay incidencias.</p>;
  const max = Math.max(1, ...data.cells.flat());
  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <thead><tr><th className="px-2 py-1 text-left text-xs text-fg-subtle">{groupLabel(data.y)} \ {groupLabel(data.x)}</th>
          {data.xs.map((x) => <th key={String(x.key)} className="px-2 py-1 text-right text-xs font-semibold">{x.label}</th>)}<th className="px-2 py-1 text-right text-xs text-fg-subtle">Total</th></tr></thead>
        <tbody>{data.ys.map((y, r) => (
          <tr key={String(y.key)} className="border-t border-line">
            <td className="whitespace-nowrap px-2 py-1">{y.label}</td>
            {data.cells[r].map((n, c) => (
              <td key={c} className="px-2 py-1 text-right tabular-nums" style={n ? { background: `color-mix(in oklab, var(--series-1) ${Math.round((n / max) * 35)}%, transparent)` } : undefined}>{n || <span className="text-fg-subtlest">·</span>}</td>
            ))}
            <td className="px-2 py-1 text-right tabular-nums text-fg-subtle">{y.count}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

const axis = { stroke: "var(--text-subtlest)", fontSize: 11, tickLine: false, axisLine: false };
const tooltipStyle = { background: "var(--bg-overlay)", border: "1px solid var(--border)", color: "var(--text)", fontSize: 12 };

function CreatedResolved({ data }) {
  const fmt = (d) => fmtDate(d, data.period === "week" ? "d MMM" : "d/M");
  return (
    <div>
      <div className="mb-2 flex gap-4 text-sm">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--series-1)]" />Creadas <b className="tabular-nums">{data.created}</b></span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--series-2)]" />Resueltas <b className="tabular-nums">{data.resolved}</b></span>
      </div>
      <div className="h-48">
        <ResponsiveContainer>
          <LineChart data={data.series} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={fmt} {...axis} minTickGap={24} />
            <YAxis allowDecimals={false} {...axis} />
            <Tooltip labelFormatter={(l) => fmtDate(String(l), "d MMM yyyy")} contentStyle={tooltipStyle} cursor={{ stroke: "var(--border-strong)" }} />
            <Line name="Creadas" dataKey="created" stroke="var(--series-1)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "var(--bg)", strokeWidth: 2 }} isAnimationActive={false} />
            <Line name="Resueltas" dataKey="resolved" stroke="var(--series-2)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "var(--bg)", strokeWidth: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Burndown({ data }) {
  if (!data.sprint) return <p className="py-4 text-center text-sm text-fg-subtle">{String(data.board ?? "El tablero")} no tiene un sprint activo.</p>;
  const sprint = data.sprint;
  const timeline = data.timeline ?? [];
  const initial = Number(data.initial ?? 0);
  const points = [{ t: sprint.start ?? timeline[0]?.at, remaining: initial, guide: initial }, ...timeline.map((p) => ({ t: p.at, remaining: p.remaining, guide: undefined }))];
  if (sprint.end) points.push({ t: sprint.end, remaining: undefined, guide: 0 });
  const last = timeline.length ? timeline[timeline.length - 1].remaining : initial;
  return (
    <div>
      <div className="mb-2 flex items-baseline gap-3 text-sm"><b>{sprint.name}</b><span className="text-fg-subtle">Restante: <b className="tabular-nums text-fg">{last}</b> de {initial}</span>{sprint.end && <span className="text-xs text-fg-subtle">termina {fmtRelative(sprint.end)}</span>}</div>
      <div className="h-44">
        <ResponsiveContainer>
          <LineChart data={points} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="t" tickFormatter={(d) => fmtDate(d, "d/M")} {...axis} minTickGap={24} />
            <YAxis allowDecimals={false} {...axis} />
            <Tooltip labelFormatter={(l) => fmtDate(String(l), "d MMM HH:mm")} contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line name="Guía" dataKey="guide" stroke="var(--series-other)" strokeDasharray="5 5" connectNulls dot={false} isAnimationActive={false} />
            <Line name="Restante" dataKey="remaining" type="stepAfter" stroke="var(--series-1)" strokeWidth={2} connectNulls dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}


function Activity({ items }) {
  const meta = useMeta();
  if (!items.length) return <p className="py-4 text-center text-sm text-fg-subtle">Sin actividad reciente.</p>;
  return (
    <ul className="space-y-2.5">{items.map((a, i) => (
      <li key={i} className="flex gap-2 text-sm">
        <Avatar user={a.actor} size="sm" />
        <div className="min-w-0">
          <span className="font-medium">{a.actor?.name ?? "Alguien"}</span>{" "}
          {a.created ? "creó" : `cambió ${a.fields.map((f) => String(choiceLabel(meta.data?.issue_fields, f)).toLowerCase()).join(", ")} en`}{" "}
          <Link className="text-link hover:underline" href={`/browse/${a.issue.key}`}>{a.issue.key}</Link>
          <div className="truncate text-xs text-fg-subtle">{a.issue.summary} · {fmtRelative(a.at)}</div>
        </div>
      </li>
    ))}</ul>
  );
}

/* ------------------------------------------------------------------ config */

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

export function GadgetConfig({ kind, config, onChange }) {
  const set = (patch) => onChange({ ...config, ...patch });
  const filters = useQuery({ queryKey: ["filters", "all"], queryFn: () => unwrap(api.GET("/api/v1/filters")), enabled: ["filter_results", "pie", "stats", "two_d", "created_vs_resolved", "control_chart", "cycle_time"].includes(kind) });
  const [source, setSource] = useState(config.filter_id ? "filter" : "jql");
  const meta = useMeta();
  const groupSel = (key, label, twoD = false) => (
    <Field label={label}>
      <select className={sel} value={String(config[key] ?? "status")} onChange={(e) => set({ [key]: e.target.value })}>
        {(meta.data?.group_by_fields ?? []).filter((f) => !twoD || f.two_d).map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
      </select>
    </Field>
  );
  const sourceFields = (
    <div className="space-y-2 sm:col-span-2">
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-1.5"><input type="radio" checked={source === "jql"} onChange={() => { setSource("jql"); set({ filter_id: undefined }); }} />JQL</label>
        <label className="flex items-center gap-1.5"><input type="radio" checked={source === "filter"} onChange={() => setSource("filter")} />Filtro guardado</label>
      </div>
      {source === "jql" ? (
        <Input className="font-mono" value={String(config.jql ?? "")} placeholder="Vacío = todas las incidencias que puedes ver" onChange={(e) => set({ jql: e.target.value })} />
      ) : (
        <Picker value={config.filter_id ?? null} width={320} options={(filters.data ?? []).map((f) => ({ value: f.id, label: f.name, description: f.jql }))} onSelect={(v) => set({ filter_id: v })}
                trigger={<button className={sel}>{filters.data?.find((f) => f.id === config.filter_id)?.name ?? "Elegir filtro"}</button>} />
      )}
    </div>
  );
  const limit = (
    <Field label="Máximo de incidencias"><Input type="number" min={1} max={50} value={Number(config.limit ?? 10)} onChange={(e) => set({ limit: Number(e.target.value) })} /></Field>
  );
  switch (kind) {
    case "filter_results": return <div className="grid gap-3 sm:grid-cols-2">{sourceFields}{limit}</div>;
    case "assigned_to_me": return <div className="grid gap-3 sm:grid-cols-2">{limit}</div>;
    case "pie": case "stats": return <div className="grid gap-3 sm:grid-cols-2">{sourceFields}{groupSel("group_by", "Agrupar por")}</div>;
    case "two_d": return <div className="grid gap-3 sm:grid-cols-2">{sourceFields}{groupSel("x", "Columnas", true)}{groupSel("y", "Filas", true)}</div>;
    case "created_vs_resolved":
      return (
        <div className="grid gap-3 sm:grid-cols-2">{sourceFields}
          <Field label="Días hacia atrás"><Input type="number" min={7} max={365} value={Number(config.days ?? 30)} onChange={(e) => set({ days: Number(e.target.value) })} /></Field>
          <Field label="Agrupar"><select className={sel} value={String(config.period ?? "day")} onChange={(e) => set({ period: e.target.value })}><option value="day">Por día</option><option value="week">Por semana</option></select></Field>
        </div>
      );
    case "sprint_burndown": return <BoardChooser value={config.board_id} onChange={(id) => set({ board_id: id })} />;
    case "control_chart": case "cycle_time": return <div className="grid gap-3 sm:grid-cols-2">{sourceFields}<FlowGadgetConfig kind={kind} config={config} set={set} /></div>;
    case "activity": return (
      <div className="grid gap-3 sm:grid-cols-2">
        <ProjectChooser value={config.project} onChange={(k) => set({ project: k })} allowAll />{limit}
      </div>
    );
    case "text": return <Field label="Texto"><Textarea rows={6} value={String(config.text ?? "")} onChange={(e) => set({ text: e.target.value })} /></Field>;
    default: return null;
  }
}

function ProjectChooser({ value, onChange, allowAll }) {
  const projects = useProjects();
  const opts = [...(allowAll ? [{ value: "", label: "Todos los proyectos" }] : []), ...(projects.data ?? []).map((p) => ({ value: p.key, label: `${p.name} (${p.key})` }))];
  return (
    <Field label="Proyecto">
      <Picker value={value ?? ""} width={300} options={opts} onSelect={(v) => onChange(v || undefined)}
              trigger={<button className={sel}>{opts.find((o) => o.value === (value ?? ""))?.label ?? "Elegir proyecto"}</button>} />
    </Field>
  );
}

function BoardChooser({ value, onChange }) {
  const [project, setProject] = useState();
  const meta = useProjectMeta(project);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <ProjectChooser value={project} onChange={setProject} />
      <Field label="Tablero" error={meta.data && !meta.data.boards.length ? "Este proyecto no tiene tableros" : undefined}>
        <select className={cn(sel)} value={value ?? ""} disabled={!meta.data?.boards.length} onChange={(e) => onChange(Number(e.target.value))}>
          <option value="">{value && !meta.data ? `Tablero #${value}` : "Elegir tablero"}</option>
          {(meta.data?.boards ?? []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </Field>
    </div>
  );
}

export function GadgetPreview({ kind, config }) {
  const q = useQuery({
    queryKey: ["gadget-preview", kind, config],
    queryFn: () => unwrap(api.POST("/api/v1/dashboard-gadgets/preview", { body: { kind, config } })),
    retry: false,
  });
  return (
    <div className="rounded-[3px] border border-dashed border-line-strong p-3">
      <div className="mb-2 text-xs font-semibold text-fg-subtle">Vista previa</div>
      {q.isPending ? <Spinner /> : q.error ? <p className="text-sm text-danger">{q.error instanceof ApiError ? q.error.message : "Error"}</p>
        : <GadgetView kind={kind} config={config} data={q.data} />}
    </div>
  );
}
