"use client";

import { useQueries, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronRight, ChevronsDownUp, ChevronsUpDown, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon, ProjectAvatar } from "@/components/icons";
import { IssueModal } from "@/components/issue/issue-view";
import { Button, PageSpinner } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Avatar, Confirm, EmptyState, Lozenge, Tabs } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { invalidateIssueViews, useMe } from "@/lib/api/hooks";
import { cn, fmtDate } from "@/lib/utils";
import { useNow } from "@/lib/use-now";
import { invalidatePlanViews, planRowsKey, planRowsQuery, savePlanView, usePlanConflicts, usePlanGroups, usePlanTimeline, usePlanView, useTeams } from "./api";
import { selectCls } from "./plan-form";

/*
 * Cronograma sin tope de incidencias, como Jira Plans: grupos y jerarquía desplegados por
 * defecto. Los grupos y sus conteos vienen del servidor; cada nodo desplegado (raíces de un
 * grupo o hijas de una incidencia) se pinta primero con filas skeleton y se pide solo cuando
 * esas filas entran en la ventana virtualizada (peticiones limitadas en paralelo en api.js);
 * sus siguientes páginas llegan con «Cargar más» o al hacer scroll. La vista (agrupación,
 * filtros, escala y lo contraído, como excepción al modo) se guarda por plan y usuario en
 * el servidor (`/plans/{id}/view`, con debounce); localStorage solo hace de respaldo.
 */

/* ------------------------------------------------------------------ dates (UTC day numbers) */

const DAY = 864e5;
const ROW = 36;
const LEFT = 460;
const OVERSCAN = 12;
const PAGE = 100;
const MAX_EXCEPTIONS = 2000;
const PX = { weeks: 28, months: 8, quarters: 3 };
const SPAN = { weeks: 84, months: 365, quarters: 730 };

const toDay = (s) => {
  const [y, m, d] = s.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / DAY);
};
const isoDay = (n) => new Date(n * DAY).toISOString().slice(0, 10);
/** Local Date for display (date-fns formats in local time). */
const dayDate = (n) => {
  const d = new Date(n * DAY);
  return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
};
const fmtDay = (n, p = "d MMM yyyy") => fmtDate(dayDate(n), p);
const monthStart = (n, every = 1) => {
  const d = new Date(n * DAY);
  const m = d.getUTCMonth() - (d.getUTCMonth() % every);
  return Math.round(Date.UTC(d.getUTCFullYear(), m, 1) / DAY);
};
const fmtNum = (n) => n.toLocaleString("es-ES");

/** [start, end] in day numbers from the issue's own dates (either one alone = 1 day). */
function span(issue) {
  if (!issue.start_date && !issue.due_date) return null;
  const s = toDay(issue.start_date ?? issue.due_date);
  const e = toDay(issue.due_date ?? issue.start_date);
  return [Math.min(s, e), Math.max(s, e)];
}
const rollupSpan = (issue) => (issue.rollup_start ? [toDay(issue.rollup_start), toDay(issue.rollup_end)] : null);
const endOf = (i) => i.due_date ?? i.start_date;
const startOf = (i) => i.start_date ?? i.due_date;

const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);
const OTHER = "var(--series-other)";
const NONE = 0;
const EMPTY_FILTERS = { project_ids: [], team_ids: [], status_ids: [], assignee_ids: [], version_ids: [] };
const EMPTY_MAP = new Map();
const EMPTY_SET = new Set();
const EXPANDED = { mode: "expanded", exceptions: [] };
const DEFAULT_VIEW = { group_by: "none", scale: "months", filters: EMPTY_FILTERS, collapse: {} };
const SAVE_DELAY = 700;

/* ------------------------------------------------------------------ nodes */

// Node keys: "g:<group>" for a group's roots, "<group>:<issue id>" for an issue's children
// (an issue appears once per group, so the id is enough and survives filter changes).
function parseNode(key) {
  if (key.startsWith("g:")) return { group: key.slice(2), parent: null };
  const sep = key.indexOf(":");
  return { group: key.slice(0, sep), parent: Number(key.slice(sep + 1)) };
}

/* The view lives on the server; localStorage is only a fallback (server unreachable) and the
   source of a one-time migration of what earlier versions kept there. */
const localKey = (planId, userId) => `gestiona-plan-view:${planId}:${userId}`;
const normalizeView = (v) => ({
  ...DEFAULT_VIEW, ...v,
  filters: { ...EMPTY_FILTERS, ...(v?.filters ?? {}) },
  collapse: v?.collapse && typeof v.collapse === "object" ? v.collapse : {},
});
function readLocal(key) {
  if (!key || typeof window === "undefined") return null;
  try {
    const raw = JSON.parse(window.localStorage.getItem(key) ?? "null");
    if (!raw || typeof raw !== "object") return null;
    if (raw.v === 2) return normalizeView(raw.view);
    // first local format: { [groupBy]: { mode, except } }
    const collapse = {};
    for (const [g, c] of Object.entries(raw)) if (c?.mode) collapse[g] = { mode: c.mode, exceptions: c.except ?? [] };
    return Object.keys(collapse).length ? normalizeView({ collapse }) : null;
  } catch {
    return null;
  }
}
function writeLocal(key, view) {
  if (!key) return;
  try { window.localStorage.setItem(key, JSON.stringify({ v: 2, view })); } catch { /* storage full or blocked */ }
}
function removeLocal(key) {
  if (!key) return;
  try { window.localStorage.removeItem(key); } catch { /* ignore */ }
}

const combinePages = (results) => results.map((r) => ({ data: r.data, isPending: r.isPending, isError: r.isError, error: r.error }));

/** Optimistic edit of one issue in every cached page (its rows and dependency ends). */
function patchPage(page, id, changes) {
  const end = (e) => (e.id === id ? { ...e, ...("start_date" in changes ? { start_date: changes.start_date } : {}), ...("due_date" in changes ? { due_date: changes.due_date } : {}) } : e);
  return {
    ...page,
    rows: page.rows.map((r) => (r.id === id ? { ...r, ...changes } : r)),
    dependencies: page.dependencies.map((d) => (d.blocker.id === id || d.blocked.id === id ? { ...d, blocker: end(d.blocker), blocked: end(d.blocked) } : d)),
  };
}

/* ------------------------------------------------------------------ bar */

function Bar({ issue, range, origin, px, color, editable, linkable, onChange, onOpen, onLinkStart }) {
  const [drag, setDrag] = useState(null);
  const [preview, setPreview] = useState(null);
  const moved = useRef(false);
  const [s0, e0] = range;
  const [s, e] = preview ?? range;
  const left = (s - origin) * px;
  const width = Math.max(px, (e - s + 1) * px);
  const down = (mode) => (ev) => {
    if (ev.button !== 0) return;
    ev.stopPropagation();
    if (!editable) return;
    ev.currentTarget.setPointerCapture(ev.pointerId);
    moved.current = false;
    setDrag({ mode, x: ev.clientX });
  };
  const move = (ev) => {
    if (!drag) return;
    const d = Math.round((ev.clientX - drag.x) / px);
    if (d) moved.current = true;
    if (drag.mode === "move") setPreview([s0 + d, e0 + d]);
    else if (drag.mode === "start") setPreview([Math.min(s0 + d, e0), e0]);
    else setPreview([s0, Math.max(e0 + d, s0)]);
  };
  const up = () => {
    if (drag && preview && moved.current) onChange(preview[0], preview[1]);
    setDrag(null);
    setPreview(null);
  };
  return (
    <div className={cn("group absolute top-1.5 flex h-6 select-none items-center rounded-[4px] text-xs font-medium text-white", !editable && "cursor-pointer")}
         style={{ left, width, backgroundColor: color, cursor: editable ? (drag ? "grabbing" : "grab") : undefined }}
         title={`${issue.key} · ${fmtDay(s)} – ${fmtDay(e)}${editable ? "" : " (sin permiso para editar)"}`}
         onPointerDown={down("move")} onPointerMove={move} onPointerUp={up}
         onClick={(ev) => { ev.stopPropagation(); if (!moved.current) onOpen(); }}>
      {editable && <span onPointerDown={down("start")} className="h-full w-2 shrink-0 cursor-ew-resize rounded-l-[4px] hover:bg-black/20" />}
      <span className="min-w-0 flex-1 truncate px-1.5">{width > 90 ? issue.summary : ""}</span>
      {editable && <span onPointerDown={down("end")} className="h-full w-2 shrink-0 cursor-ew-resize rounded-r-[4px] hover:bg-black/20" />}
      {linkable && (
        <span role="button" aria-label={`Crear dependencia desde ${issue.key}`} title="Arrastra hasta otra incidencia para indicar que esta la bloquea"
              onPointerDown={(ev) => { ev.stopPropagation(); onLinkStart(ev); }}
              className="absolute -right-3 top-1/2 h-3 w-3 -translate-y-1/2 cursor-crosshair rounded-full border-2 border-bg bg-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ filters */

function FilterPicker({ label, options, value, onChange }) {
  const toggle = (v) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <Picker multiple value={value} options={options} onSelect={toggle} placeholder={`Filtrar por ${label.toLowerCase()}`}
            footer={value.length ? <Button size="sm" variant="subtle" className="w-full justify-center" onClick={() => onChange([])}>Quitar filtro</Button> : null}
            trigger={(
              <Button size="sm" variant={value.length ? "selected" : "default"}>
                {label}{value.length ? ` (${value.length})` : ""}<ChevronDown size={12} />
              </Button>
            )} />
  );
}

/* ------------------------------------------------------------------ timeline */

export function PlanTimeline({ plan }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const qc = useQueryClient();
  const meta = usePlanTimeline(plan.id);
  const conflictsQ = usePlanConflicts(plan.id);
  const allTeams = useTeams("");
  const now = useNow();
  const [linkTypeId, setLinkTypeId] = useState(null);
  const [removing, setRemoving] = useState(null);
  const [showConflicts, setShowConflicts] = useState(false);

  const selected = params.get("selectedIssue");
  const open = (k) => { const p = new URLSearchParams(params.toString()); p.set("selectedIssue", k); router.push(`${pathname}?${p}`, { scroll: false }); };
  const close = () => {
    const p = new URLSearchParams(params.toString()); p.delete("selectedIssue");
    router.push(`${pathname}${p.size ? `?${p}` : ""}`, { scroll: false });
    invalidatePlanViews(qc, plan.id);
  };

  const t = new Date(now);
  const today = Math.round(Date.UTC(t.getFullYear(), t.getMonth(), t.getDate()) / DAY);

  // the viewer's layout: seeded once from the server; if the server has none, from an old
  // local copy (pushed to the server once); local only when the server cannot be reached
  const viewQ = usePlanView(plan.id);
  const me = useMe();
  const storeKey = me.data ? localKey(plan.id, me.data.id) : null;
  const [view, setView] = useState(null);
  const [migrate, setMigrate] = useState(null);
  if (view === null) {
    if (viewQ.data?.view) setView(normalizeView(viewQ.data.view));
    else if ((viewQ.data || viewQ.isError) && (storeKey || me.isError)) {
      const local = readLocal(storeKey);
      setView(local ?? DEFAULT_VIEW);
      if (local && viewQ.data) setMigrate(local);
    }
  }
  useEffect(() => {
    if (!migrate) return;
    savePlanView(qc, plan.id, migrate).then(() => removeLocal(storeKey), () => {});
  }, [migrate, qc, plan.id, storeKey]);

  // debounced save; a failed save keeps a local copy, and leaving flushes what is pending
  const saver = useRef({ timer: null, pending: null });
  const send = (next) => savePlanView(qc, plan.id, next).catch(() => writeLocal(storeKey, next));
  const persist = (next) => {
    const st = saver.current;
    st.pending = next;
    clearTimeout(st.timer);
    st.timer = setTimeout(() => { const v = st.pending; st.pending = null; if (v) send(v); }, SAVE_DELAY);
  };
  useEffect(() => {
    const st = saver.current;
    return () => {
      clearTimeout(st.timer);
      if (st.pending) savePlanView(qc, plan.id, st.pending).catch(() => writeLocal(storeKey, st.pending));
    };
  }, [qc, plan.id, storeKey]);

  const cur = view ?? DEFAULT_VIEW;
  const update = (patch) => {
    const next = { ...cur, ...patch };
    setView(next);
    persist(next);
  };
  const groupBy = cur.group_by;
  const scale = cur.scale;
  const filters = cur.filters;
  const bodyFilters = filters;
  const groupsQ = usePlanGroups(plan.id, groupBy, bodyFilters, view !== null);
  const groups = useMemo(() => groupsQ.data?.group_by === groupBy ? groupsQ.data.groups : [], [groupsQ.data, groupBy]);

  // collapsed/expanded per grouping: a mode plus the exceptions the user toggled
  const collapse = cur.collapse[groupBy]?.mode ? cur.collapse[groupBy] : EXPANDED;
  const except = useMemo(() => new Set(collapse.exceptions ?? []), [collapse]);
  const allCollapsed = collapse.mode === "collapsed";
  const saveCollapse = (next) => update({ collapse: { ...cur.collapse, [groupBy]: next } });

  // nodes asked for (their skeleton rows reached the viewport) and the pages each one
  // loaded; both reset when grouping or filters change
  const scope = JSON.stringify([groupBy, bodyFilters]);
  const [wantedState, setWantedState] = useState({ scope, set: EMPTY_SET });
  const wanted = wantedState.scope === scope ? wantedState.set : EMPTY_SET;
  const [pageState, setPageState] = useState({ scope, map: EMPTY_MAP });
  const pages = pageState.scope === scope ? pageState.map : EMPTY_MAP;

  const need = (keys) => setWantedState((s) => {
    const base = s.scope === scope ? s.set : EMPTY_SET;
    const fresh = keys.filter((k) => !base.has(k));
    return fresh.length ? { scope, set: new Set([...base, ...fresh]) } : s;
  });
  const forget = (keys) => setWantedState((s) => {
    if (s.scope !== scope || !keys.some((k) => s.set.has(k))) return s;
    const set = new Set(s.set);
    keys.forEach((k) => set.delete(k));
    return { scope, set };
  });
  const loadMore = (node, cursor) => setPageState((s) => {
    const base = s.scope === scope ? s.map : EMPTY_MAP;
    const list = base.get(node) ?? [null];
    if (list.includes(cursor)) return s;
    return { scope, map: new Map(base).set(node, [...list, cursor]) };
  });

  const nodes = useMemo(() => {
    const known = new Set(groups.map((g) => g.key));
    const out = [];
    for (const key of wanted) {
      const n = parseNode(key);
      if (!known.has(n.group)) continue;
      const isOpen = key === "g:all" || allCollapsed === except.has(key);
      if (isOpen) out.push({ key, ...n });
    }
    return out;
  }, [groups, wanted, allCollapsed, except]);

  const results = useQueries({
    queries: nodes.flatMap((n) => (pages.get(n.key) ?? [null]).map((cursor) => planRowsQuery(plan.id, {
      filters: bodyFilters, group_by: groupBy, group: n.group, parent_id: n.parent, cursor, limit: PAGE,
    }))),
    combine: combinePages,
  });

  // flatten the open tree into rows; nodes not loaded yet become skeleton rows (as many as
  // they are expected to hold, so the layout barely moves when they arrive)
  const flat = useMemo(() => {
    const isOpen = (key) => key === "g:all" || allCollapsed === except.has(key);
    const byNode = new Map();
    let idx = 0;
    for (const n of nodes) byNode.set(n.key, (pages.get(n.key) ?? [null]).map(() => results[idx++]).filter(Boolean));
    const rows = [], byId = new Map(), deps = new Map();
    const skeleton = (nodeKey, depth, expected, requested) => {
      const count = Math.max(1, Math.min(expected || 1, PAGE));
      for (let i = 0; i < count; i++) rows.push({ kind: "skeleton", key: `${nodeKey}#s${i}`, node: nodeKey, depth, requested });
    };
    const walk = (nodeKey, gk, depth, expected) => {
      const list = byNode.get(nodeKey);
      if (!list?.[0]?.data) {
        if (list?.[0]?.isError) rows.push({ kind: "error", key: `${nodeKey}#error`, node: nodeKey, depth, error: list[0].error });
        else skeleton(nodeKey, depth, expected, !!list);
        return;
      }
      const seen = new Set();
      let total = null;
      for (const p of list) {
        if (!p.data) continue;
        if (p.data.total != null) total = p.data.total;
        p.data.dependencies.forEach((d) => deps.set(d.id, d));
        for (const issue of p.data.rows) {
          if (seen.has(issue.id)) continue;
          seen.add(issue.id);
          if (!byId.has(issue.id)) byId.set(issue.id, issue);
          const key = `${gk}:${issue.id}`;
          const open = issue.children_count > 0 && depth < 8 && isOpen(key);
          rows.push({ kind: "issue", key, issue, depth, open });
          if (open) walk(key, gk, depth + 1, issue.children_count);
        }
      }
      const last = list[list.length - 1];
      if (last.isPending) skeleton(nodeKey, depth, 1, true);
      else if (last.isError) rows.push({ kind: "error", key: `${nodeKey}#error`, node: nodeKey, depth, error: last.error });
      else if (last.data?.next_cursor) {
        rows.push({ kind: "more", key: `${nodeKey}#more`, node: nodeKey, cursor: last.data.next_cursor, depth,
                    remaining: total != null ? Math.max(0, total - seen.size) : null });
      }
    };
    for (const g of groups) {
      const key = `g:${g.key}`;
      const open = isOpen(key);
      if (groupBy !== "none") rows.push({ kind: "group", key, group: g, open, depth: -1 });
      if (open) walk(key, g.key, 0, g.count);
    }
    return { rows, byId, deps: [...deps.values()] };
  }, [nodes, pages, results, groups, groupBy, allCollapsed, except]);

  // toggling a row; collapsing also stops observing the nodes that were under it
  const toggle = (row, idx) => {
    const next = new Set(except);
    if (next.has(row.key)) next.delete(row.key); else next.add(row.key);
    saveCollapse({ mode: collapse.mode, exceptions: [...next].slice(-MAX_EXCEPTIONS) });
    if (!row.open) return;
    const gone = [row.key];
    for (let j = idx + 1; j < flat.rows.length && flat.rows[j].depth > row.depth; j++) {
      const r = flat.rows[j];
      gone.push(r.kind === "issue" ? r.key : r.node);
    }
    forget(gone.filter(Boolean));
  };
  const expandAll = () => saveCollapse(EXPANDED);
  const collapseAll = () => {
    saveCollapse({ mode: "collapsed", exceptions: [] });
    setWantedState({ scope, set: EMPTY_SET });
  };

  // color follows the project (its slot in the plan's sources), not the row order
  const projectColor = useMemo(() => {
    const m = new Map();
    plan.projects.forEach((p, idx) => m.set(p.id, idx < SERIES.length ? SERIES[idx] : OTHER));
    return m;
  }, [plan.projects]);
  const projectById = useMemo(() => new Map(plan.projects.map((p) => [p.id, p])), [plan.projects]);
  const teamById = useMemo(() => new Map((meta.data?.teams ?? []).map((x) => [x.id, x])), [meta.data]);

  // visible range: the whole plan's dates (from the server), not only what is loaded
  const px = PX[scale];
  const range = meta.data?.date_range;
  const { origin, days } = useMemo(() => {
    let lo = today - 14, hi = today + SPAN[scale];
    if (range?.start) lo = Math.min(lo, toDay(range.start) - 14);
    if (range?.end) hi = Math.max(hi, toDay(range.end) + 30);
    lo = Math.max(lo, today - 3 * 365);
    hi = Math.min(hi, today + 5 * 365);
    const o = scale === "weeks" ? lo - ((dayDate(lo).getDay() + 6) % 7) : monthStart(lo, scale === "quarters" ? 3 : 1);
    return { origin: o, days: hi - o + 1 };
  }, [range, today, scale]);
  const width = days * px;

  const ticks = useMemo(() => {
    const out = [];
    for (let n = origin; n < origin + days; n++) {
      const d = dayDate(n);
      if (scale === "weeks" ? d.getDay() === 1 : d.getDate() === 1 && (scale !== "quarters" || d.getMonth() % 3 === 0)) {
        out.push({ left: (n - origin) * px, label: scale === "weeks" ? fmtDay(n, "d MMM") : scale === "months" ? fmtDay(n, "MMM yyyy") : `T${d.getMonth() / 3 + 1} ${d.getFullYear()}` });
      }
    }
    return out;
  }, [origin, days, scale, px]);

  /* ---------------------------------------------------------------- dependencies */

  // ends that are not loaded come with their dates from the server
  const deps = useMemo(() => flat.deps.map((d) => {
    const blocker = flat.byId.get(d.blocker_id) ?? d.blocker;
    const blocked = flat.byId.get(d.blocked_id) ?? d.blocked;
    const end = endOf(blocker), start = startOf(blocked);
    return { ...d, blocker, blocked, conflict: !!(end && start && end > start) };
  }), [flat]);

  const linkTypes = meta.data?.dependency_link_types ?? [];
  const activeLinkType = linkTypes.find((lt) => lt.id === linkTypeId) ?? linkTypes[0];

  const createLink = async (from, target) => {
    if (!target || target.id === from.id || !activeLinkType) return;
    try {
      await unwrap(api.POST("/api/v1/issues/{key}/links", { params: { path: { key: from.key } }, body: { link_type_id: activeLinkType.id, target: target.key, direction: "outward" } }));
      toast.success(`${from.key} ${activeLinkType.outward} ${target.key}`);
      invalidateIssueViews(qc, from.key);
      invalidatePlanViews(qc, plan.id);
    } catch (e) { toast.error(errorMessage(e)); }
  };

  const removeDep = async () => {
    const d = removing;
    try {
      await unwrap(api.DELETE("/api/v1/links/{lid}", { params: { path: { lid: d.id } } }));
      setRemoving(null);
      toast.success("Dependencia eliminada");
      invalidateIssueViews(qc, d.blocker.key);
      invalidatePlanViews(qc, plan.id);
    } catch (e) { toast.error(errorMessage(e)); }
  };

  /* ---------------------------------------------------------------- edits */

  const patchIssue = async (issue, body, optimistic) => {
    const key = planRowsKey(plan.id);
    const snapshot = qc.getQueriesData({ queryKey: key });
    qc.setQueriesData({ queryKey: key }, (old) => (old?.rows ? patchPage(old, issue.id, optimistic) : old));
    try {
      await unwrap(api.PATCH("/api/v1/issues/{key}", { params: { path: { key: issue.key } }, body }));
      invalidateIssueViews(qc, issue.key);
    } catch (e) {
      snapshot.forEach(([k, v]) => qc.setQueryData(k, v));
      toast.error(errorMessage(e));
    } finally {
      invalidatePlanViews(qc, plan.id);
    }
  };
  const setDates = (issue, s, e) => {
    const body = { start_date: isoDay(s), due_date: isoDay(e) };
    patchIssue(issue, body, body);
  };
  const setTeam = (issue, teamId) => patchIssue(issue, { team: teamId }, { team_id: teamId });
  const schedule = (issue, ev) => {
    if (span(issue) || !issue.can_edit) return;
    const rect = ev.currentTarget.getBoundingClientRect();
    const s = origin + Math.floor((ev.clientX - rect.left) / px);
    setDates(issue, s, s + 13);
  };

  /* ---------------------------------------------------------------- options */

  const opt = useMemo(() => ({
    projects: plan.projects.map((p) => ({ value: p.id, label: p.name, description: p.key, icon: <ProjectAvatar project={p} size={18} /> })),
    teams: [{ value: NONE, label: "Sin equipo" }, ...(meta.data?.teams ?? []).map((x) => ({ value: x.id, label: x.name, description: x.deleted ? "Eliminado" : x.in_plan ? "" : "Fuera del plan" }))],
    statuses: (meta.data?.statuses ?? []).map((s) => ({ value: s.id, label: s.name, icon: <Lozenge category={s.category}>{" "}</Lozenge> })),
    assignees: [{ value: NONE, label: "Sin asignar", icon: <Avatar user={null} size="xs" /> }, ...(meta.data?.assignees ?? []).map((u) => ({ value: u.id, label: u.name, icon: <Avatar user={u} size="xs" /> }))],
    versions: [{ value: NONE, label: "Sin versión" }, ...(meta.data?.versions ?? []).map((v) => ({ value: v.id, label: v.name, description: projectById.get(v.project_id)?.key }))],
  }), [plan.projects, meta.data, projectById]);
  const teamOptions = [{ value: NONE, label: "Sin equipo" }, ...(allTeams.data ?? []).map((x) => ({ value: x.id, label: x.name }))];
  const anyFilter = Object.values(filters).some((v) => v.length);
  const setFilter = (name) => (v) => update({ filters: { ...filters, [name]: v } });

  if (meta.isPending || view === null) return <PageSpinner />;
  if (meta.error) return <p className="px-6 py-4 text-sm text-danger">{errorMessage(meta.error)}</p>;

  const total = meta.data.total;
  const shown = groupsQ.data?.total ?? total;
  const conflicts = conflictsQ.data;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 px-6 pb-2">
        <FilterPicker label="Proyecto" options={opt.projects} value={filters.project_ids} onChange={setFilter("project_ids")} />
        <FilterPicker label="Equipo" options={opt.teams} value={filters.team_ids} onChange={setFilter("team_ids")} />
        <FilterPicker label="Estado" options={opt.statuses} value={filters.status_ids} onChange={setFilter("status_ids")} />
        <FilterPicker label="Responsable" options={opt.assignees} value={filters.assignee_ids} onChange={setFilter("assignee_ids")} />
        <FilterPicker label="Versión" options={opt.versions} value={filters.version_ids} onChange={setFilter("version_ids")} />
        {anyFilter && <Button size="sm" variant="subtle" onClick={() => update({ filters: EMPTY_FILTERS })}><X size={14} />Limpiar</Button>}
        <Button size="sm" variant="subtle" onClick={expandAll} disabled={!allCollapsed && !except.size} title="Despliega todos los grupos e incidencias con hijas">
          <ChevronsUpDown size={14} />Desplegar todo
        </Button>
        <Button size="sm" variant="subtle" onClick={collapseAll} disabled={allCollapsed && !except.size} title="Contrae todos los grupos e incidencias con hijas">
          <ChevronsDownUp size={14} />Contraer todo
        </Button>
        <label className="ml-2 flex items-center gap-2 text-sm text-fg-subtle">Agrupar por
          <select className={cn(selectCls, "h-7 w-36")} value={groupBy} onChange={(e) => update({ group_by: e.target.value })}>
            <option value="none">Nada</option><option value="project">Proyecto</option><option value="team">Equipo</option><option value="version">Versión</option>
          </select>
        </label>
        {linkTypes.length > 1 && (
          <label className="flex items-center gap-2 text-sm text-fg-subtle">Dependencia
            <select className={cn(selectCls, "h-7 w-40")} value={activeLinkType?.id ?? ""} onChange={(e) => setLinkTypeId(Number(e.target.value))}>
              {linkTypes.map((lt) => <option key={lt.id} value={lt.id}>{lt.name}</option>)}
            </select>
          </label>
        )}
        <div className="ml-auto"><Tabs value={scale} onChange={(v) => update({ scale: v })} className="border-none" tabs={[{ value: "weeks", label: "Semanas" }, { value: "months", label: "Meses" }, { value: "quarters", label: "Trimestres" }]} /></div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-6 pb-2 text-xs text-fg-subtle">
        <span className="font-medium text-fg" aria-live="polite">
          {anyFilter ? `${fmtNum(shown)} de ${fmtNum(total)} incidencias` : `${fmtNum(total)} ${total === 1 ? "incidencia" : "incidencias"}`}
        </span>
        {plan.projects.length > 1 && plan.projects.map((p) => (
          <span key={p.id} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[2px]" style={{ backgroundColor: projectColor.get(p.id) }} />{p.key}</span>
        ))}
        <span>Arrastra una barra para moverla o sus extremos para cambiar la duración.{activeLinkType ? " Arrastra el punto del final hasta otra fila para crear una dependencia." : ""}</span>
        {conflicts?.count > 0 && (
          <button className="inline-flex items-center gap-1 font-medium text-danger hover:underline" onClick={() => setShowConflicts((v) => !v)} aria-expanded={showConflicts}>
            <AlertTriangle size={14} />{conflicts.count === 1 ? "1 conflicto de dependencias" : `${fmtNum(conflicts.count)} conflictos de dependencias`}
          </button>
        )}
      </div>

      {meta.data.filter_error && <p className="mx-6 mb-2 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">El filtro JQL del plan no se puede aplicar con tus permisos: {meta.data.filter_error}</p>}
      {plan.hidden_project_count > 0 && <p className="mx-6 mb-2 text-xs text-fg-subtle">Este plan incluye {plan.hidden_project_count} proyecto(s) a los que no tienes acceso; sus incidencias no se muestran.</p>}

      {showConflicts && conflicts?.count > 0 && (
        <div className="mx-6 mb-2 max-h-40 overflow-y-auto rounded-[3px] border border-line bg-bg-subtle px-3 py-2 text-sm">
          {conflicts.conflicts.map((d) => (
            <div key={d.id} className="flex items-center gap-2 py-0.5">
              <AlertTriangle size={14} className="shrink-0 text-danger" />
              <span><button className="font-medium text-link hover:underline" onClick={() => open(d.blocker.key)}>{d.blocker.key}</button> termina el {fmtDay(toDay(endOf(d.blocker)))}, después de que empiece <button className="font-medium text-link hover:underline" onClick={() => open(d.blocked.key)}>{d.blocked.key}</button> ({fmtDay(toDay(startOf(d.blocked)))}).</span>
            </div>
          ))}
          {conflicts.truncated && <p className="pt-1 text-xs text-fg-subtle">Y {fmtNum(conflicts.count - conflicts.conflicts.length)} más. Usa los filtros o mueve las fechas para resolverlos.</p>}
        </div>
      )}

      {!total ? (
        <EmptyState title="El plan no tiene incidencias" body={plan.projects.length ? "Ninguna incidencia de los proyectos del plan cumple el filtro." : "Añade proyectos en «Configuración» para empezar a planificar."} />
      ) : groupsQ.error ? (
        <p className="px-6 py-4 text-sm text-danger">{errorMessage(groupsQ.error)}</p>
      ) : groupsQ.data?.group_by !== groupBy ? <PageSpinner /> : (
        <TimelineGrid rows={flat.rows} deps={deps} byId={flat.byId} origin={origin} px={px} width={width} ticks={ticks}
                      todayLeft={(today - origin) * px} scale={scale} projectColor={projectColor} teamById={teamById} teamOptions={teamOptions}
                      linkable={!!activeLinkType} onToggle={toggle} onNeed={need} onOpen={open} onSetDates={setDates} onSetTeam={setTeam}
                      onSchedule={schedule} onLoadMore={loadMore} onRemoveDep={setRemoving} onLink={createLink} />
      )}

      <Confirm open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} danger confirmLabel="Quitar dependencia"
               title="¿Quitar la dependencia?" onConfirm={removeDep}
               body={removing && <p><b>{removing.blocker.key}</b> {removing.label} <b>{removing.blocked.key}</b>. Se elimina el vínculo entre las dos incidencias.</p>} />
      <IssueModal issueKey={selected} onClose={close} />
    </div>
  );
}

/* ------------------------------------------------------------------ virtualized grid */

function TimelineGrid({ rows, deps, byId, origin, px, width, ticks, todayLeft, scale, projectColor, teamById, teamOptions,
                        linkable, onToggle, onNeed, onOpen, onSetDates, onSetTeam, onSchedule, onLoadMore, onRemoveDep, onLink }) {
  const scrollRef = useRef(null);
  const bodyRef = useRef(null);
  const [view, setView] = useState({ top: 0, height: 800 });
  const [linking, setLinking] = useState(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setView((v) => (v.height === el.clientHeight ? v : { ...v, height: el.clientHeight })));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Scroll to today when the scale changes; when the range widens to the left, keep the
  // same dates under the user's eyes instead of jumping.
  const scrolled = useRef(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const prev = scrolled.current;
    if (prev?.scale === scale) el.scrollLeft += (prev.origin - origin) * px;
    else el.scrollLeft = Math.max(0, todayLeft - 240);
    scrolled.current = { scale, origin };
  }, [todayLeft, scale, origin, px]);

  const n = rows.length;
  const first = Math.max(0, Math.floor(view.top / ROW) - OVERSCAN);
  const last = Math.min(n, Math.ceil((view.top + view.height) / ROW) + OVERSCAN);

  // lazy loading by viewport: skeleton rows that come into view ask for their node, and a
  // «Cargar más» row in view loads the next page (infinite scroll)
  useEffect(() => {
    const needed = [];
    for (let i = first; i < last; i++) {
      const r = rows[i];
      if (r?.kind === "skeleton" && !r.requested && !needed.includes(r.node)) needed.push(r.node);
      else if (r?.kind === "more") onLoadMore(r.node, r.cursor);
    }
    if (needed.length) onNeed(needed);
  }, [first, last, rows, onLoadMore, onNeed]);

  const rowIndex = useMemo(() => {
    const m = new Map();
    rows.forEach((r, idx) => { if (r.kind === "issue" && !m.has(r.issue.id)) m.set(r.issue.id, idx); });
    return m;
  }, [rows]);

  // only arrows that cross the rendered window; an end that is not loaded gets a stub
  const top = first * ROW;
  const arrows = [];
  for (const d of deps) {
    const ia = rowIndex.get(d.blocker_id), ib = rowIndex.get(d.blocked_id);
    if (ia === undefined && ib === undefined) continue;
    const lo = Math.min(ia ?? ib, ib ?? ia), hi = Math.max(ia ?? ib, ib ?? ia);
    if (hi < first || lo >= last) continue;
    const a = ia !== undefined ? span(d.blocker) : null, b = ib !== undefined ? span(d.blocked) : null;
    if ((ia !== undefined && !a) || (ib !== undefined && !b)) continue;
    let path, title = `${d.blocker.key} ${d.label} ${d.blocked.key}`;
    if (a && b) {
      const x1 = (a[1] - origin + 1) * px, y1 = ia * ROW + ROW / 2 - top;
      const x2 = (b[0] - origin) * px, y2 = ib * ROW + ROW / 2 - top;
      const c = Math.max(24, Math.abs(x2 - x1) / 2);
      path = `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
    } else if (a) {
      const x1 = (a[1] - origin + 1) * px, y1 = ia * ROW + ROW / 2 - top;
      path = `M${x1},${y1} L${x1 + 22},${y1}`;
      title += " (fuera de la vista)";
    } else {
      const x2 = (b[0] - origin) * px, y2 = ib * ROW + ROW / 2 - top;
      path = `M${x2 - 22},${y2} L${x2},${y2}`;
      title += " (fuera de la vista)";
    }
    if (d.conflict) title += " — conflicto: termina después de que empiece";
    arrows.push({ ...d, path, title, stub: !(a && b) });
  }

  useEffect(() => {
    if (!linking) return;
    const rect = () => bodyRef.current?.getBoundingClientRect();
    const onMove = (ev) => {
      const r = rect();
      if (r) setLinking((l) => l && { ...l, x2: ev.clientX - r.left - LEFT, y2: ev.clientY - r.top });
    };
    const onUp = (ev) => {
      const from = linking.from;
      setLinking(null);
      const el = document.elementFromPoint(ev.clientX, ev.clientY)?.closest("[data-plan-issue]");
      onLink(from, el && byId.get(Number(el.getAttribute("data-plan-issue"))));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp, { once: true });
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  }, [linking, byId, onLink]);

  const startLink = (issue, rowIdx) => (ev) => {
    const r = bodyRef.current?.getBoundingClientRect();
    if (!r) return;
    const sp = span(issue);
    const x1 = (sp[1] - origin + 1) * px, y1 = rowIdx * ROW + ROW / 2;
    setLinking({ from: issue, x1, y1, x2: ev.clientX - r.left - LEFT, y2: ev.clientY - r.top });
  };

  const rowStyle = (idx) => ({ top: idx * ROW, height: ROW, width: LEFT + width });
  const visible = [];
  for (let idx = first; idx < last; idx++) {
    const r = rows[idx];
    if (r.kind === "group") {
      visible.push(
        <div key={r.key} className="absolute left-0 flex border-b border-line bg-bg-sunken/60" style={rowStyle(idx)}>
          <button className="sticky left-0 z-20 flex shrink-0 items-center gap-1.5 border-r border-line bg-bg-sunken px-2 text-left text-sm font-semibold" style={{ width: LEFT }}
                  aria-expanded={r.open} onClick={() => onToggle(r, idx)}>
            <ChevronRight size={14} className={cn("transition-transform", r.open && "rotate-90")} />
            <span className="truncate">{r.group.label}</span><span className="text-xs font-normal text-fg-subtle">{fmtNum(r.group.count)}</span>
          </button>
        </div>,
      );
    } else if (r.kind === "issue") {
      const issue = r.issue;
      const own = span(issue), roll = own ? null : rollupSpan(issue);
      visible.push(
        <div key={r.key} className="absolute left-0 flex border-b border-line hover:bg-bg-hover/60" style={rowStyle(idx)}>
          <div className="sticky left-0 z-20 flex shrink-0 items-center gap-1.5 border-r border-line bg-bg pr-2 text-sm" style={{ width: LEFT, paddingLeft: 8 + r.depth * 20 }}>
            <button aria-label={r.open ? "Contraer" : `Expandir (${issue.children_count})`} aria-expanded={issue.children_count ? r.open : undefined}
                    className={cn("rounded p-0.5 hover:bg-bg-pressed", !issue.children_count && "invisible")} onClick={() => onToggle(r, idx)}>
              <ChevronRight size={14} className={cn("transition-transform", r.open && "rotate-90")} />
            </button>
            <IssueTypeIcon type={issue.type} />
            <button onClick={() => onOpen(issue.key)} className="min-w-0 flex-1 truncate text-left hover:underline" title={`${issue.key} ${issue.summary}`}>
              <span className="text-fg-subtle">{issue.key}</span> {issue.summary}
            </button>
            {issue.children_count > 0 && !r.open && <span className="shrink-0 text-xs text-fg-subtlest" title="Incidencias hijas">{fmtNum(issue.children_count)}</span>}
            <Lozenge category={issue.status.category} className="max-w-20 shrink-0">{issue.status.name}</Lozenge>
            <TeamCell issue={issue} team={teamById.get(issue.team_id)} options={teamOptions} onSelect={(v) => onSetTeam(issue, v || null)} />
          </div>
          <div data-plan-issue={issue.id} className={cn("relative", !own && issue.can_edit && "cursor-copy")} style={{ width }}
               title={!own && issue.can_edit ? "Haz clic para programarla" : undefined}
               onClick={(e) => onSchedule(issue, e)}>
            {own ? (
              <Bar issue={issue} range={own} origin={origin} px={px} color={projectColor.get(issue.project_id) ?? OTHER}
                   editable={issue.can_edit} linkable={issue.can_link && linkable}
                   onOpen={() => onOpen(issue.key)} onChange={(s, e) => onSetDates(issue, s, e)} onLinkStart={startLink(issue, idx)} />
            ) : roll ? (
              <div className="pointer-events-none absolute top-2.5 h-4 rounded-[4px] opacity-40"
                   title="Fechas de sus incidencias hijas"
                   style={{ left: (roll[0] - origin) * px, width: (roll[1] - roll[0] + 1) * px,
                            background: `repeating-linear-gradient(45deg, ${projectColor.get(issue.project_id) ?? OTHER} 0 6px, transparent 6px 10px)` }} />
            ) : null}
          </div>
        </div>,
      );
    } else if (r.kind === "skeleton") {
      visible.push(
        <div key={r.key} className="absolute left-0 flex border-b border-line" style={rowStyle(idx)} aria-hidden>
          <div className="sticky left-0 z-20 flex shrink-0 items-center gap-2 border-r border-line bg-bg pr-2" style={{ width: LEFT, paddingLeft: 30 + r.depth * 20 }}>
            <span className="h-4 w-4 shrink-0 animate-pulse rounded-[3px] bg-bg-sunken" />
            <span className="h-3 animate-pulse rounded-[3px] bg-bg-sunken" style={{ width: `${40 + ((idx * 37) % 45)}%` }} />
          </div>
        </div>,
      );
    } else {
      visible.push(
        <div key={r.key} className="absolute left-0 flex border-b border-line" style={rowStyle(idx)}>
          <div className="sticky left-0 z-20 flex shrink-0 items-center gap-2 border-r border-line bg-bg pr-2 text-sm text-fg-subtle" style={{ width: LEFT, paddingLeft: 30 + r.depth * 20 }}>
            {r.kind === "error" && <span className="text-danger">{errorMessage(r.error)}</span>}
            {r.kind === "more" && (
              <Button size="sm" variant="subtle" onClick={() => onLoadMore(r.node, r.cursor)}>
                Cargar más{r.remaining != null ? ` (quedan ${fmtNum(r.remaining)})` : ""}
              </Button>
            )}
          </div>
        </div>,
      );
    }
  }

  return (
    <div ref={scrollRef} className="relative min-h-0 flex-1 overflow-auto border-t border-line"
         onScroll={(e) => { const tp = e.currentTarget.scrollTop; setView((v) => (v.top === tp ? v : { ...v, top: tp })); }}>
      <div className="relative" style={{ width: LEFT + width }}>
        <div className="sticky top-0 z-30 flex h-9 border-b border-line bg-bg">
          <div className="sticky left-0 z-10 flex shrink-0 items-center border-r border-line bg-bg px-3 text-xs font-semibold text-fg-subtle" style={{ width: LEFT }}>
            <span className="flex-1">Incidencia</span><span className="w-32">Equipo</span>
          </div>
          <div className="relative" style={{ width }}>
            {ticks.map((tk) => <div key={tk.left} className="absolute top-0 h-9 border-l border-line pl-2 text-xs capitalize leading-9 text-fg-subtle" style={{ left: tk.left }}>{tk.label}</div>)}
          </div>
        </div>
        <div ref={bodyRef} className="relative" style={{ height: n * ROW }}>
          {ticks.map((tk) => <div key={`g${tk.left}`} className="pointer-events-none absolute bottom-0 top-0 border-l border-line/60" style={{ left: LEFT + tk.left }} />)}
          <div className="pointer-events-none absolute bottom-0 top-0 z-[5] w-0.5 bg-warning" style={{ left: LEFT + todayLeft }} title="Hoy" />
          {visible}
          <svg className="pointer-events-none absolute z-10 overflow-visible" style={{ left: LEFT, top, width, height: Math.max(0, last - first) * ROW }} aria-hidden>
            <defs>
              <marker id="plan-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--text-subtlest)" /></marker>
              <marker id="plan-arrow-bad" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="var(--danger)" /></marker>
            </defs>
            {arrows.map((a) => (
              <g key={a.id} className={a.blocker.can_link ? "pointer-events-auto cursor-pointer" : undefined} onClick={() => a.blocker.can_link && onRemoveDep(a)}>
                <title>{a.title}</title>
                <path d={a.path} fill="none" stroke="transparent" strokeWidth="10" />
                <path d={a.path} fill="none" stroke={a.conflict ? "var(--danger)" : "var(--text-subtlest)"} strokeWidth={a.conflict ? 2 : 1.5}
                      strokeDasharray={a.conflict || a.stub ? "4 3" : undefined} markerEnd={`url(#${a.conflict ? "plan-arrow-bad" : "plan-arrow"})`} />
              </g>
            ))}
            {linking && <path d={`M${linking.x1},${linking.y1 - top} L${linking.x2},${linking.y2 - top}`} stroke="var(--brand)" strokeWidth="2" fill="none" markerEnd="url(#plan-arrow)" />}
          </svg>
        </div>
      </div>
      {!n && <div className="px-6 py-10 text-center text-sm text-fg-subtle">Ninguna incidencia cumple los filtros.</div>}
    </div>
  );
}

function TeamCell({ issue, team, options, onSelect }) {
  const label = team ? team.name : "—";
  if (!issue.can_edit) return <span className={cn("w-32 shrink-0 truncate text-xs", team?.deleted ? "text-fg-subtlest line-through" : "text-fg-subtle")} title={label}>{label}</span>;
  return (
    <Picker value={issue.team_id ?? NONE} options={options} width={240} placeholder="Buscar equipo" onSelect={onSelect}
            trigger={(
              <button className={cn("flex h-6 w-32 shrink-0 items-center gap-1 truncate rounded-[3px] px-1.5 text-left text-xs hover:bg-bg-pressed", team ? "text-fg" : "text-fg-subtlest", team?.deleted && "line-through")}
                      aria-label={`Equipo de ${issue.key}`}>
                <span className="truncate">{label}</span><ChevronDown size={12} className="ml-auto shrink-0" />
              </button>
            )} />
  );
}
