"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, MoreHorizontal, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { EpicTag, PointsBadge } from "@/components/board/card";
import { BoardMissing } from "@/components/board/create-board-dialog";
import { emptyFilters, FiltersBar, toQuery, useDebounced } from "@/components/board/filters-bar";
import { CompleteSprintDialog, SprintFormDialog } from "@/components/board/sprint-dialogs";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { IssueModal } from "@/components/issue/issue-view";
import { Button, PageSpinner } from "@/components/ui/button";
import {
  Avatar, Confirm, EmptyState, Lozenge, Menu, MenuContent, MenuItem, MenuTrigger, Tip,
} from "@/components/ui/primitives";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { fieldRulesQuery, invalidateIssueViews, qk, useBacklog, useProjectMeta } from "@/lib/api/hooks";
import { useApp } from "@/components/shell/app-context";
import { quickCreateMissing } from "@/lib/screens";
import { autoScrollForElements, useCardDnd, useCardMonitor, useListDrop } from "@/lib/dnd";
import { cn, fmtDate, fmtPoints, pluralize } from "@/lib/utils";

function sumPoints(cards, cat) {
  return cards.filter((c) => !cat || c.status.category === cat)
    .reduce((s, c) => s + (c.story_points ? parseFloat(c.story_points) : 0), 0);
}

function Row({ card, list, selected, selectedIds, onClick, canDrag }) {
  const ref = useRef(null);
  const ids = selected && selectedIds.length > 1 ? selectedIds : [card.id];
  const { dragging, edge } = useCardDnd(ref, { type: "issue", issueId: card.id, issueIds: ids, sourceList: list }, { disabled: !canDrag });
  return (
    <div className="relative">
      {edge === "top" && <div className="absolute -top-px left-0 right-0 z-10 h-0.5 bg-brand" />}
      <div ref={ref} role="button" tabIndex={0} onClick={(e) => onClick(e, card)}
           className={cn("flex h-10 cursor-pointer items-center gap-2 border-b border-line bg-bg px-3 text-sm hover:bg-bg-hover",
                         selected && "bg-bg-selected hover:bg-bg-selected", dragging && "opacity-40", card.flagged && "bg-warning-subtle")}>
        <IssueTypeIcon type={card.type} />
        <span className={cn("shrink-0 text-fg-subtle", card.status.category === "done" && "line-through")}>{card.key}</span>
        <span className="min-w-0 flex-1 truncate">{card.summary}</span>
        <EpicTag epic={card.epic} />
        <Lozenge category={card.status.category} className="max-w-32">{card.status.name}</Lozenge>
        <PointsBadge value={card.story_points} className="min-w-6" />
        <PriorityIcon priority={card.priority} />
        <Avatar user={card.assignee} size="sm" />
      </div>
      {edge === "bottom" && <div className="absolute -bottom-px left-0 right-0 z-10 h-0.5 bg-brand" />}
    </div>
  );
}

function InlineCreate({ meta, sprintId }) {
  const qc = useQueryClient();
  const { openCreate } = useApp();
  const [open, setOpen] = useState(false);
  const types = meta.issue_types.filter((t) => t.level === 0);
  const [typeId, setTypeId] = useState(types.find((t) => t.id === meta.default_issue_type_id)?.id ?? types[0]?.id);
  const [summary, setSummary] = useState("");
  const full = () => {
    openCreate({ projectKey: meta.project.key, issueTypeId: typeId, summary: summary.trim(), sprintId: sprintId ?? undefined });
    setSummary("");
    setOpen(false);
  };
  const create = useMutation({
    mutationFn: async () => {
      // the type asks for more than a summary: continue in the full dialog, like Jira
      const rules = await qc.fetchQuery(fieldRulesQuery(meta.project.key)).catch(() => null);
      if (quickCreateMissing(rules, meta, typeId, ["sprint"]).length) return "full";
      return unwrap(api.POST("/api/v1/issues", { body: { project: meta.project.key, issue_type_id: typeId, summary: summary.trim(), sprint_id: sprintId } }));
    },
    onSuccess: (r) => { if (r === "full") { full(); return; } setSummary(""); invalidateIssueViews(qc); },
    onError: (e) => { if (e instanceof ApiError && e.code === "fields") full(); else toast.error(errorMessage(e)); },
  });
  if (!meta.permissions.includes("create_issues")) return null;
  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="flex h-9 w-full items-center gap-1 px-3 text-sm font-medium text-fg-subtle hover:bg-bg-hover">
        <Plus size={16} />Crear incidencia
      </button>
    );
  }
  const type = types.find((t) => t.id === typeId);
  return (
    <div className="flex h-10 items-center gap-2 border-2 border-focus bg-bg px-2">
      <Menu>
        <MenuTrigger asChild><button className="flex items-center gap-0.5 rounded p-1 hover:bg-bg-hover"><IssueTypeIcon type={type} /><ChevronDown size={12} /></button></MenuTrigger>
        <MenuContent>{types.map((t) => <MenuItem key={t.id} onSelect={() => setTypeId(t.id)}><IssueTypeIcon type={t} />{t.name}</MenuItem>)}</MenuContent>
      </Menu>
      <input autoFocus value={summary} placeholder="¿Qué hay que hacer?" disabled={create.isPending}
             onChange={(e) => setSummary(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter" && summary.trim()) create.mutate(); if (e.key === "Escape") setOpen(false); }}
             onBlur={() => { if (!summary.trim()) setOpen(false); }}
             className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
      <span className="text-xs text-fg-subtlest">Enter para crear</span>
    </div>
  );
}

function Section({ id, title, subtitle, cards, meta, sprint, actions, selectedIds, onRowClick, canDrag, collapsedInit }) {
  const [collapsed, setCollapsed] = useState(!!collapsedInit);
  const ref = useRef(null);
  const over = useListDrop(ref, id);
  const todo = sumPoints(cards, "todo"), prog = sumPoints(cards, "in_progress"), done = sumPoints(cards, "done");
  return (
    <section className={cn("rounded-[3px] bg-bg-sunken p-2", over && "ring-2 ring-focus")}>
      <div className="flex items-center gap-2 px-1 pb-2">
        <button onClick={() => setCollapsed(!collapsed)} className="flex min-w-0 items-center gap-1 text-sm">
          <ChevronDown size={16} className={cn("shrink-0 transition-transform", collapsed && "-rotate-90")} />
          <span className="truncate font-semibold">{title}</span>
        </button>
        {subtitle && <span className="truncate text-sm text-fg-subtle">{subtitle}</span>}
        <span className="text-sm text-fg-subtlest">({pluralize(cards.length, "incidencia", "incidencias")})</span>
        <div className="ml-auto flex items-center gap-1">
          <Tip content="Por hacer"><span className="rounded-full bg-[var(--lz-todo-bg)] px-1.5 text-xs font-semibold text-[var(--lz-todo-fg)]">{fmtPoints(todo)}</span></Tip>
          <Tip content="En curso"><span className="rounded-full bg-[var(--lz-progress-bg)] px-1.5 text-xs font-semibold text-[var(--lz-progress-fg)]">{fmtPoints(prog)}</span></Tip>
          <Tip content="Listo"><span className="rounded-full bg-[var(--lz-done-bg)] px-1.5 text-xs font-semibold text-[var(--lz-done-fg)]">{fmtPoints(done)}</span></Tip>
          {actions}
        </div>
      </div>
      {sprint?.goal && !collapsed && <p className="px-7 pb-2 text-xs text-fg-subtle">{sprint.goal}</p>}
      {!collapsed && (
        <div ref={ref} className="overflow-hidden rounded-[3px] border border-line bg-bg">
          {cards.length ? cards.map((c) => (
            <Row key={c.id} card={c} list={id} selected={selectedIds.includes(c.id)} selectedIds={selectedIds}
                 canDrag={canDrag} onClick={(e, card) => onRowClick(e, card, cards)} />
          )) : (
            <div className="m-2 rounded-[3px] border-2 border-dashed border-line px-4 py-5 text-center text-sm text-fg-subtle">
              {sprint ? "Planifica un sprint arrastrando incidencias aquí desde el backlog." : "El backlog está vacío."}
            </div>
          )}
          <InlineCreate meta={meta} sprintId={sprint?.id} />
        </div>
      )}
    </section>
  );
}

export function BacklogView({ boardId, projectKey }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const qc = useQueryClient();
  const meta = useProjectMeta(projectKey);
  const [filters, setFilters] = useState(emptyFilters);
  const fq = useDebounced(toQuery(filters));
  const data = useBacklog(boardId, fq);
  const [selectedIds, setSelectedIds] = useState([]);
  const [lastClicked, setLastClicked] = useState(null);
  const [startSprint, setStartSprint] = useState(null);
  const [editSprint, setEditSprint] = useState(null);
  const [completeSprint, setCompleteSprint] = useState(null);
  const [deleteSprint, setDeleteSprint] = useState(null);
  const scrollRef = useRef(null);
  const selected = search.get("selectedIssue");

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    return autoScrollForElements({ element: el });
  }, [data.data]);

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

  const onRowClick = (e, c, list) => {
    if (e.shiftKey && lastClicked !== null) {
      const a = list.findIndex((x) => x.id === lastClicked), b = list.findIndex((x) => x.id === c.id);
      if (a >= 0 && b >= 0) {
        const [s, t] = a < b ? [a, b] : [b, a];
        setSelectedIds(list.slice(s, t + 1).map((x) => x.id));
        return;
      }
    }
    if (e.metaKey || e.ctrlKey) {
      setSelectedIds((ids) => (ids.includes(c.id) ? ids.filter((x) => x !== c.id) : [...ids, c.id]));
      setLastClicked(c.id);
      return;
    }
    setSelectedIds([c.id]);
    setLastClicked(c.id);
    openIssue(c.key);
  };

  const allCards = useMemo(() => {
    const d = data.data;
    return d ? [...d.sprints.flatMap((s) => s.issues), ...d.backlog] : [];
  }, [data.data]);

  const onDrop = useCallback(async ({ data: d, list, targetIssueId, edge }) => {
    const targetSprint = list === "backlog" ? null : Number(list.replace("sprint-", ""));
    const key = qk.backlog(boardId, fq);
    const prev = qc.getQueryData(key);
    const ids = d.issueIds;
    if (prev) {
      const moving = allCards.filter((c) => ids.includes(c.id)).map((c) => ({ ...c, sprint_id: targetSprint }));
      const strip = (arr) => arr.filter((c) => !ids.includes(c.id));
      const insert = (arr) => {
        const out = strip(arr);
        const idx = targetIssueId ? out.findIndex((c) => c.id === targetIssueId) : -1;
        if (idx >= 0) out.splice(edge === "bottom" ? idx + 1 : idx, 0, ...moving);
        else out.push(...moving);
        return out;
      };
      qc.setQueryData(key, {
        ...prev,
        sprints: prev.sprints.map((s) => ({ ...s, issues: s.id === targetSprint ? insert(s.issues) : strip(s.issues) })),
        backlog: targetSprint === null ? insert(prev.backlog) : strip(prev.backlog),
      });
    }
    try {
      // if dropped at end of a list, rank after its last card
      let before, after;
      if (targetIssueId) {
        if (edge === "bottom") after = targetIssueId; else before = targetIssueId;
      } else if (prev) {
        const listCards = targetSprint === null ? prev.backlog : prev.sprints.find((s) => s.id === targetSprint)?.issues ?? [];
        const last = [...listCards].reverse().find((c) => !ids.includes(c.id));
        if (last) after = last.id;
      }
      await unwrap(api.POST("/api/v1/boards/{board_id}/move", {
        params: { path: { board_id: boardId } },
        body: { issue_ids: ids, sprint_id: targetSprint, before_id: before ?? null, after_id: after ?? null },
      }));
    } catch (e) {
      if (prev) qc.setQueryData(key, prev);
      toast.error(errorMessage(e));
    } finally {
      invalidateIssueViews(qc);
    }
  }, [boardId, fq, qc, allCards]);

  useCardMonitor(onDrop);

  const createSprint = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/boards/{board_id}/sprints", { params: { path: { board_id: boardId } }, body: {} })),
    onSuccess: () => invalidateIssueViews(qc),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const delSprint = useMutation({
    mutationFn: (id) => unwrap(api.DELETE("/api/v1/sprints/{sid}", { params: { path: { sid: id } } })),
    onSuccess: () => { setDeleteSprint(null); invalidateIssueViews(qc); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (data.isPending || meta.isPending) return <PageSpinner />;
  // [Z] a board in the papelera answers 404: offer another board, «Crear tablero» or the issues
  if (data.error?.status === 404 && meta.data) return <BoardMissing projectKey={meta.data.project.key} meta={meta.data} backlog />;
  if (!data.data || !meta.data) return <EmptyState title="No se pudo cargar el backlog" body={data.error ? errorMessage(data.error) : undefined} />;
  const { board, sprints, backlog, epics } = data.data;
  const people = Array.from(new Map(allCards.filter((c) => c.assignee).map((c) => [c.assignee.id, c.assignee])).values());
  const canDrag = meta.data.permissions.includes("edit_issues");
  const canSprints = board.can_manage_sprints;
  const hasActive = sprints.some((s) => s.state === "active");
  const isScrum = board.kind === "scrum";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-6 pt-5">
        <div className="text-sm text-fg-subtle"><Link href="/projects" className="hover:underline">Proyectos</Link> / <Link href={`/projects/${projectKey}`} className="hover:underline">{meta.data.project.name}</Link></div>
        <h1 className="mt-1 text-2xl font-medium">Backlog</h1>
        <div className="mt-4">
          <FiltersBar value={filters} onChange={setFilters} board={board} meta={meta.data} people={people} epics={epics} />
        </div>
        {selectedIds.length > 1 && (
          <div className="mt-3 flex items-center gap-3 rounded-[3px] bg-bg-selected px-3 py-2 text-sm">
            <b>{pluralize(selectedIds.length, "incidencia seleccionada", "incidencias seleccionadas")}</b>
            <span className="text-fg-subtle">Arrástralas juntas a un sprint o al backlog.</span>
            <Button variant="link" size="sm" onClick={() => setSelectedIds([])}>Deseleccionar</Button>
          </div>
        )}
      </div>
      <div ref={scrollRef} className="mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto px-6 pb-10">
        {isScrum && sprints.map((s) => (
          <Section key={s.id} id={`sprint-${s.id}`} meta={meta.data} sprint={s} cards={s.issues} canDrag={canDrag}
                   selectedIds={selectedIds} onRowClick={onRowClick}
                   title={s.name}
                   subtitle={s.start_date ? `${fmtDate(s.start_date, "d MMM")} – ${fmtDate(s.end_date, "d MMM")}` : undefined}
                   actions={canSprints && <>
                     {s.state === "active"
                       ? <Button size="sm" onClick={() => setCompleteSprint(s)}>Completar sprint</Button>
                       : <Tip content={hasActive ? "Ya hay un sprint activo" : s.issues.length ? "" : "Agrega incidencias para iniciar"}>
                           <span><Button size="sm" disabled={hasActive || !s.issues.length} onClick={() => setStartSprint(s)}>Iniciar sprint</Button></span>
                         </Tip>}
                     <Menu>
                       <MenuTrigger asChild><Button variant="subtle" size="icon-sm" aria-label="Opciones del sprint"><MoreHorizontal size={16} /></Button></MenuTrigger>
                       <MenuContent align="end">
                         <MenuItem onSelect={() => setEditSprint(s)}>Editar sprint</MenuItem>
                         {s.state === "future" && <MenuItem danger onSelect={() => setDeleteSprint(s)}>Eliminar sprint</MenuItem>}
                       </MenuContent>
                     </Menu>
                   </>} />
        ))}
        <Section id="backlog" meta={meta.data} cards={backlog} title="Backlog" canDrag={canDrag}
                 selectedIds={selectedIds} onRowClick={onRowClick}
                 actions={isScrum && canSprints && <Button size="sm" loading={createSprint.isPending} onClick={() => createSprint.mutate()}>Crear sprint</Button>} />
      </div>
      {startSprint && <SprintFormDialog sprint={startSprint} mode="start" issueCount={startSprint ? sprints.find((s) => s.id === startSprint.id)?.issues.length : 0}
                                        open onOpenChange={(o) => !o && setStartSprint(null)} />}
      {editSprint && <SprintFormDialog sprint={editSprint} mode="edit" open onOpenChange={(o) => !o && setEditSprint(null)} />}
      {completeSprint && <CompleteSprintDialog sprint={completeSprint} boardId={boardId} open onOpenChange={(o) => !o && setCompleteSprint(null)}
                                               issues={sprints.find((s) => s.id === completeSprint.id)?.issues ?? []}
                                               futureSprints={sprints.filter((s) => s.state === "future")} />}
      <Confirm open={!!deleteSprint} onOpenChange={(o) => !o && setDeleteSprint(null)} danger confirmLabel="Eliminar"
               title={`¿Eliminar ${deleteSprint?.name}?`} loading={delSprint.isPending}
               body="Las incidencias del sprint volverán al backlog."
               onConfirm={() => deleteSprint && delSprint.mutate(deleteSprint.id)} />
      <IssueModal issueKey={selected} onClose={closeIssue} />
    </div>
  );
}
