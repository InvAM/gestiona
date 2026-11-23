"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Clock, MoreHorizontal, Plus, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useRef, useState, useEffect } from "react";
import { toast } from "sonner";
import { IssueModal } from "@/components/issue/issue-view";
import { Button, PageSpinner } from "@/components/ui/button";
import { Badge, EmptyState, Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/primitives";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, fieldRulesQuery, invalidateIssueViews, qk, useBoardData, useMeta, useProjectMeta } from "@/lib/api/hooks";
import { useTransitionRunner } from "@/components/fields/transition-dialog";
import { useApp } from "@/components/shell/app-context";
import { quickCreateMissing } from "@/lib/screens";
import { autoScrollForElements, useCardMonitor, useListDrop } from "@/lib/dnd";
import { BOARD_LANES, cn, pluralize } from "@/lib/utils";
import { useNow } from "@/lib/use-now";
import { BoardCard } from "./card";
import { BoardMissing } from "./create-board-dialog";
import { emptyFilters, FiltersBar, toQuery, useDebounced } from "./filters-bar";
import { CompleteSprintDialog, SprintFormDialog } from "./sprint-dialogs";

function InlineCreate({ projectKey, statusId, sprintId, meta }) {
  const qc = useQueryClient();
  const { openCreate } = useApp();
  const [open, setOpen] = useState(false);
  const [summary, setSummary] = useState("");
  const [saving, setSaving] = useState(false);
  const standard = meta.issue_types.filter((t) => t.level === 0);
  const typeId = standard.find((t) => t.id === meta.default_issue_type_id)?.id ?? standard[0]?.id;
  if (!meta.permissions.includes("create_issues") || !typeId) return null;
  const submit = async () => {
    if (!summary.trim()) return setOpen(false);
    const full = () => {
      openCreate({ projectKey, issueTypeId: typeId, summary: summary.trim(), statusId, sprintId: sprintId ?? undefined });
      setSummary("");
      setOpen(false);
    };
    setSaving(true);
    try {
      // the type asks for more than a summary: continue in the full dialog, like Jira
      const rules = await qc.fetchQuery(fieldRulesQuery(projectKey)).catch(() => null);
      if (quickCreateMissing(rules, meta, typeId, ["sprint"]).length) { full(); return; }
      await unwrap(api.POST("/api/v1/issues", { body: { project: projectKey, issue_type_id: typeId, summary: summary.trim(), status_id: statusId, sprint_id: sprintId } }));
      setSummary("");
      invalidateIssueViews(qc);
    } catch (e) {
      if (e instanceof ApiError && e.code === "fields") full();
      else toast.error(errorMessage(e));
    } finally { setSaving(false); }
  };
  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="flex w-full items-center gap-1 rounded-[3px] px-2 py-1.5 text-sm font-medium text-fg-subtle hover:bg-bg-hover">
        <Plus size={16} />Crear incidencia
      </button>
    );
  }
  return (
    <div className="rounded-[3px] bg-bg p-2 shadow-raised">
      <textarea autoFocus rows={2} value={summary} disabled={saving} placeholder="¿Qué hay que hacer?"
                onChange={(e) => setSummary(e.target.value)} onBlur={submit}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } if (e.key === "Escape") { setSummary(""); setOpen(false); } }}
                className="w-full resize-none bg-transparent text-sm outline-none" />
    </div>
  );
}

function BoardColumn({ col, cards, allowed, dragging, onOpen, meta, sprintId, first, lane }) {
  const ref = useRef(null);
  const listId = `${lane}|${col.id}`;
  const over = useListDrop(ref, listId, { canDrop: useCallback(() => allowed, [allowed]) });
  const exceeded = col.max_issues != null && cards.length > col.max_issues;
  const below = col.min_issues != null && cards.length < col.min_issues;
  return (
    <div ref={ref}
         className={cn("flex min-h-24 w-[272px] shrink-0 flex-col gap-1.5 rounded-[3px] p-1.5 transition-colors",
                       exceeded ? "bg-danger-subtle" : below ? "bg-warning-subtle" : "bg-bg-column",
                       dragging && !allowed && "opacity-50",
                       dragging && allowed && "ring-2 ring-inset ring-focus/40",
                       over && allowed && "bg-bg-selected")}>
      {cards.map((c) => <BoardCard key={c.id} card={c} list={listId} onOpen={onOpen} disabled={!meta.permissions.includes("transition_issues") && !meta.permissions.includes("edit_issues")} />)}
      {first && lane === "all" && <InlineCreate projectKey={meta.project.key} statusId={col.status_ids[0]} sprintId={sprintId} meta={meta} />}
    </div>
  );
}

export function BoardView({ boardId, projectKey }) {
  const appMeta = useMeta();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const qc = useQueryClient();
  const meta = useProjectMeta(projectKey);
  const [filters, setFilters] = useState(emptyFilters);
  const fq = useDebounced(toQuery(filters));
  const sprintId = undefined;
  const now = useNow();
  const data = useBoardData(boardId, { ...fq, sprint_id: sprintId });
  const [allowedStatuses, setAllowedStatuses] = useState(null);
  const [completeOpen, setCompleteOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [swimlanes, setSwimlanes] = useState(null);
  const scrollRef = useRef(null);
  const selected = search.get("selectedIssue");

  const openIssue = (key) => {
    const p = new URLSearchParams(search.toString());
    p.set("selectedIssue", key);
    router.push(`${pathname}?${p}`, { scroll: false });
  };
  const closeIssue = () => {
    const p = new URLSearchParams(search.toString());
    p.delete("selectedIssue");
    router.push(p.size ? `${pathname}?${p}` : pathname, { scroll: false });
  };

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    return autoScrollForElements({ element: el });
  }, [data.data]);

  const board = data.data?.board;
  const lanesMode = swimlanes ?? board?.swimlanes ?? "none";
  const columns = useMemo(() => board?.columns ?? [], [board]);
  const statusToCol = useMemo(() => {
    const m = new Map();
    columns.forEach((c) => c.status_ids.forEach((s) => m.set(s, c.id)));
    return m;
  }, [columns]);

  const issues = useMemo(() => data.data?.issues ?? [], [data.data]);
  const people = useMemo(() => {
    const m = new Map();
    issues.forEach((i) => i.assignee && m.set(i.assignee.id, i.assignee));
    return [...m.values()];
  }, [issues]);
  const epics = useMemo(() => {
    const m = new Map();
    issues.forEach((i) => i.epic && m.set(i.epic.id, i.epic));
    return [...m.values()];
  }, [issues]);

  // swimlanes
  const lanes = useMemo(() => {
    if (lanesMode === "assignee") {
      const groups = new Map();
      for (const i of issues) {
        const id = i.assignee ? String(i.assignee.id) : "none";
        if (!groups.has(id)) groups.set(id, { id, title: i.assignee?.name ?? "Sin asignar", cards: [] });
        groups.get(id).cards.push(i);
      }
      return [...groups.values()].sort((a, b) => (a.id === "none" ? 1 : b.id === "none" ? -1 : a.title.localeCompare(b.title)));
    }
    if (lanesMode === "epic") {
      const groups = new Map();
      for (const i of issues) {
        const id = i.epic ? String(i.epic.id) : "none";
        if (!groups.has(id)) groups.set(id, { id, title: i.epic ? `${i.epic.key} ${i.epic.summary}` : "Incidencias sin épica", cards: [] });
        groups.get(id).cards.push(i);
      }
      return [...groups.values()].sort((a, b) => (a.id === "none" ? 1 : b.id === "none" ? -1 : 0));
    }
    if (lanesMode === "priority") {
      const groups = new Map();
      for (const i of issues) {
        const id = String(i.priority.id);
        if (!groups.has(id)) groups.set(id, { id, title: i.priority.name, cards: [], pos: i.priority.position });
        groups.get(id).cards.push(i);
      }
      return [...groups.values()].sort((a, b) => a.pos - b.pos);
    }
    return [{ id: "all", title: "", cards: issues }];
  }, [issues, lanesMode]);

  const [collapsedLanes, setCollapsedLanes] = useState(new Set());

  const runner = useTransitionRunner();
  const dragActive = useRef(false);
  const onStart = useCallback(async (d) => {
    dragActive.current = true;
    setAllowedStatuses(null); // everything droppable until transitions arrive
    try {
      const card = issues.find((i) => i.id === d.issueId);
      const key = card?.key;
      if (!key) return;
      const ts = await qc.fetchQuery({
        queryKey: qk.transitions(key),
        queryFn: () => unwrap(api.GET("/api/v1/issues/{key}/transitions", { params: { path: { key } } })),
        staleTime: 10_000,
      });
      // the drag may have ended while we were waiting
      if (dragActive.current) setAllowedStatuses([card.status.id, ...ts.map((t) => t.to.id)]);
    } catch { /* server validates on drop anyway */ }
  }, [issues, qc]);
  const onEnd = useCallback(() => {
    dragActive.current = false;
    setTimeout(() => setAllowedStatuses(null), 0);
  }, []);

  const onDrop = useCallback(async ({ data: d, list, targetIssueId, edge }) => {
    const colId = Number(list.split("|")[1]);
    const col = columns.find((c) => c.id === colId);
    const card = issues.find((i) => i.id === d.issueId);
    if (!col || !card) return;
    const sameCol = statusToCol.get(card.status.id) === col.id;
    const key = qk.board(boardId, { ...fq, sprint_id: sprintId });
    const prev = qc.getQueryData(key);
    const targetStatus = sameCol ? card.status.id
      : col.status_ids.find((s) => allowedStatuses?.includes(s)) ?? col.status_ids[0];
    // optimistic: move card
    if (prev) {
      const st = meta.data?.statuses.find((s) => s.id === targetStatus);
      let list2 = prev.issues.filter((i) => i.id !== card.id);
      const moved = { ...card, status: st ?? card.status };
      const idx = targetIssueId ? list2.findIndex((i) => i.id === targetIssueId) : -1;
      if (idx >= 0) list2.splice(edge === "bottom" ? idx + 1 : idx, 0, moved);
      else list2 = [...list2, moved];
      qc.setQueryData(key, { ...prev, issues: list2 });
    }
    try {
      if (!sameCol) {
        // like Jira: a transition with a screen (or required fields) opens it before moving
        const ts = qc.getQueryData(qk.transitions(card.key)) ?? await qc.fetchQuery({
          queryKey: qk.transitions(card.key),
          queryFn: () => unwrap(api.GET("/api/v1/issues/{key}/transitions", { params: { path: { key: card.key } } })),
        }).catch(() => []);
        const t = ts.find((x) => x.to.id === targetStatus);
        if (t) {
          // posts right away, or opens the transition screen (also when a validator fails)
          const done = await runner.run(card.key, t);
          if (!done) { if (prev) qc.setQueryData(key, prev); return; }
        } else {
          await unwrap(api.POST("/api/v1/issues/{key}/transitions", { params: { path: { key: card.key } }, body: { to_status_id: targetStatus } }));
        }
      }
      if (targetIssueId && targetIssueId !== card.id) {
        await unwrap(api.POST("/api/v1/issues/rank", {
          body: edge === "bottom" ? { issue_ids: [card.id], after_id: targetIssueId } : { issue_ids: [card.id], before_id: targetIssueId },
        }));
      }
    } catch (e) {
      if (prev) qc.setQueryData(key, prev);
      toast.error(errorMessage(e));
    } finally {
      invalidateIssueViews(qc, card.key);
    }
  }, [columns, issues, statusToCol, boardId, fq, sprintId, qc, allowedStatuses, meta.data, runner]);

  useCardMonitor(onDrop, onStart, onEnd);

  if (data.isPending || meta.isPending) return <PageSpinner />;
  // e.g. the board was moved to the papelera: offer another board, «Crear tablero» or the issues
  if (data.error instanceof ApiError && data.error.status === 404) return <BoardMissing projectKey={projectKey} meta={meta.data} />;
  if (!data.data || !meta.data || !board) return <EmptyState title="No se pudo cargar el tablero" body={data.error ? errorMessage(data.error) : undefined} />;
  const boards = meta.data.boards;
  const sprint = data.data.sprint;
  const isScrum = board.kind === "scrum";
  const daysLeft = sprint?.end_date ? Math.ceil((new Date(sprint.end_date).getTime() - now) / 864e5) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-6 pt-5">
        <div className="text-sm text-fg-subtle"><Link href="/projects" className="hover:underline">Proyectos</Link> / <Link href={`/projects/${projectKey}`} className="hover:underline">{meta.data.project.name}</Link></div>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-medium">{isScrum ? (sprint?.name ?? "Sin sprint activo") : board.name}</h1>
          {boards.length > 1 && (
            <Menu>
              <MenuTrigger asChild><Button variant="subtle" size="sm" aria-label="Cambiar de tablero">{board.name}<ChevronDown size={14} /></Button></MenuTrigger>
              <MenuContent align="start">
                {boards.map((b) => (
                  <MenuItem key={b.id} onSelect={() => router.push(`/projects/${projectKey}/boards/${b.id}`)}>
                    <span className="flex w-4 justify-center">{b.id === board.id && <Check size={14} />}</span>
                    {b.name}<span className="ml-auto pl-3 text-xs text-fg-subtle">{choiceLabel(appMeta.data?.board_kinds, b.kind)}</span>
                  </MenuItem>
                ))}
              </MenuContent>
            </Menu>
          )}
          <div className="ml-auto flex items-center gap-2">
            {isScrum && sprint && daysLeft !== null && (
              <span className="flex items-center gap-1 text-sm text-fg-subtle"><Clock size={16} />
                {daysLeft >= 0 ? pluralize(daysLeft, "día restante", "días restantes") : `Venció hace ${pluralize(-daysLeft, "día", "días")}`}</span>
            )}
            {isScrum && sprint && board.can_manage_sprints && <Button onClick={() => setCompleteOpen(true)}>Completar sprint</Button>}
            <Menu>
              <MenuTrigger asChild><Button variant="subtle" size="icon" aria-label="Opciones del tablero"><MoreHorizontal size={18} /></Button></MenuTrigger>
              <MenuContent align="end">
                {isScrum && sprint && board.can_manage_sprints && <MenuItem onSelect={() => setEditOpen(true)}>Editar sprint</MenuItem>}
                {board.can_manage && <MenuItem onSelect={() => router.push(`/projects/${projectKey}/settings/board?board=${board.id}`)}><Settings size={16} />Configurar tablero</MenuItem>}
              </MenuContent>
            </Menu>
          </div>
        </div>
        {isScrum && sprint?.goal && <p className="mt-1 text-sm text-fg-subtle"><b>Objetivo:</b> {sprint.goal}</p>}
        <div className="mt-4">
          <FiltersBar value={filters} onChange={setFilters} board={board} meta={meta.data} people={people} epics={epics}
                      extra={<Menu>
                        <MenuTrigger asChild><Button variant="subtle">Agrupar: {choiceLabel(appMeta.data?.board_swimlanes, lanesMode)}<ChevronDown size={14} /></Button></MenuTrigger>
                        <MenuContent align="end">
                          {(appMeta.data?.board_swimlanes ?? []).filter((o) => BOARD_LANES.includes(o.value)).map((o) => (
                            <MenuItem key={o.value} onSelect={() => setSwimlanes(o.value)}>{o.label}</MenuItem>
                          ))}
                        </MenuContent>
                      </Menu>} />
        </div>
        {data.data.unmapped_status_ids.length > 0 && board.can_manage && (
          <div className="mt-3 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">
            Hay estados del flujo sin columna; sus incidencias no aparecen. <Link className="text-link underline" href={`/projects/${projectKey}/settings/board?board=${board.id}`}>Configurar columnas</Link>
          </div>
        )}
      </div>

      {isScrum && !sprint ? (
        <EmptyState title="No hay ningún sprint activo"
                    body="Planifica un sprint en el backlog e inícialo para ver sus incidencias aquí."
                    action={<Button variant="primary" asChild><Link href={`/projects/${projectKey}/boards/${boardId}/backlog`}>Ir al backlog</Link></Button>} />
      ) : (
        <div ref={scrollRef} className="mt-4 min-h-0 flex-1 overflow-auto px-6 pb-6">
          {/* column headers */}
          <div className="sticky top-0 z-10 flex gap-2 bg-bg pb-1">
            {columns.map((c) => {
              const n = issues.filter((i) => statusToCol.get(i.status.id) === c.id).length;
              return (
                <div key={c.id} className="flex w-[272px] shrink-0 items-center gap-2 rounded-t-[3px] bg-bg-column px-3 pt-3 pb-1 text-xs font-semibold uppercase text-fg-subtle">
                  <span className="truncate">{c.name}</span><span>{n}</span>
                  {c.max_issues != null && <Badge className={cn("ml-auto", n > c.max_issues && "bg-danger text-white")}>Máx: {c.max_issues}</Badge>}
                </div>
              );
            })}
          </div>
          {lanes.map((lane) => (
            <div key={lane.id} className="mb-2">
              {lanesMode !== "none" && (
                <button className="mb-1 flex items-center gap-2 py-1 text-sm font-semibold" onClick={() => setCollapsedLanes((s) => { const n = new Set(s); if (n.has(lane.id)) n.delete(lane.id); else n.add(lane.id); return n; })}>
                  <ChevronDown size={16} className={cn("transition-transform", collapsedLanes.has(lane.id) && "-rotate-90")} />
                  {lane.title}<span className="font-normal text-fg-subtlest">({pluralize(lane.cards.length, "incidencia", "incidencias")})</span>
                </button>
              )}
              {!collapsedLanes.has(lane.id) && (
                <div className="flex gap-2">
                  {columns.map((c, idx) => (
                    <BoardColumn key={c.id} col={c} lane={lane.id} first={idx === 0} meta={meta.data} sprintId={sprint?.id}
                                 cards={lane.cards.filter((i) => statusToCol.get(i.status.id) === c.id)}
                                 dragging={allowedStatuses !== null}
                                 allowed={allowedStatuses === null || c.status_ids.some((s) => allowedStatuses.includes(s))}
                                 onOpen={openIssue} />
                  ))}
                </div>
              )}
            </div>
          ))}
          {issues.length === 0 && <p className="py-6 text-center text-sm text-fg-subtlest">{filters !== emptyFilters ? "Ninguna incidencia coincide con los filtros." : "Aún no hay incidencias en este tablero."}</p>}
        </div>
      )}
      {sprint && (
        <>
          <CompleteSprintDialog sprint={sprint} issues={issues} futureSprints={data.data.future_sprints} boardId={boardId} open={completeOpen} onOpenChange={setCompleteOpen} />
          <SprintFormDialog sprint={sprint} mode="edit" open={editOpen} onOpenChange={setEditOpen} />
        </>
      )}
      <IssueModal issueKey={selected} onClose={closeIssue} />
      {runner.dialog}
    </div>
  );
}
