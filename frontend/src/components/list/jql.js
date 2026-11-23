// JQL helpers of the «Lista» view. The table never sorts or filters on the client: the
// whole query (project scope, user filter, quick filters, search box, ORDER BY) travels as
// JQL, so what you see is exactly what «Exportar CSV» or a saved filter would return.

export const DEFAULT_SORT = [{ field: "created", dir: "DESC" }];

/** Index of the top-level ORDER BY (outside quoted strings), or -1. */
function orderIndex(text) {
  let quote = null;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if ((i === 0 || /[\s)]/.test(text[i - 1])) && /^order\s+by\s/i.test(text.slice(i))) return i;
  }
  return -1;
}

/** Split "a = b ORDER BY x DESC, y" into { where: "a = b", sort: [{field, dir}] }. */
export function splitOrder(jql) {
  const text = (jql ?? "").trim();
  const at = orderIndex(text);
  if (at < 0) return { where: text, sort: null };
  const where = text.slice(0, at).trim();
  const rest = text.slice(at).replace(/^order\s+by\s+/i, "");
  const sort = rest.split(",").map((part) => {
    const t = part.trim();
    const dm = t.match(/\s+(asc|desc)$/i);
    const field = (dm ? t.slice(0, dm.index) : t).trim();
    return { field, dir: dm?.[1].toUpperCase() === "DESC" ? "DESC" : "ASC" };
  }).filter((s) => s.field);
  return { where, sort: sort.length ? sort : null };
}

export function orderClause(sort) {
  if (!sort?.length) return "";
  return `ORDER BY ${sort.map((s) => `${s.field} ${s.dir}`).join(", ")}`;
}

/** User-facing JQL: filter + ORDER BY (what the JQL box shows). */
export function joinJql(where, sort) {
  return [where?.trim(), orderClause(sort)].filter(Boolean).join(" ");
}

function quote(s) {
  return `"${String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** Full JQL sent to the backend. */
export function composeJql({ projectKey, where, quick = [], text, sort }) {
  const parts = [`project = ${quote(projectKey)}`];
  if (where?.trim()) parts.push(`(${where.trim()})`);
  for (const q of quick) if (q?.trim()) parts.push(`(${q.trim()})`);
  if (text?.trim()) parts.push(`text ~ ${quote(text.trim())}`);
  return [parts.join(" AND "), orderClause(sort)].filter(Boolean).join(" ");
}

// JQL aliases of the sortable columns (same as the backend's FIELD_ALIASES), so a typed
// «ORDER BY principal» or «ORDER BY "story points"» lights up the right header.
const SORT_ALIASES = {
  clave: "key", issue: "key", issuekey: "key", resumen: "summary", tipo: "type", issuetype: "type",
  estado: "status", prioridad: "priority", responsable: "assignee", asignado: "assignee",
  informador: "reporter", etiquetas: "labels", etiqueta: "labels", label: "labels",
  principal: "parent", epic: "parent", "epic link": "parent", creado: "created",
  createddate: "created", actualizado: "updated", updateddate: "updated", resuelto: "resolved",
  resolutiondate: "resolved", vencimiento: "due", duedate: "due", inicio: "startdate",
  "story points": "storypoints", puntos: "storypoints", equipo: "team",
  components: "component", componente: "component", componentes: "component",
  fixversions: "fixversion", version: "fixversion", "versión": "fixversion",
  "versión de corrección": "fixversion", "version de correccion": "fixversion",
  affectsversion: "affectedversion", affectedversions: "affectedversion",
  "versión afectada": "affectedversion", "version afectada": "affectedversion",
  resolucion: "resolution", "resolución": "resolution",
  timeoriginalestimate: "originalestimate", "estimación original": "originalestimate",
  "estimacion original": "originalestimate", estimacionoriginal: "originalestimate",
  timeestimate: "remainingestimate", "estimación restante": "remainingestimate",
  "estimacion restante": "remainingestimate", estimacionrestante: "remainingestimate",
  "tiempo registrado": "timespent", tiemporegistrado: "timespent", marcada: "flagged",
};

// Names that always mean a system field (the backend resolves them before custom fields).
const SYSTEM_NAMES = new Set([
  ...Object.keys(SORT_ALIASES), ...Object.values(SORT_ALIASES), "sprint", "project", "proyecto",
  "rank", "id", "statuscategory", "categoria",
]);

function bare(field) {
  return String(field ?? "").trim().replace(/^["']|["']$/g, "").toLowerCase();
}

function canonical(field) {
  const f = bare(field);
  return SORT_ALIASES[f] ?? f;
}

/** Does the ORDER BY item `field` sort by the column `name` (its JQL sort name), or by
 * `alt` (a custom field's name, which JQL accepts too unless a system field has it)? */
function sameField(field, name, alt) {
  if (canonical(field) === canonical(name)) return true;
  const f = bare(field);
  return !!alt && !SYSTEM_NAMES.has(f) && f === bare(alt);
}

/** Header click: same column toggles ASC/DESC, `add` (Shift) appends a secondary sort. */
export function toggleSort(sort, field, add, alt) {
  const cur = sort ?? [];
  const i = cur.findIndex((s) => sameField(s.field, field, alt));
  if (add) {
    if (i < 0) return [...cur, { field, dir: "ASC" }];
    return cur.map((s, j) => (j === i ? { ...s, dir: s.dir === "ASC" ? "DESC" : "ASC" } : s));
  }
  const dir = i === 0 && cur[0].dir === "ASC" ? "DESC" : "ASC";
  return [{ field, dir }];
}

export function sortOf(sort, field, alt) {
  if (!field) return null;
  const i = (sort ?? []).findIndex((s) => sameField(s.field, field, alt));
  return i < 0 ? null : { ...sort[i], index: i };
}
