/*
 * Screens and field configuration resolved by the backend (company-managed, like Jira):
 * GET /projects/{key}/field-rules (contract [S 17:45] in FASE4) — the frontend computes nothing,
 * it only adapts that payload to what the forms render:
 *   Screen = {id, name, tabs: [{id, name, fields: [Field]}], resolved}
 *   Field  = {key, label, required, description, custom?}
 * Hidden fields and fields that don't apply to the type never come in a screen. `issue_type`
 * and `status` are rendered by their own controls, so they are left out of the tabs.
 * When the server has no rules (older backend) the form falls back to every field the
 * renderer supports, with the custom fields' own `required` flag.
 */

import { canRender, cfIdOf, cfKey } from "./fields";

const OWN_CONTROL = new Set(["issue_type", "status"]);

export const typeRules = (fr, typeId) => fr?.by_type?.[String(typeId)] ?? null;

/** Custom field object (kind, options…) for a key, from the project meta or the catalog. */
function customOf(key, meta, entry) {
  const id = cfIdOf(key);
  if (id === null) return undefined;
  const c = meta?.custom_fields?.find((x) => x.id === id);
  if (c) return c;
  if (!entry) return undefined;
  return { id, name: entry.label, kind: entry.kind, options: entry.options ?? [], issue_type_ids: [], description: entry.description ?? "" };
}

/** Every known field key → {key, label, kind, locked, custom?}. */
export function fieldCatalog(fr, meta, appMeta) {
  const out = new Map();
  for (const f of appMeta?.system_fields ?? []) out.set(f.value, { key: f.value, label: f.label, kind: f.kind, locked: !!f.locked });
  for (const f of appMeta?.issue_fields ?? []) if (!out.has(f.value)) out.set(f.value, { key: f.value, label: f.label });
  for (const f of fr?.fields ?? []) out.set(f.key, { key: f.key, label: f.label, kind: f.kind, locked: !!f.locked, entry: f });
  for (const c of meta?.custom_fields ?? []) {
    const k = cfKey(c.id);
    out.set(k, { ...(out.get(k) ?? {}), key: k, label: c.name, kind: c.kind });
  }
  for (const [k, v] of out) if (cfIdOf(k) !== null) v.custom = customOf(k, meta, v.entry);
  return out;
}

export function fieldLabel(catalog, key) {
  return catalog.get(key)?.label ?? key;
}

/** Field configuration of a type: Map key → {required, hidden, description}. */
export function fieldConfig(fr, meta, typeId) {
  const out = new Map();
  const tr = typeRules(fr, typeId);
  if (tr?.config) {
    for (const [k, r] of Object.entries(tr.config)) out.set(k, { required: !!r.required, hidden: !!r.hidden, description: r.description ?? "" });
  } else {
    // older backend: custom fields carry their own required/description
    for (const c of meta?.custom_fields ?? []) out.set(cfKey(c.id), { required: !!c.required, hidden: false, description: c.description ?? "" });
    out.set("summary", { required: true, hidden: false, description: "" });
  }
  return out;
}

function appliesToType(meta, key, typeId) {
  const id = cfIdOf(key);
  if (id === null) return true;
  const c = meta?.custom_fields?.find((x) => x.id === id);
  return !c || !c.issue_type_ids?.length || c.issue_type_ids.includes(typeId);
}

/** Normalize a server screen (tabs of `{key, required, description}`) with labels. */
export function normalizeScreen(raw, { catalog, config, meta, typeId, resolved = true }) {
  if (!raw) return null;
  const rawTabs = raw.tabs?.length ? raw.tabs : [{ id: "main", name: "", fields: (raw.fields ?? []).map((k) => ({ key: k })) }];
  const tabs = rawTabs.map((t, i) => ({
    id: t.id ?? i, name: t.name ?? "",
    fields: (t.fields ?? []).map((f) => (typeof f === "string" ? { key: f } : { ...f, key: f.key ?? f.field }))
      .filter((f) => canRender(f.key) && !OWN_CONTROL.has(f.key))
      .filter((f) => !config.get(f.key)?.hidden && appliesToType(meta, f.key, typeId))
      .map((f) => {
        const r = config.get(f.key) ?? {};
        const c = catalog.get(f.key);
        return {
          key: f.key, label: c?.label ?? f.label ?? f.key, custom: c?.custom,
          required: f.required ?? !!r.required, description: f.description ?? r.description ?? "",
          locked: !!c?.locked,
        };
      }),
  }));
  return { id: raw.id ?? null, name: raw.name ?? "", tabs, resolved };
}

const FALLBACK_ORDER = [
  "summary", "description", "assignee", "parent", "labels", "sprint", "story_points", "reporter",
  "priority", "due_date", "start_date", "components", "fix_versions", "affects_versions", "team",
  "original_estimate",
];

/** Screen used when the server sends none (older backend): today's fields, in today's order. */
function fallbackScreen({ catalog, config, meta, typeId, type }) {
  const keys = FALLBACK_ORDER.filter((k) => catalog.has(k))
    .filter((k) => k !== "affects_versions" || type?.has_affects_versions)
    .filter((k) => !(k === "story_points" && type?.level === 1));
  const custom = (meta?.custom_fields ?? []).map((c) => cfKey(c.id));
  const fields = [...keys, ...custom].map((key) => ({ key }));
  return normalizeScreen({ id: null, name: "", tabs: [{ id: "main", name: "", fields }] }, { catalog, config, meta, typeId, resolved: false });
}

function ctxOf(fr, meta, appMeta, typeId) {
  return {
    catalog: fieldCatalog(fr, meta, appMeta), config: fieldConfig(fr, meta, typeId), meta, typeId,
    type: meta?.issue_types?.find((t) => t.id === typeId),
  };
}

/** Resolved screen of `op` ("create" | "edit" | "view") for an issue type. */
export function screenFor(fr, meta, appMeta, typeId, op) {
  const ctx = ctxOf(fr, meta, appMeta, typeId);
  const raw = typeRules(fr, typeId)?.screens?.[op];
  const s = raw ? normalizeScreen(raw, ctx) : fallbackScreen(ctx);
  // summary is always required; a sub-task always needs its parent
  for (const t of s.tabs) for (const f of t.fields) if (f.key === "summary" || (f.key === "parent" && ctx.type?.level === -1)) f.required = true;
  return s;
}

/** Keys on the edit screen of a type, issue_type included (null = no rules: all editable). */
export function editKeys(fr, typeId) {
  const s = typeRules(fr, typeId)?.screens?.edit;
  if (!s) return null;
  return new Set(s.fields ?? (s.tabs ?? []).flatMap((t) => t.fields.map((f) => f.key ?? f)));
}

/** Required keys of a type's field configuration (summary always). */
export function requiredKeys(fr, meta, typeId) {
  const tr = typeRules(fr, typeId);
  if (tr?.required) return new Set(["summary", ...tr.required]);
  const out = new Set(["summary"]);
  for (const [k, r] of fieldConfig(fr, meta, typeId)) if (r.required && !r.hidden) out.add(k);
  return out;
}

/** Keys required at creation (= required ∩ create screen), as the backend enforces them. */
export function createRequired(fr, meta, typeId) {
  const tr = typeRules(fr, typeId);
  if (tr?.create_required) return new Set(tr.create_required);
  return requiredKeys(fr, meta, typeId);
}

export function hiddenKeys(fr, typeId) {
  return new Set(typeRules(fr, typeId)?.hidden ?? []);
}

export function allKeys(screen) {
  return new Set((screen?.tabs ?? []).flatMap((t) => t.fields.map((f) => f.key)));
}

export function allFields(screen) {
  return (screen?.tabs ?? []).flatMap((t) => t.fields);
}

/**
 * True when moving through `t` asks for input: a transition screen, a resolution or a
 * comment. A validator («campos obligatorios») alone doesn't open a dialog: the backend only
 * accepts values for fields ON the transition screen, so those must already be filled in; if
 * not, the transition answers 422 `fields` and the runner shows the dialog with the reason.
 */
export function transitionNeedsInput(t) {
  return !!(t && (t.screen || t.require_resolution || t.require_comment));
}

/**
 * Screen of a transition (as GET /issues/{key}/transitions sends it) for an issue type: the
 * transition screen (its fields are already marked required by configuration or validator),
 * plus «Resolución» when it is asked for, plus «Comentario» (required when the transition says
 * so), like Jira's transition dialogs. `blocked` = validator fields that are NOT on the screen:
 * they can't be filled in here, the issue must already have a value.
 */
export function transitionScreen(fr, meta, appMeta, typeId, t) {
  const ctx = ctxOf(fr, meta, appMeta, typeId);
  const required = new Set((t.required_fields ?? []).map((f) => (typeof f === "string" ? f : f.key ?? f.field)));
  const base = t.screen ? normalizeScreen(t.screen, ctx) : { id: null, name: "", tabs: [{ id: "main", name: "", fields: [] }] };
  if (!base.tabs.length) base.tabs = [{ id: "main", name: "", fields: [] }];
  const tabs = base.tabs.map((tab) => ({ ...tab, fields: tab.fields.map((f) => (required.has(f.key) ? { ...f, required: true } : f)) }));
  const present = new Set(tabs.flatMap((tab) => tab.fields.map((f) => f.key)));
  const extra = t.require_resolution && !present.has("resolution")
    ? normalizeScreen({ tabs: [{ fields: [{ key: "resolution", required: true }] }] }, ctx).tabs[0].fields.map((f) => ({ ...f, required: true }))
    : [];
  const comment = { key: "comment", label: ctx.catalog.get("comment")?.label ?? "Comentario", required: !!t.require_comment, description: "" };
  tabs[0] = { ...tabs[0], fields: [...tabs[0].fields, ...extra] };
  const last = tabs.length - 1;
  tabs[last] = { ...tabs[last], fields: [...tabs[last].fields.filter((f) => f.key !== "comment"), comment] };
  for (const tab of tabs) for (const f of tab.fields) if (f.key === "resolution") f.label = ctx.catalog.get("resolution")?.label ?? "Resolución";
  const blocked = [...required].filter((k) => !present.has(k)).map((k) => ({ key: k, label: ctx.catalog.get(k)?.label ?? k }));
  return { id: base.id, name: base.name, tabs, blocked, resolved: true };
}

/** Values the backend fills in on its own when creating (default priority, reporter = creator). */
const SERVER_DEFAULTS = new Set(["summary", "issue_type", "priority", "reporter"]);

/**
 * Required fields a quick-create (summary only) can't satisfy: when not empty, open the full
 * «Crear incidencia» dialog with what was typed, like Jira. `provided` = keys the inline form
 * sends (e.g. sprint, status context).
 */
export function quickCreateMissing(fr, meta, typeId, provided = []) {
  const skip = new Set([...SERVER_DEFAULTS, ...provided]);
  return [...createRequired(fr, meta, typeId)].filter((k) => !skip.has(k));
}
