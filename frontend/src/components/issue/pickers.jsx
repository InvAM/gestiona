"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { Picker } from "@/components/ui/picker";
import { Avatar } from "@/components/ui/primitives";
import { api, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta, useUsers } from "@/lib/api/hooks";

export function UserPicker({ trigger, value, onSelect, projectKey, assignable, allowNone = true,
                             noneLabel = "Sin asignar", meId, multiple, align, onPickUser }) {
  const [q, setQ] = useState("");
  const users = useUsers(q, projectKey, assignable);
  const opts = (users.data ?? []).map((u) => ({
    value: u.id, label: u.id === meId ? `${u.name} (tú)` : u.name, description: u.email,
    icon: <Avatar user={u} size="sm" />,
  }));
  if (meId) opts.sort((a, b) => (a.value === meId ? -1 : b.value === meId ? 1 : 0));
  if (allowNone && !q) opts.unshift({ value: 0, label: noneLabel, description: "", icon: <Avatar user={null} size="sm" /> });
  return (
    <Picker trigger={trigger} options={opts} value={value ?? (allowNone ? 0 : null)} multiple={multiple}
            onSearch={setQ} loading={users.isFetching} align={align}
            onSelect={(v) => { onSelect(v === 0 ? null : v); onPickUser?.(users.data?.find((u) => u.id === v) ?? null); }}
            placeholder="Buscar personas" />
  );
}

export function LabelPicker({ trigger, value, onChange, projectKey }) {
  const [q, setQ] = useState("");
  const labels = useQuery({
    queryKey: ["labels", projectKey ?? "", q],
    queryFn: () => unwrap(api.GET("/api/v1/labels", { params: { query: { q, project: projectKey } } })),
  });
  const all = Array.from(new Set([...(value ?? []), ...(labels.data ?? [])]));
  const toggle = (l) => onChange(value.includes(l) ? value.filter((x) => x !== l) : [...value, l]);
  return (
    <Picker trigger={trigger} multiple value={value} onSearch={setQ}
            options={all.filter((l) => !q || l.toLowerCase().includes(q.toLowerCase())).map((l) => ({ value: l, label: l }))}
            onSelect={toggle} placeholder="Buscar o crear etiqueta"
            creatable={(t) => (all.includes(t.replace(/\s+/g, "_")) ? null : <span>Crear etiqueta «{t.replace(/\s+/g, "_")}»</span>)}
            onCreate={(t) => toggle(t.replace(/\s+/g, "_"))} emptyText="Escribe para crear una etiqueta" />
  );
}

export function PriorityPicker({ trigger, meta, value, onSelect }) {
  return (
    <Picker trigger={trigger} value={value} onSelect={onSelect} width={220} placeholder="Prioridad"
            options={meta.priorities.map((p) => ({ value: p.id, label: p.name, icon: <PriorityIcon priority={p} /> }))} />
  );
}

export function TypePicker({ trigger, meta, value, onSelect, levels }) {
  const types = meta.issue_types.filter((t) => !levels || levels.includes(t.level));
  return (
    <Picker trigger={trigger} value={value} onSelect={onSelect} width={240} placeholder="Tipo de incidencia"
            options={types.map((t) => ({ value: t.id, label: t.name, icon: <IssueTypeIcon type={t} /> }))} />
  );
}

export function IssuePicker({ trigger, projectKey, level, exclude, onSelect, placeholder = "Buscar incidencia" }) {
  const [q, setQ] = useState("");
  const res = useQuery({
    queryKey: ["picker", q, projectKey, level, exclude],
    queryFn: () => unwrap(api.GET("/api/v1/issues/picker", { params: { query: { q, project: projectKey, level, exclude, limit: 20 } } })),
  });
  const items = res.data ?? [];
  return (
    <Picker trigger={trigger} onSearch={setQ} loading={res.isFetching} width={380} placeholder={placeholder}
            options={items.map((i) => ({ value: i.id, label: `${i.key} ${i.summary}`, icon: <IssueTypeIcon type={i.type} /> }))}
            onSelect={(id) => { const i = items.find((x) => x.id === id); if (i) onSelect(i); }} />
  );
}

export function SprintPicker({ trigger, boardId, value, onSelect }) {
  const meta = useMeta();
  const sprints = useQuery({
    queryKey: ["sprints", boardId],
    queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}/sprints", { params: { path: { board_id: boardId }, query: { state: "active,future" } } })),
    enabled: !!boardId,
  });
  const opts = [{ value: 0, label: "Ninguno (backlog)" },
    ...(sprints.data ?? []).map((s) => ({ value: s.id, label: s.name, description: choiceLabel(meta.data?.sprint_states, s.state) }))];
  return (
    <Picker trigger={trigger} value={value ?? 0} options={opts} width={260} placeholder="Sprint"
            onSelect={(v) => onSelect(v === 0 ? null : v)} />
  );
}

export function MultiNamedPicker({ trigger, options, value, onChange, placeholder }) {
  return (
    <Picker trigger={trigger} multiple value={value} placeholder={placeholder}
            options={options.map((o) => ({ value: o.id, label: o.name }))}
            onSelect={(id) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id])} />
  );
}
