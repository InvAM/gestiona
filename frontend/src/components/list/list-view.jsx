"use client";

import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code2, Download, Layers, ListTree, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AskJql } from "@/components/ai/ai";
import { IssueModal } from "@/components/issue/issue-view";
import { BulkDialog } from "@/components/search/bulk-dialog";
import { JqlEditor } from "@/components/search/jql-editor";
import { useApp } from "@/components/shell/app-context";
import { useDebounced } from "@/components/board/filters-bar";
import { Button, PageSpinner } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/primitives";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, fieldRulesQuery, invalidateIssueViews, qk, useFieldRules, useMe, useMeta, useProjectMeta } from "@/lib/api/hooks";
import { useTransitionRunner } from "@/components/fields/transition-dialog";
import { fieldErrors } from "@/lib/fields";
import { fieldLabel, fieldCatalog, quickCreateMissing, transitionNeedsInput } from "@/lib/screens";
import { useRealtime } from "@/lib/realtime";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";
import { buildColumns, emptyReason, lockReason, shapeOf } from "./columns";
import {
  appendRows, dropRows, fetchRows, findRows, lk, patchRows, replaceRows, resetListConfig, saveListConfig,
  useChildren, useListConfig, useListGroups, useListMeta, useListPages,
} from "./data";
import { CreateRowButton, Grid } from "./grid";
import { DEFAULT_SORT, composeJql, joinJql, splitOrder, toggleSort } from "./jql";
import { ColumnChooser, GroupByPicker, QuickFilters, SearchBox, ShortcutsHelp } from "./toolbar";

const LOCAL = (key) => `gestiona-list:${key}`;
const MAX_DEPTH = 3;

function readLocal(projectKey) {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LOCAL(projectKey));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeLocal(projectKey, serialized) {
  try { window.localStorage.setItem(LOCAL(projectKey), serialized); } catch { /* storage full or blocked */ }
}

function clearLocal(projectKey) {
  try { window.localStorage.removeItem(LOCAL(projectKey)); } catch { /* ignore */ }
}

function defaultsFrom(listMeta) {
  return {
    columns: listMeta.columns.filter((c) => c.default).map((c) => ({ id: c.id, width: null })),
    group_by: null, jql: "", quick_filters: [], collapsed: [],
  };
}

/** Server config, else this browser's copy, else the defaults of the column catalogue. */
function resolveConfig(server, local, listMeta) {
  const base = defaultsFrom(listMeta);
  const cfg = server ?? local ?? base;
  const known = new Set(listMeta.columns.map((c) => c.id));
  const columns = (cfg.columns ?? []).filter((c) => known.has(c.id));
  const quickIds = new Set(listMeta.quick_filters.map((q) => q.id));
  const groups = new Set(listMeta.group_by.map((g) => g.value));
  return {
    columns: columns.length ? columns : base.columns,
    group_by: groups.has(cfg.group_by) ? cfg.group_by : null,
    jql: cfg.jql ?? "",
    quick_filters: (cfg.quick_filters ?? []).filter((q) => quickIds.has(q)),
    collapsed: cfg.collapsed ?? [],
  };
}

function groupLabelOf(groupBy, row) {
  switch (groupBy) {
    case "status": return { label: row.status.name, ref: row.status };
    case "assignee": return { label: row.assignee?.name ?? "Sin asignar", ref: row.assignee };
    case "priority": return { label: row.priority?.name ?? "", ref: row.priority };
    case "type": return { label: row.type.name, ref: row.type };
    case "sprint": return { label: row.sprint?.name ?? "Sin sprint", ref: row.sprint };
    case "epic": return { label: row.epic ? `${row.epic.key} ${row.epic.summary}` : "Sin épica", ref: row.epic };
    default: return { label: "", ref: null };
  }
}

export function ListView({ projectKey }) {
  const meta = useProjectMeta(projectKey);
  const listMeta = useListMeta(projectKey);
  const cfg = useListConfig(projectKey);
  const rules = useFieldRules(projectKey);
  if (meta.isPending || listMeta.isPending || cfg.isPending || rules.isPending) return <PageSpinner />;
  if (!meta.data || !listMeta.data) {
    return <EmptyState title="No se pudo cargar la lista" body={errorMessage(listMeta.error ?? meta.error)} />;
  }
  // a failing config endpoint falls back to this browser's copy
  const initial = resolveConfig(cfg.data?.config ?? null, cfg.data?.config ? null : readLocal(projectKey), listMeta.data);
  return <ListViewInner key={projectKey} projectKey={projectKey} meta={meta.data} listMeta={listMeta.data} initial={initial} />;
}

function ListViewInner({ projectKey, meta, listMeta, initial }) {
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const rt = useRealtime();
  const appMeta = useMeta();
  const me = useMe();
  const { openCreate } = useApp();
  const now = useNow();
  const fieldRules = useFieldRules(projectKey).data ?? null;
  const runner = useTransitionRunner();

  // ---------------------------------------------------------------- persisted layout
  const initialSplit = splitOrder(initial.jql);
  const [columns, setColumns] = useState(initial.columns);
  const [groupBy, setGroupBy] = useState(initial.group_by);
  const [collapsed, setCollapsed] = useState(initial.collapsed);
  const [where, setWhere] = useState(initialSplit.where);
  const [sort, setSort] = useState(initialSplit.sort ?? DEFAULT_SORT);
  const [quick, setQuick] = useState(initial.quick_filters);
  // ---------------------------------------------------------------- transient
  const [draftJql, setDraftJql] = useState(joinJql(initialSplit.where, initialSplit.sort ?? DEFAULT_SORT));
  const [jqlOpen, setJqlOpen] = useState(!!initialSplit.where);
  const [text, setText] = useState("");
  const [expanded, setExpanded] = useState([]);
  const [selected, setSelected] = useState(() => new Map());
  const [active, setActive] = useState(null);
  const [anchor, setAnchor] = useState(null);
  const [editing, setEditing] = useState(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [liveMsg, setLiveMsg] = useState("");
  const clip = useRef(null);
  const openIssue = params.get("selectedIssue");

  const config = {
    columns, group_by: groupBy || null, jql: joinJql(where, sort), quick_filters: quick, collapsed,
  };
  const serialized = JSON.stringify(config);
  const lastSaved = useRef(serialized);
  useEffect(() => {
    if (serialized === lastSaved.current) return;
    const body = JSON.parse(serialized);
    writeLocal(projectKey, serialized);
    qc.setQueryData(lk.config(projectKey), (old) => ({ ...(old ?? {}), config: body }));
    const t = setTimeout(() => {
      saveListConfig(projectKey, body).then(() => { lastSaved.current = serialized; }).catch(() => { /* kept locally */ });
    }, 700);
    return () => clearTimeout(t);
  }, [serialized, projectKey, qc]);

  // ---------------------------------------------------------------- query
  const search = useDebounced(text, 300);
  const quickJql = listMeta.quick_filters.filter((q) => quick.includes(q.id)).map((q) => q.jql);
  const jql = composeJql({ projectKey, where, quick: quickJql, text: search, sort });
  const pagesKey = lk.pages(projectKey, jql, groupBy);
  const pages = useListPages(projectKey, jql, groupBy, true);
  const groups = useListGroups(projectKey, jql, groupBy, true);
  const children = useChildren(projectKey, expanded);
  const jqlError = pages.error instanceof ApiError ? pages.error.message : groups.error instanceof ApiError ? groups.error.message : null;

  const boards = meta.boards ?? [];
  const sprintQs = useQueries({
    queries: boards.map((b) => ({
      queryKey: ["sprints", b.id, "open"],
      queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}/sprints", { params: { path: { board_id: b.id }, query: { state: "active,future" } } })),
      staleTime: 60_000,
    })),
  });
  const sprints = sprintQs.flatMap((q) => q.data ?? []).filter((s) => s.state !== "closed")
    .map((s) => ({ ...s, stateLabel: choiceLabel(appMeta.data?.sprint_states, s.state) }));

  const colDefs = buildColumns(listMeta.columns, meta);
  const teamCol = colDefs.get("team");
  const teamsQ = useQuery({
    queryKey: ["teams"],
    queryFn: () => unwrap(api.GET("/api/v1/teams")),
    enabled: !!teamCol?.field && columns.some((c) => c.id === "team"),
    staleTime: 60_000,
  });

  const topRows = [];
  const seenTop = new Set();
  const users = {};
  for (const p of pages.data?.pages ?? []) {
    Object.assign(users, p.users);
    for (const r of p.rows) if (!seenTop.has(r.id)) { seenTop.add(r.id); topRows.push(r); }
  }
  for (const q of children.values()) Object.assign(users, q.data?.users ?? {});
  const total = pages.data?.pages[0]?.total ?? 0;

  const ctx = {
    projectKey, meta, users, me: me.data, sprints, teams: teamCol?.field ? teamsQ.data : undefined, fieldRules,
    today: new Date(now).toISOString().slice(0, 10),
  };

  const visibleCols = columns.map((c) => {
    const d = colDefs.get(c.id);
    return d ? { ...d, width: c.width ?? d.width } : null;
  }).filter(Boolean);

  // ---------------------------------------------------------------- flatten rows
  const expandedSet = new Set(expanded);
  const collapsedSet = new Set(collapsed);
  const items = [];
  const pushRows = (rows, depth, path, ancestors) => {
    for (const r of rows) {
      const key = path ? `${path}/${r.id}` : String(r.id);
      const expandable = r.children_count > 0 && depth < MAX_DEPTH && !ancestors.has(r.id);
      const isOpen = expandable && expandedSet.has(r.id);
      items.push({ type: "row", key, row: r, depth, expandable, expanded: isOpen });
      if (!isOpen) continue;
      const q = children.get(r.id);
      if (!q?.data) items.push({ type: "loading", key: `${key}/…`, depth: depth + 1 });
      else pushRows(q.data.rows, depth + 1, key, new Set([...ancestors, r.id]));
    }
  };
  const grouping = !!groupBy && !!groups.data && !pages.isPlaceholderData && !groups.isPlaceholderData;
  if (grouping) {
    const byGroup = new Map();
    for (const r of topRows) {
      const k = r.group ?? null;
      if (!byGroup.has(k)) byGroup.set(k, []);
      byGroup.get(k).push(r);
    }
    const list = [...groups.data.groups];
    const known = new Set(list.map((g) => g.key));
    for (const [k, rows] of byGroup) if (!known.has(k)) list.push({ key: k, count: undefined, ...groupLabelOf(groupBy, rows[0]) });
    for (const g of list) {
      const rows = byGroup.get(g.key) ?? [];
      if (!rows.length) continue;
      const gk = `${groupBy}:${g.key ?? "none"}`;
      const isCollapsed = collapsedSet.has(gk);
      items.push({ type: "group", key: `g:${gk}`, gk, group: g, collapsed: isCollapsed, loaded: rows.length });
      if (!isCollapsed) pushRows(rows, 0, "", new Set());
    }
  } else {
    pushRows(topRows, 0, "", new Set());
  }
  if (pages.hasNextPage) items.push({ type: "more", key: "more", depth: 0 });
  const canCreate = meta.permissions.includes("create_issues") && !meta.project.is_archived;
  if (canCreate && pages.data) items.push({ type: "create", key: "create" });
  const rowItems = items.filter((it) => it.type === "row");
  const latest = new Map(rowItems.map((it) => [it.row.id, it.row]));
  const selectedRows = Array.from(selected.entries()).map(([id, r]) => latest.get(id) ?? r);

  // ---------------------------------------------------------------- refresh helpers
  const refreshIds = async (ids, { children: kids } = {}) => {
    if (!ids.length) return;
    try {
      for (let i = 0; i < ids.length; i += 500) {
        const chunk = ids.slice(i, i + 500);
        const res = await fetchRows(projectKey, chunk, groupBy);
        replaceRows(qc, projectKey, chunk, res.rows, res.users);
      }
    } catch { /* keep the optimistic state; the next refetch fixes it */ }
    qc.invalidateQueries({ queryKey: [...lk.all(projectKey), "groups"] });
    if (kids) qc.invalidateQueries({ queryKey: [...lk.all(projectKey), "children"] });
  };

  const announce = (msg) => {
    setLiveMsg(msg);
    toast.message(msg);
  };

  // ---------------------------------------------------------------- writes
  const writeCells = async (targets, value) => {
    if (!targets.length) return;
    const col = targets[0].col;
    const writable = targets.filter((t) => !lockReason(col, t.row, ctx));
    if (!writable.length) { announce(lockReason(col, targets[0].row, ctx)); return; }
    // a required field of the row's type can't be emptied
    const editable = writable.filter((t) => !emptyReason(col, t.row, ctx, value));
    if (!editable.length) { announce(emptyReason(col, writable[0].row, ctx, value)); return; }
    const isStatus = col.kind === "status";
    const transition = isStatus ? value?.transition : null;
    const toStatus = isStatus ? (transition ? transition.to : value) : null;
    const ok = editable.filter((t) => (isStatus
      ? t.row.status.id !== toStatus?.id
      : JSON.stringify(col.patch(value)) !== JSON.stringify(col.patch(col.value(t.row)))));
    const skipped = targets.length - editable.length;
    if (skipped) toast.warning(`${skipped} ${skipped === 1 ? "celda no se puede" : "celdas no se pueden"} editar y no se cambiaron`);
    if (!ok.length) return;
    const ids = ok.map((t) => t.row.id);
    const prev = new Map(ok.map((t) => [t.row.id, t.row]));
    const optimistic = isStatus ? (r) => ({ ...r, status: toStatus }) : (r) => col.apply(r, value);
    const rollback = (rids) => patchRows(qc, projectKey, rids, (r) => {
      const p = prev.get(r.id);
      return isStatus ? { ...r, status: p.status } : col.apply(r, col.value(p));
    });
    let request;
    if (transition && ok.length === 1) {
      // runs right away or opens the transition screen (fields, resolution, comment)
      const key = ok[0].row.key;
      request = () => runner.run(key, transition).then((d) => (d ? { failed: [] } : { failed: [], cancelled: true }));
      if (transitionNeedsInput(transition)) {
        try {
          const res = await request();
          if (!res.cancelled) {
            qc.invalidateQueries({ queryKey: qk.issue(key) });
            invalidateIssueViews(qc);
            await refreshIds([ok[0].row.id]);
          }
        } catch (e) {
          toast.error(errorMessage(e));
        }
        return;
      }
    } else if (isStatus) {
      request = () => unwrap(api.POST("/api/v1/issues/bulk", { body: { issue_ids: ids, transition_to_status_id: toStatus.id, notify: true } }));
    } else if (ok.length === 1) {
      const key = ok[0].row.key;
      request = () => unwrap(api.PATCH("/api/v1/issues/{key}", { params: { path: { key } }, body: col.patch(value) })).then(() => ({ failed: [] }));
    } else {
      request = () => unwrap(api.POST("/api/v1/issues/bulk", { body: { issue_ids: ids, changes: col.patch(value), notify: true } }));
    }
    patchRows(qc, projectKey, ids, optimistic);
    try {
      const res = await request();
      const catalog = fieldCatalog(fieldRules, meta, appMeta.data);
      const failed = new Map(res.failed.map((f) => [String(f.key), failMessage(f, catalog)]));
      const failedIds = ok.filter((t) => failed.has(t.row.key)).map((t) => t.row.id);
      if (failedIds.length) {
        rollback(failedIds);
        const first = Array.from(failed.entries()).slice(0, 3).map(([k, m]) => `${k}: ${m}`).join(" · ");
        toast.error(failedIds.length === ok.length && ok.length === 1 ? first : `${failedIds.length} de ${ok.length} no se pudieron cambiar. ${first}`);
      } else if (ok.length > 1) {
        toast.success(`${ok.length} incidencias actualizadas`);
      }
      for (const t of ok) qc.invalidateQueries({ queryKey: qk.issue(t.row.key) });
      invalidateIssueViews(qc);
      await refreshIds(ids, { children: col.kind === "parent" || col.kind === "type" });
    } catch (e) {
      rollback(ids);
      const fe = fieldErrors(e);
      toast.error(Object.keys(fe).length ? Object.values(fe).join(" · ") : errorMessage(e));
    }
  };

  const writeEach = async (targets, values) => {
    await Promise.allSettled(targets.map((t, i) => writeCells([t], values[i])));
  };

  const copyText = (targets) => {
    const col = targets[0].col;
    const text = targets.map((t) => (col.applies && !col.applies(t.row) ? "" : col.text(t.row, ctx))).join("\n");
    clip.current = { text, shape: shapeOf(col), values: targets.map((t) => col.value(t.row)) };
    setLiveMsg(`${targets.length} ${targets.length === 1 ? "celda copiada" : "celdas copiadas"}`);
    return text;
  };

  const paste = async (targets, text, lines) => {
    const col = targets[0].col;
    if (!col.editor) { announce(`«${col.label}» es de solo lectura`); return; }
    let values;
    const internal = clip.current;
    if (internal && internal.text.replace(/\r/g, "").replace(/\n$/, "") === text.replace(/\r/g, "").replace(/\n$/, "") && internal.shape === shapeOf(col)) {
      values = internal.values;
    } else {
      if (lines.length > 500) { toast.error("Pega como máximo 500 valores a la vez"); return; }
      try {
        values = await Promise.all(lines.map((l) => col.parse(l, ctx)));
      } catch (e) {
        toast.error(errorMessage(e));
        return;
      }
    }
    if (values.length === 1) await writeCells(targets, values[0]);
    else if (values.length === targets.length) await writeEach(targets, values);
    else toast.error(`Copiaste ${values.length} valores para ${targets.length} celdas: copia uno solo o selecciona tantas filas como valores.`);
  };

  const clearCells = (targets) => {
    if (!targets.length) return;
    writeCells(targets, targets[0].col.clear);
  };

  // ---------------------------------------------------------------- layout actions
  const setWidth = (id, w) => {
    const width = Math.max(40, Math.min(1200, Math.round(w)));
    setColumns((cs) => cs.map((c) => (c.id === id ? { ...c, width } : c)));
  };
  const moveCol = (id, targetId, edge) => {
    setColumns((cs) => {
      const from = cs.find((c) => c.id === id);
      if (!from || id === targetId) return cs;
      const rest = cs.filter((c) => c.id !== id);
      let i = rest.findIndex((c) => c.id === targetId);
      if (i < 0) return cs;
      if (edge === "right") i += 1;
      return [...rest.slice(0, i), from, ...rest.slice(i)];
    });
  };
  const moveBy = (id, delta) => setColumns((cs) => {
    const i = cs.findIndex((c) => c.id === id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= cs.length) return cs;
    const next = [...cs];
    [next[i], next[j]] = [next[j], next[i]];
    return next;
  });
  const hideCol = (id) => setColumns((cs) => (cs.length > 1 ? cs.filter((c) => c.id !== id) : cs));
  const toggleCol = (id, on) => setColumns((cs) => (on ? (cs.some((c) => c.id === id) ? cs : [...cs, { id, width: null }]) : cs.length > 1 ? cs.filter((c) => c.id !== id) : cs));
  const resetView = () => {
    const d = defaultsFrom(listMeta);
    setColumns(d.columns); setGroupBy(null); setCollapsed([]); setWhere(""); setSort(DEFAULT_SORT); setQuick([]);
    setDraftJql(joinJql("", DEFAULT_SORT)); setExpanded([]);
    clearLocal(projectKey);
    lastSaved.current = JSON.stringify({ ...d, jql: joinJql("", DEFAULT_SORT) });
    resetListConfig(projectKey).catch(() => { /* ignore */ });
    qc.setQueryData(lk.config(projectKey), { config: null, updated_at: null });
    toast.success("Vista restablecida");
  };

  const applyJql = (q) => {
    const s = splitOrder(q);
    setWhere(s.where);
    setSort(s.sort ?? DEFAULT_SORT);
    setDraftJql(joinJql(s.where, s.sort ?? DEFAULT_SORT));
  };
  const onSort = (field, add, dir, alt) => {
    const next = dir ? [{ field, dir }] : toggleSort(sort, field, add, alt);
    setSort(next);
    setDraftJql(joinJql(where, next));
  };
  const toggleGroup = (gk) => setCollapsed((c) => (c.includes(gk) ? c.filter((x) => x !== gk) : [...c, gk]));
  const toggleExpand = (id) => setExpanded((e) => (e.includes(id) ? e.filter((x) => x !== id) : [...e, id]));
  const allGroupKeys = items.filter((it) => it.type === "group").map((it) => it.gk);

  // ---------------------------------------------------------------- selection
  const allSelected = rowItems.length > 0 && rowItems.every((it) => selected.has(it.row.id));
  const toggleSelect = (row) => setSelected((m) => {
    const next = new Map(m);
    if (next.has(row.id)) next.delete(row.id); else next.set(row.id, row);
    return next;
  });
  const toggleAll = (on) => setSelected(() => {
    const next = new Map();
    if (on) for (const it of rowItems) next.set(it.row.id, it.row);
    return next;
  });
  const onBulkDone = (r) => {
    const ids = Array.from(selected.keys());
    setSelected(new Map());
    if (r?.updated?.length || r?.failed?.length) refreshIds(ids, { children: true });
  };

  // ---------------------------------------------------------------- issue modal
  const open = (key) => {
    const p = new URLSearchParams(params.toString());
    p.set("selectedIssue", key);
    router.push(`${pathname}?${p}`, { scroll: false });
  };
  const close = () => {
    const key = openIssue;
    const p = new URLSearchParams(params.toString());
    p.delete("selectedIssue");
    router.push(`${pathname}?${p}`, { scroll: false });
    const rows = findRows(qc, projectKey, (r) => r.key === key);
    if (rows.length) refreshIds(rows.map((r) => r.id), { children: true });
    else qc.invalidateQueries({ queryKey: pagesKey });
  };

  // ---------------------------------------------------------------- realtime
  const refreshRef = useRef(refreshIds);
  useEffect(() => { refreshRef.current = refreshIds; });
  useEffect(() => {
    const pagesKey = lk.pages(projectKey, jql, groupBy);
    let created = null;
    let pending = new Set();
    let timer = null;
    const flush = () => {
      timer = null;
      const ids = Array.from(pending);
      pending = new Set();
      refreshRef.current(ids);
    };
    const off = rt.on((event, payload) => {
      const key = typeof payload.key === "string" ? payload.key : null;
      if (event === "issue.updated" || event === "issue.ranked") {
        const rows = key ? findRows(qc, projectKey, (r) => r.key === key) : [];
        if (!rows.length) return;
        rows.forEach((r) => pending.add(r.id));
        if (!timer) timer = setTimeout(flush, 400);
      } else if (event === "issue.created") {
        clearTimeout(created);
        created = setTimeout(() => {
          qc.invalidateQueries({ queryKey: pagesKey });
          qc.invalidateQueries({ queryKey: [...lk.all(projectKey), "groups"] });
          qc.invalidateQueries({ queryKey: [...lk.all(projectKey), "children"] });
        }, 800);
      } else if (event === "issue.deleted") {
        if (key) dropRows(qc, projectKey, [key]);
        qc.invalidateQueries({ queryKey: [...lk.all(projectKey), "groups"] });
      } else if (event === "project.updated") {
        qc.invalidateQueries({ queryKey: lk.meta(projectKey) });
      }
    });
    return () => { off(); clearTimeout(timer); clearTimeout(created); };
  }, [rt, qc, projectKey, jql, groupBy]);

  // ---------------------------------------------------------------- quick create
  const createRow = {
    open: () => setCreateOpen(true),
    node: () => (createOpen
      ? <QuickCreate meta={meta} projectKey={projectKey} groupBy={groupBy} pagesKey={pagesKey} openCreate={openCreate} fieldRules={fieldRules}
                     onClose={() => {
                       setCreateOpen(false);
                       setActive({ key: "create", col: active?.col });
                       requestAnimationFrame(() => document.querySelector('[data-cell="create::*"]')?.focus());
                     }} />
      : <CreateRowButton onClick={() => setCreateOpen(true)} />),
  };

  const loadMore = () => {
    if (pages.hasNextPage && !pages.isFetchingNextPage) pages.fetchNextPage();
  };

  const exportHref = `/api/v1/search/export?jql=${encodeURIComponent(jql)}&columns=${encodeURIComponent(visibleCols.map((c) => c.id).join(","))}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-3 px-6 pb-3 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-medium">Lista</h1>
          <span className="text-sm text-fg-subtle" aria-live="polite">
            {pages.data ? `${total} ${total === 1 ? "incidencia" : "incidencias"}` : ""}
            {pages.isFetching && !pages.isFetchingNextPage && pages.data ? " · actualizando…" : ""}
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <ColumnChooser all={Array.from(colDefs.values())} visible={visibleCols.map((c) => c.id)} onToggle={toggleCol} onReset={resetView} />
            <Button asChild variant="subtle"><a href={exportHref}><Download size={16} />Exportar CSV</a></Button>
            <ShortcutsHelp />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SearchBox value={text} onChange={setText} />
          <GroupByPicker options={listMeta.group_by} value={groupBy} onChange={(v) => { setGroupBy(v); setCollapsed([]); }} />
          {groupBy && allGroupKeys.length > 0 && (
            <Button variant="subtle" size="sm" onClick={() => setCollapsed(collapsed.length ? [] : allGroupKeys)}>
              {collapsed.length ? "Expandir grupos" : "Contraer grupos"}
            </Button>
          )}
          {expanded.length > 0 && <Button variant="subtle" size="sm" onClick={() => setExpanded([])}><ListTree size={14} />Contraer jerarquía</Button>}
          <Button variant={jqlOpen ? "selected" : "subtle"} aria-pressed={jqlOpen} onClick={() => setJqlOpen((o) => !o)}><Code2 size={16} />JQL</Button>
          <QuickFilters filters={listMeta.quick_filters} value={quick}
                        onToggle={(id) => setQuick((q) => (q.includes(id) ? q.filter((x) => x !== id) : [...q, id]))} />
          {(quick.length > 0 || where || text) && (
            <Button variant="link" onClick={() => { setQuick([]); setText(""); applyJql(joinJql("", sort)); }}>Borrar filtros</Button>
          )}
        </div>
        {jqlOpen && (
          <div>
            <JqlEditor value={draftJql} onChange={setDraftJql} onSubmit={() => applyJql(draftJql)} error={jqlError} />
            <p className="mt-1 text-xs text-fg-subtlest">Se aplica dentro del proyecto {projectKey}, junto con los filtros rápidos. El orden de las columnas viaja como <code>ORDER BY</code>.</p>
            <AskJql projectKey={projectKey} onJql={(q) => applyJql(q.replace(new RegExp(`^\\s*project\\s*=\\s*"?${projectKey}"?\\s*(AND\\s+)?`, "i"), ""))} />
          </div>
        )}
        {!jqlOpen && jqlError && <p role="alert" className="text-sm text-danger">{jqlError}</p>}
      </div>

      <div className={cn("flex min-h-0 flex-1 flex-col", (pages.isPlaceholderData || groups.isPlaceholderData) && "opacity-60")}>
        {pages.isPending ? <PageSpinner /> : pages.error && !pages.data ? (
          <EmptyState title="No se pudo cargar la lista" body={errorMessage(pages.error)} />
        ) : (
          <>
            {!topRows.length && (
              <p className="px-6 pb-2 text-sm text-fg-subtle">No hay incidencias que coincidan con estos filtros.</p>
            )}
            <Grid items={items} cols={visibleCols} ctx={ctx} groupBy={groupBy} totalRows={total + items.length - rowItems.length}
                  sort={sort} active={active} setActive={setActive} anchor={anchor} setAnchor={setAnchor}
                  editing={editing} setEditing={setEditing} selected={selected} onToggleSelect={toggleSelect}
                  onToggleAll={toggleAll} allSelected={allSelected} onSort={onSort} onResize={setWidth} onMove={moveCol}
                  onMoveBy={moveBy} onHide={hideCol} onToggleGroup={toggleGroup} onToggleExpand={toggleExpand}
                  onCommit={writeCells} onClear={clearCells} onCopyText={copyText} onPaste={paste} onOpenIssue={open}
                  onLoadMore={loadMore} canLoadMore={!!pages.hasNextPage && !pages.isFetchingNextPage}
                  renderCreate={createRow} announce={announce} />
          </>
        )}
      </div>
      <div className="sr-only" aria-live="polite">{liveMsg}</div>

      {selected.size > 0 && (
        <div role="toolbar" aria-label="Acciones de selección"
             className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-md border border-line bg-bg px-4 py-2 text-sm shadow-lg">
          <b>{selected.size} {selected.size === 1 ? "seleccionada" : "seleccionadas"}</b>
          <Button size="sm" variant="primary" onClick={() => setBulkOpen(true)}><Layers size={14} />Cambio masivo</Button>
          <button className="inline-flex items-center gap-1 text-fg-subtle hover:text-fg" onClick={() => setSelected(new Map())}><X size={14} />Limpiar</button>
        </div>
      )}
      <BulkDialog open={bulkOpen} onOpenChange={setBulkOpen} rows={selectedRows} onDone={onBulkDone} />
      {runner.dialog}
      <IssueModal issueKey={openIssue} onClose={close} />
    </div>
  );
}

/* ------------------------------------------------------------------ quick create */

/** «KEY: message» of a bulk failure, with the field-level messages when there are some. */
function failMessage(f, catalog) {
  const fields = f.fields && typeof f.fields === "object" ? Object.entries(f.fields) : [];
  if (!fields.length) return String(f.message);
  return fields.map(([k, m]) => (String(m).includes("«") ? String(m) : `${fieldLabel(catalog, k)}: ${m}`)).join(" · ");
}

function QuickCreate({ meta, projectKey, groupBy, pagesKey, openCreate, onClose, fieldRules }) {
  const qc = useQueryClient();
  const types = meta.issue_types.filter((t) => t.level !== -1);
  const [typeId, setTypeId] = useState(() => (types.some((t) => t.id === meta.default_issue_type_id) ? meta.default_issue_type_id : types[0]?.id));
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef(null);
  useEffect(() => { input.current?.focus(); }, []);

  const submit = async () => {
    const s = summary.trim();
    if (!s || busy || !typeId) return;
    // the type asks for more than a summary: continue in the full dialog, like Jira
    const rules = fieldRules ?? await qc.fetchQuery(fieldRulesQuery(projectKey)).catch(() => null);
    if (quickCreateMissing(rules, meta, typeId).length) {
      openCreate({ projectKey, issueTypeId: typeId, summary: s });
      setSummary("");
      onClose();
      return;
    }
    setBusy(true);
    try {
      const issue = await unwrap(api.POST("/api/v1/issues", { body: { project: projectKey, issue_type_id: typeId, summary: s } }));
      const res = await fetchRows(projectKey, [issue.id], groupBy);
      appendRows(qc, projectKey, pagesKey, res.rows);
      replaceRows(qc, projectKey, [], [], res.users);
      qc.setQueryData(qk.issue(issue.key), issue);
      qc.invalidateQueries({ queryKey: [...lk.all(projectKey), "groups"] });
      invalidateIssueViews(qc);
      toast.success(`${issue.key} creada`);
      setSummary("");
      input.current?.focus();
    } catch (e) {
      if (e instanceof ApiError && e.code === "fields") {
        openCreate({ projectKey, issueTypeId: typeId, summary: s });
        onClose();
        return;
      }
      toast.error(errorMessage(e), {
        action: { label: "Formulario completo", onClick: () => openCreate({ projectKey, issueTypeId: typeId, summary: s }) },
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="flex h-full w-full items-center gap-2 px-2" onSubmit={(e) => { e.preventDefault(); submit(); }}
          onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); } }}>
      <select value={typeId ?? ""} onChange={(e) => setTypeId(Number(e.target.value))} aria-label="Tipo de incidencia"
              className="h-7 rounded-[3px] border-2 border-line bg-bg-subtle px-1 text-sm">
        {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
      <input ref={input} value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={255} aria-label="Resumen de la nueva incidencia"
             placeholder="¿Qué hay que hacer? (Intro crea, Esc cierra)" disabled={busy}
             className="h-7 min-w-0 max-w-xl flex-1 rounded-[3px] border-2 border-focus bg-bg px-2 text-sm outline-none" />
      <Button type="submit" size="sm" variant="primary" loading={busy} disabled={!summary.trim()}>Crear</Button>
      <Button type="button" size="sm" variant="subtle" onClick={onClose}>Cancelar</Button>
    </form>
  );
}
