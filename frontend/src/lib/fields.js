/*
 * Issue fields by key. Keys are the PATCH /issues/{key} names (`summary`, `assignee`,
 * `fix_versions`…) plus `cf:<id>` for custom fields. Form values use one shape per key:
 *   ids for single references (priority, assignee, reporter, sprint, team, resolution),
 *   arrays of ids for components / versions, the issue ref object for `parent`,
 *   strings for dates (AAAA-MM-DD), seconds for estimates, the raw value for custom fields.
 * Which fields exist, their labels and rules come from the backend (meta / screens); this
 * module only knows how to move values between the API and the forms.
 */

import { ApiError } from "./api/client";

export const cfKey = (id) => `cf:${id}`;
export const cfIdOf = (key) => (typeof key === "string" && key.startsWith("cf:") ? Number(key.slice(3)) : null);
export const isCustomKey = (key) => cfIdOf(key) !== null;

/** Keys the generic renderer can edit (anything else is shown read-only). */
export const EDITABLE_KEYS = new Set([
  "summary", "description", "priority", "assignee", "reporter", "parent", "labels", "components",
  "fix_versions", "affects_versions", "sprint", "team", "story_points", "original_estimate",
  "remaining_estimate", "start_date", "due_date", "flagged", "resolution", "comment",
]);

export function canRender(key) {
  return EDITABLE_KEYS.has(key) || isCustomKey(key);
}

/** Value of `key` in an IssueOut (or a Lista row, which has the same shape for these keys). */
export function issueValue(issue, key) {
  if (!issue) return undefined;
  const id = cfIdOf(key);
  if (id !== null) return issue.custom_fields?.[String(id)] ?? null;
  switch (key) {
    case "priority":
    case "assignee":
    case "reporter":
    case "sprint":
    case "team":
    case "resolution":
    case "issue_type":
    case "status":
      return issue[key === "issue_type" ? "type" : key]?.id ?? null;
    case "components":
    case "fix_versions":
    case "affects_versions":
      return (issue[key] ?? []).map((x) => x.id);
    case "parent":
      return issue.parent ?? null;
    case "story_points":
      return issue.story_points === null || issue.story_points === undefined ? null : Number(issue.story_points);
    case "labels":
      return issue.labels ?? [];
    case "flagged":
      return !!issue.flagged;
    default:
      return issue[key] ?? null;
  }
}

export function isEmptyValue(v) {
  if (v === null || v === undefined) return true;
  if (typeof v === "string") return !v.trim();
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object" && v.type === "doc") {
    // TipTap document: empty when it has no text, mentions or other leaves
    const walk = (n) => (n.text?.trim() ? true : n.type === "mention" || n.type === "image" ? true : (n.content ?? []).some(walk));
    return !walk(v);
  }
  return false;
}

const wire = (key, v) => {
  if (key === "parent") return v?.id ?? null;
  if (key === "story_points") return v === null || v === undefined || v === "" ? null : String(v);
  if (typeof v === "string" && ["start_date", "due_date"].includes(key)) return v || null;
  return v === undefined ? null : v;
};

/** PATCH /issues/{key} body for a set of `{key: value}`. */
export function toPatch(values) {
  const out = {};
  for (const [key, v] of Object.entries(values)) {
    const id = cfIdOf(key);
    if (id !== null) {
      out.custom_fields = { ...(out.custom_fields ?? {}), [String(id)]: v === undefined ? null : v };
    } else if (key !== "comment" && key !== "resolution") {
      out[key] = wire(key, v);
    }
  }
  return out;
}

const CREATE_NAMES = {
  priority: "priority_id", assignee: "assignee_id", reporter: "reporter_id", parent: "parent_id",
  components: "component_ids", fix_versions: "fix_version_ids", affects_versions: "affects_version_ids",
  sprint: "sprint_id", team: "team_id",
};

/** POST /issues body fields for `{key: value}` (only the given keys). */
export function toCreate(values) {
  const out = {};
  for (const [key, v] of Object.entries(values)) {
    if (v === undefined) continue;
    const id = cfIdOf(key);
    if (id !== null) {
      if (!isEmptyValue(v)) out.custom_fields = { ...(out.custom_fields ?? {}), [String(id)]: v };
    } else if (key !== "comment" && key !== "resolution") {
      out[CREATE_NAMES[key] ?? key] = wire(key, v);
    }
  }
  return out;
}

/**
 * Field-level messages from an API error: `{<key>: message}`. Accepts the shapes the backend
 * uses for validation (`details.fields` as an object or a list, `details.field`) and, as a
 * last resort, a `code` that is itself a field key.
 */
export function fieldErrors(e, knownKeys) {
  if (!(e instanceof ApiError)) return {};
  const d = e.details ?? {};
  const out = {};
  const put = (k, m) => { if (k) out[normKey(k)] = m || e.message; };
  if (d.fields && typeof d.fields === "object" && !Array.isArray(d.fields)) {
    for (const [k, m] of Object.entries(d.fields)) put(k, Array.isArray(m) ? m.join(" ") : String(m ?? ""));
  } else if (Array.isArray(d.fields)) {
    for (const f of d.fields) {
      if (typeof f === "string") put(f, e.message);
      else put(f.key ?? f.field, f.message);
    }
  } else if (Array.isArray(d.missing)) {
    for (const f of d.missing) put(typeof f === "string" ? f : f.key ?? f.field, typeof f === "string" ? undefined : f.message);
  } else if (typeof d.field === "string") {
    put(d.field, e.message);
  } else if (knownKeys && e.code && knownKeys.has(normKey(e.code))) {
    put(e.code, e.message);
  }
  return out;
}

/** Accept `cf[12]`, `customfield_12`, `custom_fields.12`, `*_id` / `*_ids` create names. */
export function normKey(k) {
  const s = String(k);
  let m = s.match(/^(?:cf\[(\d+)\]|cf:(\d+)|customfield_(\d+)|custom_fields\.(\d+))$/);
  if (m) return cfKey(Number(m[1] ?? m[2] ?? m[3] ?? m[4]));
  const back = Object.entries(CREATE_NAMES).find(([, v]) => v === s);
  if (back) return back[0];
  if (s === "issue_type_id") return "issue_type";
  if (s === "resolution_id") return "resolution";
  return s;
}
