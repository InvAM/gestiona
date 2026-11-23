"use client";

// One filter row above everything it scopes: date range first, then source, group, interval.
// Every option label comes from GET /meta → analytics.

import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { JqlEditor } from "@/components/search/jql-editor";
import { Button } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { useMeta, useProjects } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { dateRange, daysBetween } from "./use-analytics";

const sel = "h-8 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-sm text-fg hover:bg-bg-hover focus:border-focus focus:outline-none";

function Labeled({ label, children, className, group }) {
  const Tag = group ? "div" : "label";
  return (
    <Tag className={cn("flex flex-col gap-1", className)}>
      <span className="text-xs font-semibold text-fg-subtle">{label}</span>
      {children}
    </Tag>
  );
}

export function RangeControl({ value, onChange, now }) {
  const meta = useMeta();
  const a = meta.data?.analytics;
  const presets = a?.range_presets ?? [];
  const custom = !value.preset;
  const range = dateRange(value, now);
  const days = daysBetween(range.start, range.end);
  const tooLong = a && days > a.max_range_days;
  const inverted = custom && range.start && range.end && range.start > range.end;
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Labeled label="Periodo">
        <select className={sel} value={custom ? "custom" : String(value.preset)}
                onChange={(e) => {
                  if (e.target.value === "custom") onChange({ ...value, preset: null, start: range.start, end: range.end });
                  else onChange({ ...value, preset: Number(e.target.value) });
                }}>
          {presets.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          <option value="custom">Personalizado…</option>
        </select>
      </Labeled>
      {custom && (
        <>
          <Labeled label="Desde"><input type="date" className={sel} value={value.start} max={value.end || undefined} onChange={(e) => onChange({ ...value, start: e.target.value })} /></Labeled>
          <Labeled label="Hasta"><input type="date" className={sel} value={value.end} min={value.start || undefined} onChange={(e) => onChange({ ...value, end: e.target.value })} /></Labeled>
        </>
      )}
      {(tooLong || inverted) && (
        <p role="alert" className="pb-1.5 text-xs text-danger">
          {inverted ? "La fecha de inicio debe ser anterior a la de fin." : `El rango máximo es de ${a.max_range_days} días.`}
        </p>
      )}
    </div>
  );
}

export function rangeIsValid(value, now, maxDays) {
  const r = dateRange(value, now);
  if (!r.start || !r.end || r.start > r.end) return false;
  return !maxDays || daysBetween(r.start, r.end) <= maxDays;
}

function ProjectsControl({ value, onChange }) {
  const projects = useProjects();
  const opts = (projects.data ?? []).map((p) => ({ value: p.key, label: p.name, description: p.key }));
  const picked = value.projects;
  const label = !picked.length ? "Todos mis proyectos"
    : picked.length <= 3 ? picked.join(", ") : `${picked.length} proyectos`;
  const toggle = (k) => onChange({ ...value, projects: picked.includes(k) ? picked.filter((x) => x !== k) : [...picked, k].sort() });
  return (
    <Picker multiple value={picked} options={opts} onSelect={toggle} width={320} placeholder="Buscar proyecto…"
            footer={picked.length ? <Button size="sm" variant="subtle" className="w-full justify-center" onClick={() => onChange({ ...value, projects: [] })}>Todos mis proyectos</Button> : null}
            trigger={<button type="button" className={cn(sel, "flex min-w-48 items-center justify-between gap-2 text-left")}>
              <span className="truncate">{label}</span><ChevronDown size={14} className="shrink-0 text-fg-subtle" /></button>} />
  );
}

function JqlControl({ value, onChange }) {
  const [draft, setDraft] = useState(value.jql);
  const dirty = draft.trim() !== value.jql.trim();
  return (
    <div className="flex min-w-[18rem] flex-1 items-start gap-2">
      <div className="min-w-0 flex-1"><JqlEditor value={draft} onChange={setDraft} onSubmit={() => onChange({ ...value, jql: draft })} /></div>
      <Button variant={dirty ? "primary" : "default"} onClick={() => onChange({ ...value, jql: draft })}>Aplicar</Button>
    </div>
  );
}

/**
 * `showSource`: projects / JQL chooser (global page). `jqlOnly`: refine by JQL inside a fixed
 * scope (project reports). `showGroup`, `showInterval`: group-by and period controls.
 */
export function FiltersBar({ value, onChange, now, showSource = true, jqlOnly = false, showGroup = true, showInterval = true }) {
  const meta = useMeta();
  const a = meta.data?.analytics;
  return (
    <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
      <RangeControl value={value} onChange={onChange} now={now} />
      {showSource && (
        <Labeled label="Origen" group>
          <div className="flex gap-1" role="radiogroup" aria-label="Origen de los datos">
            <Button variant={value.source === "projects" ? "selected" : "subtle"} role="radio" aria-checked={value.source === "projects"} onClick={() => onChange({ ...value, source: "projects" })}>Proyectos</Button>
            <Button variant={value.source === "jql" ? "selected" : "subtle"} role="radio" aria-checked={value.source === "jql"} onClick={() => onChange({ ...value, source: "jql" })}>JQL</Button>
          </div>
        </Labeled>
      )}
      {showSource && value.source === "projects" && <Labeled label="Proyectos" group><ProjectsControl value={value} onChange={onChange} /></Labeled>}
      {showGroup && (
        <Labeled label="Agrupar por">
          <select className={sel} value={value.group_by} onChange={(e) => onChange({ ...value, group_by: e.target.value })}>
            <option value="">Sin agrupar</option>
            {(a?.group_by ?? []).map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
          </select>
        </Labeled>
      )}
      {showInterval && (
        <Labeled label="Intervalo">
          <select className={sel} value={value.interval} onChange={(e) => onChange({ ...value, interval: e.target.value })}>
            {(a?.intervals ?? []).map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
          </select>
        </Labeled>
      )}
      {((showSource && value.source === "jql") || jqlOnly) && (
        <Labeled label={jqlOnly ? "Refinar con JQL (opcional)" : "JQL"} className="w-full" group><JqlControl key={value.jql} value={value} onChange={onChange} /></Labeled>
      )}
    </div>
  );
}

/** Cycle / lead toggle for the control chart (labels from /meta → analytics.metrics). */
export function MetricToggle({ value, onChange }) {
  const meta = useMeta();
  const metrics = meta.data?.analytics?.metrics ?? [];
  return (
    <div className="flex gap-1" role="radiogroup" aria-label="Métrica">
      {metrics.map((m) => (
        <Button key={m.value} size="sm" role="radio" aria-checked={value === m.value} title={m.description}
                variant={value === m.value ? "selected" : "subtle"} onClick={() => onChange(m.value)}>{m.label}</Button>
      ))}
    </div>
  );
}
