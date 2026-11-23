"use client";

import { ChevronDown, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { IssueTypeIcon } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { AvatarStack } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export const emptyFilters = { q: "", assignees: [], epics: [], types: [], quick: [], label: null };

export function toQuery(f) {
  return {
    q: f.q || undefined,
    assignees: f.assignees.join(",") || undefined,
    epics: f.epics.join(",") || undefined,
    types: f.types.join(",") || undefined,
    quick_filters: f.quick.join(",") || undefined,
    label: f.label ?? undefined,
  };
}

export function useDebounced(v, ms = 250) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export function FiltersBar({ value, onChange, board, meta, people, epics, extra }) {
  const toggle = (k, id) =>
    onChange({ ...value, [k]: value[k].includes(id) ? value[k].filter((x) => x !== id) : [...value[k], id] });
  const active = value.q || value.assignees.length || value.epics.length || value.types.length ||
    value.quick.length || value.label;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-subtlest" />
        <input value={value.q} onChange={(e) => onChange({ ...value, q: e.target.value })} placeholder="Buscar en el tablero"
               className="h-8 w-44 rounded-[3px] border-2 border-line bg-bg pl-7 pr-2 text-sm outline-none focus:border-focus" />
      </div>
      {people.length > 0 && <AvatarStack users={people} selected={value.assignees} onToggle={(id) => toggle("assignees", id)} max={6} />}
      {epics.length > 0 && (
        <Picker multiple value={value.epics} onSelect={(id) => toggle("epics", id)} width={300} placeholder="Buscar épica"
                options={[{ value: 0, label: "Incidencias sin épica" }, ...epics.map((e) => ({ value: e.id, label: e.summary, description: e.key,
                  icon: <span className="h-3 w-3 rounded-sm" style={{ background: e.color }} /> }))]}
                trigger={<Button variant={value.epics.length ? "selected" : "subtle"}>Épica{value.epics.length ? ` (${value.epics.length})` : ""}<ChevronDown size={14} /></Button>} />
      )}
      <Picker multiple value={value.types} onSelect={(id) => toggle("types", id)} width={240}
              options={meta.issue_types.filter((t) => t.level !== 1).map((t) => ({ value: t.id, label: t.name, icon: <IssueTypeIcon type={t} /> }))}
              trigger={<Button variant={value.types.length ? "selected" : "subtle"}>Tipo{value.types.length ? ` (${value.types.length})` : ""}<ChevronDown size={14} /></Button>} />
      {board.quick_filters.map((qf) => (
        <Button key={qf.id} variant={value.quick.includes(qf.id) ? "selected" : "subtle"} title={qf.description || qf.jql}
                onClick={() => toggle("quick", qf.id)}>{qf.name}</Button>
      ))}
      {value.label && (
        <Button variant="selected" onClick={() => onChange({ ...value, label: null })}>Etiqueta: {value.label}<X size={14} /></Button>
      )}
      {active ? <Button variant="link" onClick={() => onChange(emptyFilters)} className={cn("ml-1")}>Borrar filtros</Button> : null}
      <div className="ml-auto flex items-center gap-2">{extra}</div>
    </div>
  );
}
