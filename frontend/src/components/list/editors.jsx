"use client";

import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Avatar, Lozenge, Popover, PopoverAnchor, PopoverContent, Textarea } from "@/components/ui/primitives";
import { api, unwrap } from "@/lib/api/client";
import { useTransitions, useUsers } from "@/lib/api/hooks";
import { cn, fmtDuration, parseDuration } from "@/lib/utils";

/*
 * Inline cell editors. Contract: `onCommit(value, move)` saves (move = "down" | "up" |
 * "right" | "left" | null) and `onCancel()` discards. Enter/Tab save and move, Escape
 * cancels, clicking elsewhere saves (text) or applies (multi-select).
 */

const NONE = "__none__";

function moveFromKey(e) {
  if (e.key === "Tab") return e.shiftKey ? "left" : "right";
  if (e.key === "Enter") return e.shiftKey ? "up" : "down";
  return null;
}

/* ------------------------------------------------------------------ text-like */

function InputEditor({ type = "text", initial, initialText, parse, format, onCommit, onCancel, align, maxLength }) {
  const [text, setText] = useState(initialText ?? (initial === null || initial === undefined ? "" : format ? format(initial) : String(initial)));
  const [error, setError] = useState(null);
  const done = useRef(false);
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    if (type !== "text") return;
    if (initialText === undefined) el.select();
    else el.setSelectionRange(el.value.length, el.value.length);
  }, [initialText, type]);
  const finish = (move) => {
    if (done.current) return;
    try {
      const v = parse(text);
      done.current = true;
      onCommit(v, move);
    } catch (err) {
      setError(err.message);
      toast.error(err.message);
      if (move === null) { done.current = true; onCancel(); } // blur with invalid input: discard
    }
  };
  return (
    <div className="absolute inset-0 z-20">
      <input ref={ref} type={type} value={text} maxLength={maxLength} aria-invalid={!!error} aria-label="Editar celda"
             onChange={(e) => { setText(e.target.value); setError(null); }}
             onKeyDown={(e) => {
               e.stopPropagation();
               if (e.key === "Escape") { e.preventDefault(); done.current = true; onCancel(); return; }
               const m = moveFromKey(e);
               if (m) { e.preventDefault(); finish(m); }
             }}
             onBlur={() => finish(null)}
             title={error ?? undefined}
             className={cn("h-full w-full rounded-none border-2 border-focus bg-bg px-2 text-sm outline-none", align === "right" && "text-right", error && "border-danger")} />
    </div>
  );
}

function TextareaEditor({ initial, initialText, onCommit, onCancel }) {
  const [text, setText] = useState(initialText ?? initial ?? "");
  const done = useRef(false);
  const finish = (move) => {
    if (done.current) return;
    done.current = true;
    onCommit(text.trim() ? text : null, move);
  };
  return (
    <Popover open>
      <PopoverAnchor asChild><span className="absolute inset-0" /></PopoverAnchor>
      <PopoverContent align="start" className="w-96 p-2"
                      onEscapeKeyDown={(e) => { e.preventDefault(); done.current = true; onCancel(); }}
                      onInteractOutside={(e) => { e.preventDefault(); finish(null); }}>
        <Textarea autoFocus rows={5} value={text} aria-label="Editar texto" onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    e.stopPropagation();
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish("down"); }
                    if (e.key === "Tab") { e.preventDefault(); finish(e.shiftKey ? "left" : "right"); }
                  }} />
        <p className="mt-1 text-xs text-fg-subtlest">Intro guarda · Mayús+Intro salto de línea · Esc cancela</p>
      </PopoverContent>
    </Popover>
  );
}

/* ------------------------------------------------------------------ picker */

/**
 * Popover list anchored to the cell. `options`: [{key, label, description?, icon?, obj}].
 * `selected`: array of objs (single mode: 0 or 1). `keyOf(obj)` gives the option key.
 */
export function CellPicker({ options, selected, keyOf, multiple, onCommit, onCancel, onSearch, loading,
                             creatable, placeholder = "Buscar…", width = 300, emptyText = "Sin resultados", header, labelOf }) {
  const [draft, setDraft] = useState(selected);
  const [q, setQ] = useState("");
  const [hl, setHl] = useState("");
  const done = useRef(false);
  const draftKeys = new Set(draft.map((o) => (o === null ? NONE : String(keyOf(o)))));
  // selected values not in the (searched) options still show up so they can be removed
  const extra = multiple
    ? draft.filter((o) => o !== null && !options.some((x) => x.key === String(keyOf(o))))
      .map((o) => ({ key: String(keyOf(o)), label: labelOf?.(o) ?? o?.name ?? String(o), obj: o }))
    : [];
  const all = [...extra, ...options];
  const createKey = creatable && q.trim() ? creatable(q.trim()) : null;

  const commit = (value, move) => {
    if (done.current) return;
    done.current = true;
    onCommit(value, move);
  };
  const cancel = () => {
    if (done.current) return;
    done.current = true;
    onCancel();
  };
  const toggle = (opt) => {
    const k = opt.key;
    setDraft((d) => (draftKeys.has(k) ? d.filter((o) => String(keyOf(o)) !== k) : [...d, opt.obj]));
  };
  const pick = (opt) => (multiple ? toggle(opt) : commit(opt.obj, "down"));
  const highlighted = () => all.find((o) => `opt:${o.key}` === hl);

  return (
    <Popover open>
      <PopoverAnchor asChild><span className="absolute inset-0" /></PopoverAnchor>
      <PopoverContent align="start" style={{ width }} className="p-0"
                      onOpenAutoFocus={(e) => e.preventDefault()}
                      onEscapeKeyDown={(e) => { e.preventDefault(); cancel(); }}
                      onInteractOutside={(e) => { e.preventDefault(); if (multiple) commit(draft, null); else cancel(); }}>
        <Command shouldFilter={!onSearch} loop value={hl} onValueChange={setHl}
                 onKeyDown={(e) => {
                   e.stopPropagation();
                   if (e.key === "Tab") {
                     e.preventDefault();
                     const m = e.shiftKey ? "left" : "right";
                     if (multiple) commit(draft, m);
                     else { const o = highlighted(); if (o) commit(o.obj, m); else cancel(); }
                   } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && multiple) {
                     e.preventDefault();
                     commit(draft, "down");
                   }
                 }}>
          {header}
          <div className="border-b border-line p-2">
            <Command.Input autoFocus value={q} placeholder={placeholder} aria-label={placeholder}
                           onValueChange={(v) => { setQ(v); onSearch?.(v); }}
                           className="h-8 w-full rounded-[3px] border-2 border-focus bg-bg px-2 text-sm outline-none placeholder:text-fg-subtlest" />
          </div>
          <Command.List className="max-h-72 overflow-y-auto py-1">
            {loading && <Command.Loading><div className="px-3 py-2 text-sm text-fg-subtlest">Buscando…</div></Command.Loading>}
            <Command.Empty className="px-3 py-2 text-sm text-fg-subtlest">{emptyText}</Command.Empty>
            {all.map((o) => (
              <Command.Item key={o.key} value={`opt:${o.key}`} keywords={[o.label, o.description ?? ""]} onSelect={() => pick(o)}
                            className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm data-[selected=true]:bg-bg-hover">
                {o.icon}
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{o.label}</span>
                  {o.description && <span className="block truncate text-xs text-fg-subtlest">{o.description}</span>}
                </span>
                <Check size={14} className={cn("shrink-0 text-brand", !draftKeys.has(o.key) && "invisible")} />
              </Command.Item>
            ))}
            {createKey && (
              <Command.Item value={`create:${q}`} onSelect={() => { const o = createKey; toggle(o); setQ(""); onSearch?.(""); }}
                            className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm data-[selected=true]:bg-bg-hover">
                Crear «{createKey.label}»
              </Command.Item>
            )}
          </Command.List>
          {multiple && (
            <div className="flex items-center justify-between gap-2 border-t border-line px-2 py-1.5">
              <span className="text-xs text-fg-subtlest">Ctrl+Intro aplica · Esc cancela</span>
              <span className="flex gap-1">
                <Button size="sm" variant="subtle" onClick={cancel}>Cancelar</Button>
                <Button size="sm" variant="primary" onClick={() => commit(draft, null)}>Aplicar</Button>
              </span>
            </div>
          )}
        </Command>
      </PopoverContent>
    </Popover>
  );
}

const idOf = (o) => (o && typeof o === "object" ? o.id : o);

function UserOptions({ col, row, ctx, value, multiple, assignable, allowNone, onCommit, onCancel, asIds }) {
  const [q, setQ] = useState("");
  const users = useUsers(q, ctx.projectKey, assignable);
  const canAssignOthers = col.id !== "assignee" || row.permissions.includes("assign_issues");
  let list = users.data ?? [];
  if (!canAssignOthers) list = ctx.me ? [ctx.me] : [];
  const opts = list.map((u) => ({
    key: String(u.id), label: u.id === ctx.me?.id ? `${u.name} (tú)` : u.name, description: u.email,
    icon: <Avatar user={u} size="sm" />, obj: asIds ? u.id : u,
  }));
  if (allowNone && canAssignOthers && !q) opts.unshift({ key: NONE, label: col.id === "assignee" ? "Sin asignar" : "Ninguno", icon: <Avatar user={null} size="sm" />, obj: null });
  const selected = multiple ? (value ?? []) : [value ?? null];
  return (
    <CellPicker options={opts} multiple={multiple} keyOf={(o) => (o === null ? NONE : idOf(o))} selected={selected}
                labelOf={(o) => (asIds ? ctx.users?.[String(o)]?.name ?? `Usuario ${o}` : o?.name)}
                onSearch={canAssignOthers ? setQ : undefined} loading={users.isFetching} placeholder="Buscar personas"
                onCommit={onCommit} onCancel={onCancel} />
  );
}

function LabelOptions({ value, ctx, onCommit, onCancel }) {
  const [q, setQ] = useState("");
  const labels = useQuery({
    queryKey: ["labels", ctx.projectKey ?? "", q],
    queryFn: () => unwrap(api.GET("/api/v1/labels", { params: { query: { q, project: ctx.projectKey } } })),
  });
  const opts = (labels.data ?? []).map((l) => ({ key: l, label: l, obj: l }));
  const norm = (t) => t.replace(/\s+/g, "_").slice(0, 60);
  return (
    <CellPicker multiple options={opts} selected={value ?? []} keyOf={(l) => l} onSearch={setQ} loading={labels.isFetching}
                placeholder="Buscar o crear etiqueta" emptyText="Escribe para crear una etiqueta"
                creatable={(t) => ((labels.data ?? []).includes(norm(t)) || (value ?? []).includes(norm(t)) ? null : { key: norm(t), label: norm(t), obj: norm(t) })}
                onCommit={onCommit} onCancel={onCancel} />
  );
}

function ParentOptions({ row, ctx, value, onCommit, onCancel }) {
  const [q, setQ] = useState("");
  const level = row.type.level === -1 ? 0 : 1;
  const res = useQuery({
    queryKey: ["picker", q, ctx.projectKey, level, row.key],
    queryFn: () => unwrap(api.GET("/api/v1/issues/picker", { params: { query: { q, project: ctx.projectKey, level, exclude: row.key, limit: 20 } } })),
  });
  const opts = (res.data ?? []).map((i) => ({
    key: String(i.id), label: `${i.key} ${i.summary}`, icon: <IssueTypeIcon type={i.type} />,
    obj: { id: i.id, key: i.key, summary: i.summary, type: i.type },
  }));
  if (row.type.level === 0 && !q) opts.unshift({ key: NONE, label: "Sin principal", obj: null });
  return (
    <CellPicker options={opts} selected={[value ?? null]} keyOf={(o) => (o === null ? NONE : o.id)} onSearch={setQ}
                loading={res.isFetching} width={380} placeholder={level === 1 ? "Buscar épica" : "Buscar incidencia principal"}
                onCommit={onCommit} onCancel={onCancel} />
  );
}

function StatusEditor({ row, onCommit, onCancel }) {
  const transitions = useTransitions(row.key, true);
  const opts = (transitions.data ?? []).map((t) => ({
    key: String(t.id), label: t.name, description: t.name === t.to.name ? undefined : `→ ${t.to.name}`,
    icon: <Lozenge category={t.to.category}>{t.to.name}</Lozenge>, obj: t,
  }));
  // transitions with a screen, required fields, resolution or comment open the transition dialog
  return (
    <CellPicker options={opts} selected={[]} keyOf={(t) => t?.id} loading={transitions.isFetching} placeholder="Cambiar estado"
                emptyText={transitions.isFetching ? "Cargando…" : "No hay transiciones disponibles"}
                onCommit={(t, move) => (t ? onCommit({ transition: t }, move) : onCancel())} onCancel={onCancel} />
  );
}

/** Editor for one cell. `initialText`: the printable key that started editing, if any. */
export function CellEditor({ col, row, ctx, initialText, onCommit, onCancel }) {
  const value = col.value(row);
  const meta = ctx.meta;
  switch (col.editor) {
    case "text":
      return <InputEditor initial={value} initialText={initialText} maxLength={255} onCommit={onCommit} onCancel={onCancel}
                          parse={(t) => {
                            const s = t.trim();
                            if (col.kind === "text" && !s) throw new Error("El resumen es obligatorio");
                            return s || null;
                          }} />;
    case "number":
      return <InputEditor initial={value} initialText={initialText} align="right" onCommit={onCommit} onCancel={onCancel}
                          parse={(t) => {
                            const s = t.trim().replace(",", ".");
                            if (!s) return null;
                            const n = Number(s);
                            if (!Number.isFinite(n)) throw new Error("Introduce un número");
                            if (col.kind === "number" && n < 0) throw new Error("No puede ser negativo");
                            return n;
                          }} />;
    case "duration":
      return <InputEditor initial={value} initialText={initialText} format={fmtDuration} align="right" onCommit={onCommit} onCancel={onCancel}
                          parse={(t) => {
                            if (!t.trim()) return null;
                            const s = parseDuration(t);
                            if (s === null) throw new Error("Usa el formato 1w 2d 3h 30m");
                            return s;
                          }} />;
    case "date":
      return <InputEditor type="date" initial={value} onCommit={onCommit} onCancel={onCancel} parse={(t) => t || null} />;
    case "datetime":
      return <InputEditor type="datetime-local" initial={value} onCommit={onCommit} onCancel={onCancel} parse={(t) => t || null} />;
    case "textarea":
      return <TextareaEditor initial={value} initialText={initialText} onCommit={onCommit} onCancel={onCancel} />;
    case "status":
      return <StatusEditor row={row} onCommit={onCommit} onCancel={onCancel} />;
    case "picker":
      break;
    default:
      return null;
  }
  const common = { onCommit, onCancel };
  if (col.kind === "custom") {
    const f = col.customField;
    if (f.kind === "user" || f.kind === "multiuser") {
      return <UserOptions col={col} row={row} ctx={ctx} value={value} multiple={f.kind === "multiuser"} allowNone asIds {...common} />;
    }
    if (f.kind === "labels") return <LabelOptions value={value} ctx={ctx} {...common} />;
    const multiple = f.kind === "multiselect" || f.kind === "checkbox";
    const sel = multiple ? (value ?? []) : value === null || value === undefined ? [null] : [value];
    const opts = (f.options ?? []).filter((o) => !o.deleted || sel.includes(o.id)).map((o) => ({ key: String(o.id), label: o.value, obj: o.id }));
    if (!multiple) opts.unshift({ key: NONE, label: "Ninguno", obj: null });
    return <CellPicker options={opts} multiple={multiple} selected={sel} keyOf={(v) => (v === null ? NONE : v)} {...common} />;
  }
  switch (col.kind) {
    case "user":
      return <UserOptions col={col} row={row} ctx={ctx} value={value} assignable={col.id === "assignee"} allowNone={col.id === "assignee"} {...common} />;
    case "labels":
      return <LabelOptions value={value} ctx={ctx} {...common} />;
    case "parent":
      return <ParentOptions row={row} ctx={ctx} value={value} {...common} />;
    case "type": {
      const opts = meta.issue_types.filter((t) => t.level === row.type.level)
        .map((t) => ({ key: String(t.id), label: t.name, icon: <IssueTypeIcon type={t} />, obj: t }));
      return <CellPicker options={opts} selected={[value]} keyOf={(t) => t.id} width={240} placeholder="Tipo de incidencia" {...common} />;
    }
    case "priority": {
      const opts = meta.priorities.map((p) => ({ key: String(p.id), label: p.name, icon: <PriorityIcon priority={p} />, obj: p }));
      return <CellPicker options={opts} selected={[value]} keyOf={(p) => p.id} width={240} placeholder="Prioridad" {...common} />;
    }
    case "components": {
      const opts = meta.components.map((c) => ({ key: String(c.id), label: c.name, description: c.description, obj: { id: c.id, name: c.name } }));
      return <CellPicker multiple options={opts} selected={value ?? []} keyOf={(c) => c.id} placeholder="Componentes" {...common} />;
    }
    case "versions": {
      const sel = new Set((value ?? []).map((v) => v.id));
      const opts = meta.versions.filter((v) => v.status !== "archived" || sel.has(v.id))
        .map((v) => ({ key: String(v.id), label: v.name, description: v.release_date ?? undefined, obj: { id: v.id, name: v.name } }));
      return <CellPicker multiple options={opts} selected={value ?? []} keyOf={(v) => v.id} placeholder="Versiones" {...common} />;
    }
    case "sprint": {
      const opts = [{ key: NONE, label: "Ninguno (backlog)", obj: null },
        ...ctx.sprints.map((s) => ({ key: String(s.id), label: s.name, description: s.stateLabel, obj: { id: s.id, name: s.name, state: s.state } }))];
      return <CellPicker options={opts} selected={[value ?? null]} keyOf={(s) => (s === null ? NONE : s.id)} placeholder="Sprint" {...common} />;
    }
    case "team": {
      const opts = [{ key: NONE, label: "Sin equipo", obj: null },
        ...(ctx.teams ?? []).map((t) => ({ key: String(t.id), label: t.name, obj: { id: t.id, name: t.name } }))];
      return <CellPicker options={opts} selected={[value ?? null]} keyOf={(t) => (t === null ? NONE : t.id)} placeholder="Equipo" {...common} />;
    }
    default:
      return null;
  }
}
