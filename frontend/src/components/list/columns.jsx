"use client";

import { Flag } from "lucide-react";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { Avatar, Lozenge } from "@/components/ui/primitives";
import { api, unwrap } from "@/lib/api/client";
import { isEmptyValue } from "@/lib/fields";
import { editKeys, hiddenKeys, requiredKeys } from "@/lib/screens";
import { cn, fmtDate, fmtDateTime, fmtDuration, fmtPoints, parseDuration } from "@/lib/utils";

/*
 * Column behaviour by `kind` (the catalogue itself, with labels, PATCH fields and JQL sort
 * names, comes from GET /projects/{key}/list/meta). Each column knows how to:
 *   value(row)            raw value (what editors receive and the internal clipboard keeps)
 *   text(row, ctx)        plain text (copy to the system clipboard)
 *   patch(value)          PATCH /issues/{key} body
 *   apply(row, value)     optimistic row
 *   parse(text, ctx)      Promise<value> from pasted text (throws Error with a message)
 *   editor                which inline editor to open
 *   clear                 value written by Delete/Backspace (undefined = not clearable)
 */

const EMPTY = <span className="text-fg-subtlest">—</span>;
const lower = (s) => String(s ?? "").trim().toLowerCase();

function matchName(list, text, what) {
  const t = lower(text);
  const hit = list.find((x) => lower(x.name) === t);
  if (!hit) throw new Error(`«${text}» no es ${what} válido`);
  return hit;
}

function splitList(text) {
  return String(text).split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
}

function parseDate(text) {
  const t = String(text).trim();
  if (!t) return null;
  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  m = t.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/);
  if (m) return `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  throw new Error(`«${t}» no es una fecha (usa AAAA-MM-DD o DD/MM/AAAA)`);
}

function parseNumber(text) {
  const t = String(text).trim().replace(",", ".");
  if (!t) return null;
  const n = Number(t);
  if (!Number.isFinite(n)) throw new Error(`«${text}» no es un número`);
  return n;
}

async function findUser(text, projectKey, assignable) {
  const t = lower(text);
  if (!t || t === "sin asignar" || t === "ninguno") return null;
  const users = await unwrap(api.GET("/api/v1/users", { params: { query: { q: text.trim(), project: projectKey, assignable } } }));
  const hit = users.find((u) => lower(u.name) === t || lower(u.email) === t);
  if (!hit) throw new Error(`No se encontró a «${text}»`);
  return hit;
}

function userCell(u, none = "Sin asignar") {
  return u ? (
    <span className="flex min-w-0 items-center gap-1.5"><Avatar user={u} size="xs" /><span className="truncate">{u.name}</span></span>
  ) : <span className="text-fg-subtlest">{none}</span>;
}

function namesCell(list) {
  return list?.length ? <span className="truncate">{list.map((x) => x.name).join(", ")}</span> : EMPTY;
}

/** Display of a custom field value (users resolved through the page's `users` map). */
function customText(field, value, users) {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return "";
  const opts = new Map((field?.options ?? []).map((o) => [o.id, o.value]));
  switch (field?.kind) {
    case "select": return opts.get(value) ?? String(value);
    case "multiselect":
    case "checkbox": return value.map((v) => opts.get(v) ?? v).join(", ");
    case "user": return users?.[String(value)]?.name ?? `Usuario ${value}`;
    case "multiuser": return value.map((v) => users?.[String(v)]?.name ?? `Usuario ${v}`).join(", ");
    case "labels": return value.join(" ");
    case "date": return fmtDate(value);
    case "datetime": return fmtDateTime(value);
    default: return String(value);
  }
}

function customDefs(col, field) {
  const id = String(col.custom_field_id);
  const kind = field?.kind ?? col.custom_kind;
  const base = {
    value: (r) => r.custom_fields?.[id] ?? null,
    patch: (v) => ({ custom_fields: { [id]: v === undefined ? null : v } }),
    apply: (r, v) => ({ ...r, custom_fields: { ...r.custom_fields, [id]: v } }),
    text: (r, ctx) => customText(field, r.custom_fields?.[id], ctx.users),
    applies: (r) => !field?.issue_type_ids?.length || field.issue_type_ids.includes(r.type.id),
    clear: null,
  };
  const opts = (field?.options ?? []).filter((o) => !o.deleted);
  const byValue = (t) => {
    const hit = opts.find((o) => lower(o.value) === lower(t));
    if (!hit) throw new Error(`«${t}» no es una opción de ${field?.name ?? "este campo"}`);
    return hit.id;
  };
  const display = (r, ctx) => {
    const v = r.custom_fields?.[id];
    if (kind === "user") return v ? userCell(ctx.users?.[String(v)] ?? { id: v, name: `Usuario ${v}` }, "") : EMPTY;
    if (kind === "url" && v && /^https?:\/\//i.test(String(v))) {
      return <a href={String(v)} target="_blank" rel="noopener noreferrer nofollow" onClick={(e) => e.stopPropagation()} className="truncate text-link hover:underline">{String(v)}</a>;
    }
    const t = customText(field, v, ctx.users);
    return t ? <span className={cn("truncate", kind === "number" && "ml-auto tabular-nums")}>{t}</span> : EMPTY;
  };
  switch (kind) {
    case "number":
      return { ...base, display, editor: "number", align: "right", parse: async (t) => parseNumber(t) };
    case "date":
      return { ...base, display, editor: "date", parse: async (t) => parseDate(t) };
    case "datetime":
      return { ...base, display, editor: "datetime", parse: async (t) => (String(t).trim() || null) };
    case "textarea":
      return { ...base, display, editor: "textarea", parse: async (t) => String(t) || null };
    case "select":
      return { ...base, display, editor: "picker", parse: async (t) => (String(t).trim() ? byValue(t) : null) };
    case "multiselect":
    case "checkbox":
      return { ...base, display, editor: "picker", multiple: true, parse: async (t) => splitList(t).map(byValue) };
    case "user":
      return { ...base, display, editor: "picker", parse: async (t, ctx) => (await findUser(t, ctx.projectKey, false))?.id ?? null };
    case "multiuser":
      return {
        ...base, display, editor: "picker", multiple: true,
        parse: async (t, ctx) => Promise.all(splitList(t).map((x) => findUser(x, ctx.projectKey, false))).then((us) => us.filter(Boolean).map((u) => u.id)),
      };
    case "labels":
      return { ...base, display, editor: "picker", multiple: true, parse: async (t) => String(t).split(/[\s,]+/).filter(Boolean) };
    default: // text, url
      return { ...base, display, editor: "text", parse: async (t) => String(t).slice(0, 255) || null };
  }
}

function standardDefs(col) {
  const f = col.id;
  switch (col.kind) {
    case "key":
      return {
        value: (r) => r.key, text: (r) => r.key,
        display: (r) => <span className={cn("truncate text-link", r.status.category === "done" && "line-through")}>{r.key}</span>,
      };
    case "type":
      return {
        value: (r) => r.type, text: (r) => r.type.name,
        display: (r) => <span className="flex min-w-0 items-center gap-1.5"><IssueTypeIcon type={r.type} /><span className="truncate text-fg-subtle">{r.type.name}</span></span>,
        editor: "picker", patch: (v) => ({ issue_type: v.id }), apply: (r, v) => ({ ...r, type: v }),
        parse: async (t, ctx) => matchName(ctx.meta.issue_types, t, "un tipo"),
      };
    case "text":
      return {
        value: (r) => r[f], text: (r) => r[f] ?? "", display: (r) => <span className="truncate">{r[f]}</span>,
        editor: "text", patch: (v) => ({ [f]: v }), apply: (r, v) => ({ ...r, [f]: v }),
        parse: async (t) => {
          const s = String(t).trim();
          if (!s) throw new Error("El resumen es obligatorio");
          return s.slice(0, 255);
        },
      };
    case "status":
      return {
        value: (r) => r.status, text: (r) => r.status.name,
        display: (r) => <Lozenge category={r.status.category}>{r.status.name}</Lozenge>,
        editor: "status", apply: (r, v) => ({ ...r, status: v }),
        parse: async (t, ctx) => matchName(ctx.meta.statuses, t, "un estado"),
      };
    case "user":
      return {
        value: (r) => r[f], text: (r) => r[f]?.name ?? "",
        display: (r) => userCell(r[f], f === "assignee" ? "Sin asignar" : "—"),
        editor: "picker", patch: (v) => ({ [f]: v?.id ?? null }), apply: (r, v) => ({ ...r, [f]: v }),
        clear: f === "assignee" ? null : undefined,
        parse: async (t, ctx) => findUser(t, ctx.projectKey, f === "assignee"),
      };
    case "priority":
      return {
        value: (r) => r.priority, text: (r) => r.priority?.name ?? "",
        display: (r) => <span className="flex min-w-0 items-center gap-1.5"><PriorityIcon priority={r.priority} /><span className="truncate">{r.priority?.name}</span></span>,
        editor: "picker", patch: (v) => ({ priority: v.id }), apply: (r, v) => ({ ...r, priority: v }),
        parse: async (t, ctx) => matchName(ctx.meta.priorities, t, "una prioridad"),
      };
    case "labels":
      return {
        value: (r) => r.labels, text: (r) => r.labels.join(" "),
        display: (r) => (r.labels.length ? (
          <span className="flex min-w-0 gap-1 overflow-hidden">
            {r.labels.map((l) => <span key={l} className="shrink-0 rounded-[3px] bg-bg-sunken px-1 text-xs text-fg-subtle">{l}</span>)}
          </span>
        ) : EMPTY),
        editor: "picker", multiple: true, patch: (v) => ({ labels: v }), apply: (r, v) => ({ ...r, labels: v }),
        clear: [], parse: async (t) => String(t).split(/[\s,]+/).filter(Boolean),
      };
    case "components":
    case "versions":
      return {
        value: (r) => r[f], text: (r) => r[f].map((x) => x.name).join(", "), display: (r) => namesCell(r[f]),
        editor: "picker", multiple: true, patch: (v) => ({ [f]: v.map((x) => x.id) }), apply: (r, v) => ({ ...r, [f]: v }),
        clear: [],
        parse: async (t, ctx) => {
          const list = col.kind === "components" ? ctx.meta.components : ctx.meta.versions;
          return splitList(t).map((x) => matchName(list, x, col.kind === "components" ? "un componente" : "una versión"))
            .map((x) => ({ id: x.id, name: x.name }));
        },
        applies: f === "affects_versions" ? (r) => !!r.type.has_affects_versions : undefined,
      };
    case "sprint":
      return {
        value: (r) => r.sprint, text: (r) => r.sprint?.name ?? "", display: (r) => (r.sprint ? <span className="truncate">{r.sprint.name}</span> : EMPTY),
        editor: "picker", patch: (v) => ({ sprint: v?.id ?? null }), apply: (r, v) => ({ ...r, sprint: v }),
        clear: null, locked: (r) => (r.type.level === -1 ? "Las subtareas siguen el sprint de su principal" : null),
        parse: async (t, ctx) => {
          if (!String(t).trim()) return null;
          const s = matchName(ctx.sprints, t, "un sprint abierto");
          return { id: s.id, name: s.name, state: s.state };
        },
      };
    case "parent":
      return {
        value: (r) => r.parent, text: (r) => r.parent?.key ?? "",
        display: (r) => (r.parent ? (
          <span className="flex min-w-0 items-center gap-1.5"><IssueTypeIcon type={r.parent.type} size={14} /><span className="shrink-0 text-fg-subtle">{r.parent.key}</span><span className="truncate">{r.parent.summary}</span></span>
        ) : EMPTY),
        editor: "picker", patch: (v) => ({ parent: v?.id ?? null }), apply: (r, v) => ({ ...r, parent: v }),
        clear: null,
        locked: (r) => (r.type.level === 1 ? "Una épica no tiene principal" : null),
        parse: async (t, ctx) => {
          const key = String(t).trim().toUpperCase();
          if (!key) return null;
          const items = await unwrap(api.GET("/api/v1/issues/picker", { params: { query: { q: key, project: ctx.projectKey, limit: 5 } } }));
          const hit = items.find((i) => i.key === key);
          if (!hit) throw new Error(`No se encontró ${key}`);
          return { id: hit.id, key: hit.key, summary: hit.summary, type: hit.type };
        },
      };
    case "number":
      return {
        value: (r) => (r[f] === null || r[f] === undefined ? null : Number(r[f])), text: (r) => fmtPoints(r[f]) ?? "",
        display: (r) => <span className="ml-auto tabular-nums">{fmtPoints(r[f]) ?? ""}</span>, align: "right",
        editor: "number", patch: (v) => ({ [f]: v }), apply: (r, v) => ({ ...r, [f]: v }), clear: null,
        parse: async (t) => {
          const n = parseNumber(t);
          if (n !== null && n < 0) throw new Error("No puede ser negativo");
          return n;
        },
      };
    case "duration":
      return {
        value: (r) => r[f], text: (r) => (r[f] ? fmtDuration(r[f]) : ""),
        display: (r) => <span className="ml-auto tabular-nums">{r[f] ? fmtDuration(r[f]) : ""}</span>, align: "right",
        editor: col.field ? "duration" : undefined, patch: (v) => ({ [f]: v }), apply: (r, v) => ({ ...r, [f]: v }), clear: null,
        parse: async (t) => {
          if (!String(t).trim()) return null;
          const s = parseDuration(String(t));
          if (s === null) throw new Error(`«${t}» no es una duración (p. ej. 1d 4h)`);
          return s;
        },
      };
    case "date":
      return {
        value: (r) => r[f], text: (r) => r[f] ?? "",
        display: (r, ctx) => {
          const overdue = f === "due_date" && r[f] && r.status.category !== "done" && r[f] < ctx.today;
          return r[f] ? <span className={cn("truncate", overdue && "font-medium text-danger")}>{fmtDate(r[f])}</span> : EMPTY;
        },
        editor: "date", patch: (v) => ({ [f]: v }), apply: (r, v) => ({ ...r, [f]: v }), clear: null,
        parse: async (t) => parseDate(t),
      };
    case "datetime": {
      const src = { created: "created_at", updated: "updated_at", resolved: "resolved_at" }[f] ?? f;
      return {
        value: (r) => r[src], text: (r) => r[src] ?? "",
        display: (r) => (r[src] ? <span className="truncate text-fg-subtle" title={fmtDateTime(r[src])}>{fmtDate(r[src], "d MMM yyyy")}</span> : EMPTY),
      };
    }
    case "bool":
      return {
        value: (r) => !!r[f], text: (r) => (r[f] ? "Sí" : ""),
        display: (r) => (r[f] ? <span className="flex items-center gap-1 text-danger"><Flag size={14} className="fill-current" />Sí</span> : EMPTY),
        editor: "toggle", patch: (v) => ({ [f]: !!v }), apply: (r, v) => ({ ...r, [f]: !!v }), clear: false,
        parse: async (t) => ["sí", "si", "true", "1", "x", "yes", "verdadero"].includes(lower(t)),
      };
    case "resolution":
      return {
        value: (r) => r.resolution, text: (r) => r.resolution?.name ?? "",
        display: (r) => (r.resolution ? <span className="truncate">{r.resolution.name}</span> : <span className="text-fg-subtlest">Sin resolver</span>),
      };
    case "team":
      return {
        value: (r) => r.team, text: (r) => r.team?.name ?? "", display: (r) => (r.team ? <span className="truncate">{r.team.name}</span> : EMPTY),
        editor: col.field ? "picker" : undefined, patch: (v) => ({ team: v?.id ?? null }), apply: (r, v) => ({ ...r, team: v }), clear: null,
        parse: async (t, ctx) => {
          if (!String(t).trim()) return null;
          const tm = matchName(ctx.teams ?? [], t, "un equipo");
          return { id: tm.id, name: tm.name };
        },
      };
    default:
      return { value: () => null, text: () => "", display: () => EMPTY };
  }
}

/** Catalogue entries (from the server) + behaviour, keyed by id. */
export function buildColumns(catalog, projectMeta) {
  const fields = new Map((projectMeta?.custom_fields ?? []).map((cf) => [cf.id, cf]));
  const out = new Map();
  for (const col of catalog ?? []) {
    const field = col.kind === "custom" ? fields.get(col.custom_field_id) : null;
    if (col.kind === "custom" && !field) continue; // not applicable to this project anymore
    const defs = col.kind === "custom" ? customDefs(col, field) : standardDefs(col);
    out.set(col.id, { ...col, ...defs, customField: field, editor: col.field || col.kind === "status" ? defs.editor : undefined });
  }
  return out;
}

/** Issue field key of a column (PATCH name or `cf:<id>`; null for status / read-only). */
export function fieldKeyOf(col) {
  if (col.kind === "custom") return `cf:${col.custom_field_id}`;
  if (col.kind === "status") return null;
  return col.field ?? null;
}

/** Why a cell can't be edited (null = editable). */
export function lockReason(col, row, ctx) {
  if (!col.editor) return "Campo de solo lectura";
  if (row.is_archived) return "Incidencia archivada (solo lectura)";
  const perms = row.permissions ?? [];
  if (col.applies && !col.applies(row)) return "No aplica a este tipo de incidencia";
  if (col.locked) {
    const why = col.locked(row);
    if (why) return why;
  }
  // screens: only fields on the edit screen of the row's type («Asignar» only needs it visible)
  const key = fieldKeyOf(col);
  if (key && ctx.fieldRules) {
    if (hiddenKeys(ctx.fieldRules, row.type.id).has(key)) return `«${col.label}» está oculto para ${row.type.name}`;
    const edit = editKeys(ctx.fieldRules, row.type.id);
    if (key !== "assignee" && edit && !edit.has(key)) return `«${col.label}» no está en la pantalla de edición de ${row.type.name}`;
  }
  if (col.kind === "status") return perms.includes("transition_issues") ? null : "No tienes permiso para cambiar el estado";
  if (col.id === "assignee") {
    return perms.includes("assign_issues") || perms.includes("edit_issues") ? null : "No tienes permiso para asignar";
  }
  if (col.kind === "team" && !ctx.teams) return "Equipos no disponibles";
  return perms.includes("edit_issues") ? null : "No tienes permiso para editar";
}

/** Why `value` can't be written to this cell: a required field of the row's type can't be emptied. */
export function emptyReason(col, row, ctx, value) {
  const key = fieldKeyOf(col);
  if (!key || !isEmptyValue(value === undefined ? null : value)) return null;
  if (key === "summary" || requiredKeys(ctx.fieldRules, ctx.meta, row.type.id).has(key)) {
    return `«${col.label}» es obligatorio en ${row.type.name}: no se puede vaciar`;
  }
  return null;
}

/** Raw values can be pasted as-is between columns that share the same value shape. */
export function shapeOf(col) {
  if (col.kind === "custom") return `cf:${col.custom_field_id}`;
  if (col.kind === "user") return "user";
  if (col.kind === "versions") return "versions";
  if (col.kind === "date") return "date";
  if (col.kind === "duration") return "duration";
  return col.id;
}
