"use client";

import { draggable, dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { attachClosestEdge } from "@atlaskit/pragmatic-drag-and-drop-hitbox/closest-edge/attach-closest-edge";
import {
  ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ChevronDown, ChevronRight, EyeOff, MoreHorizontal, Plus,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { Spinner } from "@/components/ui/button";
import { Avatar, Badge, Lozenge, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from "@/components/ui/primitives";
import { combine, extractClosestEdge } from "@/lib/dnd";
import { cn } from "@/lib/utils";
import { lockReason } from "./columns";
import { CellEditor } from "./editors";
import { sortOf } from "./jql";

export const ROW_H = 36;
const HEADER_H = 36;
const SELECT_W = 40;
const OVERSCAN = 8;
const INDENT = 20;

export const cellId = (item, colId) => (item.type === "row" ? `${item.key}::${colId}` : `${item.key}::*`);

/* ------------------------------------------------------------------ header */

function HeaderCell({ col, index, count, sort, onSort, onResize, onMove, onMoveBy, onHide }) {
  const ref = useRef(null);
  const handle = useRef(null);
  const [edge, setEdge] = useState(null);
  const [dragging, setDragging] = useState(false);
  const moveRef = useRef(onMove);
  useEffect(() => { moveRef.current = onMove; });
  useEffect(() => {
    const el = ref.current;
    if (!el || !handle.current) return;
    return combine(
      draggable({
        element: el, dragHandle: handle.current,
        getInitialData: () => ({ type: "list-column", id: col.id }),
        onDragStart: () => setDragging(true), onDrop: () => setDragging(false),
      }),
      dropTargetForElements({
        element: el,
        canDrop: ({ source }) => source.data.type === "list-column" && source.data.id !== col.id,
        getData: ({ input, element }) => attachClosestEdge({ type: "list-column-target", id: col.id }, { input, element, allowedEdges: ["left", "right"] }),
        onDrag: ({ self }) => setEdge(extractClosestEdge(self.data)),
        onDragLeave: () => setEdge(null),
        onDrop: ({ source, self }) => { setEdge(null); moveRef.current(source.data.id, col.id, extractClosestEdge(self.data)); },
      }),
    );
  }, [col.id]);

  // a custom field can also be sorted by its name in the JQL box
  const alt = col.custom_field_id ? col.label : null;
  const s = sortOf(sort, col.sort, alt);
  const resizeStart = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startW = col.width;
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    const move = (ev) => onResize(col.id, startW + ev.clientX - startX);
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  };
  return (
    <div ref={ref} role="columnheader" aria-colindex={index + 2} aria-sort={s ? (s.dir === "ASC" ? "ascending" : "descending") : col.sort ? "none" : undefined}
         style={{ width: col.width }}
         className={cn("group/h relative flex h-full shrink-0 items-center border-r border-line px-1 text-xs font-semibold text-fg-subtle",
                       dragging && "opacity-40")}>
      {edge && <span className={cn("absolute inset-y-0 z-10 w-0.5 bg-brand", edge === "left" ? "-left-px" : "-right-px")} />}
      <div ref={handle} className="flex min-w-0 flex-1 cursor-grab items-center active:cursor-grabbing">
        {col.sort ? (
          <button type="button" onClick={(e) => onSort(col.sort, e.shiftKey, undefined, alt)} title="Ordenar (Mayús+clic: orden secundario)"
                  className="flex min-w-0 items-center gap-1 rounded-[3px] px-1 py-0.5 text-left hover:bg-bg-hover hover:text-fg">
            <span className="truncate">{col.label}</span>
            {s && (s.dir === "ASC" ? <ArrowUp size={12} className="shrink-0" /> : <ArrowDown size={12} className="shrink-0" />)}
            {s && sort.length > 1 && <span className="text-[10px] text-fg-subtlest">{s.index + 1}</span>}
          </button>
        ) : <span className="truncate px-1">{col.label}</span>}
      </div>
      <Menu>
        <MenuTrigger asChild>
          <button type="button" aria-label={`Opciones de la columna ${col.label}`}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[3px] text-fg-subtle opacity-0 hover:bg-bg-hover focus:opacity-100 group-hover/h:opacity-100 data-[state=open]:opacity-100">
            <MoreHorizontal size={14} />
          </button>
        </MenuTrigger>
        <MenuContent align="end">
          {col.sort && <>
            <MenuItem onSelect={() => onSort(col.sort, false, "ASC")}><ArrowUp size={14} />Orden ascendente</MenuItem>
            <MenuItem onSelect={() => onSort(col.sort, false, "DESC")}><ArrowDown size={14} />Orden descendente</MenuItem>
            <MenuSeparator />
          </>}
          <MenuItem disabled={index === 0} onSelect={() => onMoveBy(col.id, -1)}><ArrowLeft size={14} />Mover a la izquierda</MenuItem>
          <MenuItem disabled={index === count - 1} onSelect={() => onMoveBy(col.id, 1)}><ArrowRight size={14} />Mover a la derecha</MenuItem>
          <MenuSeparator />
          <MenuItem disabled={count <= 1} onSelect={() => onHide(col.id)}><EyeOff size={14} />Ocultar columna</MenuItem>
        </MenuContent>
      </Menu>
      <div role="separator" aria-orientation="vertical" aria-label={`Ancho de ${col.label}`} tabIndex={0}
           aria-valuenow={col.width} aria-valuemin={40} aria-valuemax={1200}
           onPointerDown={resizeStart}
           onKeyDown={(e) => {
             if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); onResize(col.id, col.width - 16); }
             if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); onResize(col.id, col.width + 16); }
           }}
           className="absolute -right-1 top-0 z-10 h-full w-2 cursor-col-resize touch-none outline-none hover:bg-brand/40 focus-visible:bg-brand" />
    </div>
  );
}

/* ------------------------------------------------------------------ group header */

function GroupLabel({ groupBy, group }) {
  const ref = group.ref;
  if (!ref) return <span className="truncate">{group.label}</span>;
  switch (groupBy) {
    case "status": return <Lozenge category={ref.category}>{group.label}</Lozenge>;
    case "assignee": return <span className="flex min-w-0 items-center gap-1.5"><Avatar user={ref} size="xs" /><span className="truncate">{group.label}</span></span>;
    case "priority": return <span className="flex min-w-0 items-center gap-1.5"><PriorityIcon priority={ref} /><span className="truncate">{group.label}</span></span>;
    case "type": return <span className="flex min-w-0 items-center gap-1.5"><IssueTypeIcon type={ref} /><span className="truncate">{group.label}</span></span>;
    case "epic": return <span className="flex min-w-0 items-center gap-1.5"><span className="h-3 w-3 shrink-0 rounded-sm" style={{ background: ref.color }} /><span className="truncate">{group.label}</span></span>;
    default: return <span className="truncate">{group.label}</span>;
  }
}

/* ------------------------------------------------------------------ grid */

/**
 * Virtualized, keyboard-driven grid (role="grid"). `items` is the flattened list of
 * group headers, issue rows (with hierarchy depth), loaders and the quick-create row.
 */
export function Grid({
  items, cols, ctx, groupBy, totalRows, sort, active, setActive, anchor, setAnchor, editing, setEditing,
  selected, onToggleSelect, onToggleAll, allSelected, onSort, onResize, onMove, onMoveBy, onHide,
  onToggleGroup, onToggleExpand, onCommit, onClear, onCopyText, onPaste, onOpenIssue, onLoadMore,
  canLoadMore, renderCreate, announce,
}) {
  const scroller = useRef(null);
  const hasFocus = useRef(false);
  const [view, setView] = useState({ top: 0, height: 600 });

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setView((v) => ({ ...v, height: el.clientHeight })));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = items.length;
  const first = Math.max(0, Math.floor(view.top / ROW_H) - OVERSCAN);
  const last = Math.min(n, Math.ceil((view.top + view.height) / ROW_H) + OVERSCAN);
  const totalWidth = SELECT_W + cols.reduce((s, c) => s + c.width, 0);

  // infinite loading: ask for the next page when the end is close
  useEffect(() => {
    if (canLoadMore && last >= n - 5) onLoadMore();
  }, [canLoadMore, last, n, onLoadMore]);

  const indexOf = (key) => items.findIndex((it) => it.key === key);
  const activeIndex = active ? indexOf(active.key) : -1;
  const colIndex = active ? Math.max(0, cols.findIndex((c) => c.id === active.col)) : 0;

  // range (same column, between anchor and active)
  const range = new Set();
  if (anchor && active && anchor.col === active.col) {
    const a = indexOf(anchor.key);
    if (a >= 0 && activeIndex >= 0) {
      for (let i = Math.min(a, activeIndex); i <= Math.max(a, activeIndex); i++) {
        if (items[i].type === "row") range.add(items[i].key);
      }
    }
  }
  const rangeTargets = () => {
    const col = cols[colIndex];
    if (!col) return [];
    const keys = range.size ? range : active ? new Set([active.key]) : new Set();
    return items.filter((it) => it.type === "row" && keys.has(it.key)).map((it) => ({ row: it.row, col, key: it.key }));
  };

  // keep keyboard focus on the active cell after moves, edits and re-renders
  useEffect(() => {
    if (!hasFocus.current || editing || !active) return;
    const item = items.find((it) => it.key === active.key);
    if (!item) return;
    const el = scroller.current?.querySelector(`[data-cell="${CSS.escape(cellId(item, active.col))}"]`);
    if (el && document.activeElement !== el && !el.contains(document.activeElement)) el.focus();
  }, [active, editing, items, first]);

  const ensureVisible = (i) => {
    const el = scroller.current;
    if (!el) return;
    const top = i * ROW_H;
    const bodyH = el.clientHeight - HEADER_H;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + ROW_H > el.scrollTop + bodyH) el.scrollTop = top + ROW_H - bodyH;
  };

  const go = (i, c, extend) => {
    if (!n) return;
    const ni = Math.max(0, Math.min(n - 1, i));
    const nc = Math.max(0, Math.min(cols.length - 1, c));
    const item = items[ni];
    hasFocus.current = true;
    ensureVisible(ni);
    const next = { key: item.key, col: cols[nc]?.id };
    if (extend && item.type === "row") {
      if (!anchor || anchor.col !== next.col) setAnchor(active && items[activeIndex]?.type === "row" ? { key: active.key, col: next.col } : next);
    } else {
      setAnchor(null);
    }
    setActive(next);
  };

  const startEdit = (item, col, initialText) => {
    if (item?.type !== "row" || !col) return;
    if (col.kind === "key") { onOpenIssue(item.row.key); return; }
    const why = lockReason(col, item.row, ctx);
    if (why) { announce(why); return; }
    if (col.editor === "toggle") { onCommit([{ row: item.row, col }], !col.value(item.row), null); return; }
    setEditing({ key: item.key, col: col.id, initialText });
  };

  const onKeyDown = (e) => {
    if (editing || e.defaultPrevented || !e.target.matches?.("[data-cell]")) return;
    const item = items[activeIndex];
    const col = cols[colIndex];
    const page = Math.max(1, Math.floor((view.height - HEADER_H) / ROW_H) - 1);
    const mod = e.ctrlKey || e.metaKey;
    switch (e.key) {
      case "ArrowDown": e.preventDefault(); go(activeIndex + 1, colIndex, e.shiftKey); return;
      case "ArrowUp": e.preventDefault(); go(activeIndex - 1, colIndex, e.shiftKey); return;
      case "ArrowRight":
        e.preventDefault();
        if (item?.type === "group") { if (item.collapsed) onToggleGroup(item.gk); return; }
        if (item?.type === "row" && e.altKey) { if (item.expandable && !item.expanded) onToggleExpand(item.row.id); return; }
        go(activeIndex, colIndex + 1);
        return;
      case "ArrowLeft":
        e.preventDefault();
        if (item?.type === "group") { if (!item.collapsed) onToggleGroup(item.gk); return; }
        if (item?.type === "row" && e.altKey) { if (item.expanded) onToggleExpand(item.row.id); return; }
        go(activeIndex, colIndex - 1);
        return;
      case "Home": e.preventDefault(); go(mod ? 0 : activeIndex, 0); return;
      case "End": e.preventDefault(); go(mod ? n - 1 : activeIndex, cols.length - 1); return;
      case "PageDown": e.preventDefault(); go(activeIndex + page, colIndex, e.shiftKey); return;
      case "PageUp": e.preventDefault(); go(activeIndex - page, colIndex, e.shiftKey); return;
      case "Tab": return; // leave the grid
      case "Escape": if (anchor) { e.preventDefault(); setAnchor(null); } return;
      case "Enter":
      case "F2":
        e.preventDefault();
        if (item?.type === "group") onToggleGroup(item.gk);
        else if (item?.type === "create") renderCreate.open();
        else if (item?.type === "row") startEdit(item, col);
        return;
      case " ":
        e.preventDefault();
        if (item?.type === "row") onToggleSelect(item.row);
        else if (item?.type === "group") onToggleGroup(item.gk);
        return;
      case "Delete":
      case "Backspace": {
        if (item?.type !== "row" || !col) return;
        e.preventDefault();
        if (col.clear === undefined) { announce(`«${col.label}» no se puede vaciar`); return; }
        onClear(rangeTargets());
        return;
      }
      default:
        if (!mod && !e.altKey && e.key.length === 1 && item?.type === "row" && col &&
            ["text", "number", "duration", "textarea"].includes(col.editor)) {
          e.preventDefault();
          startEdit(item, col, e.key);
        }
    }
  };

  const onCopy = (e) => {
    if (editing || !e.target.matches?.("[data-cell]")) return;
    const targets = rangeTargets();
    if (!targets.length) return;
    e.preventDefault();
    const text = onCopyText(targets);
    e.clipboardData.setData("text/plain", text);
  };
  const onPasteEvt = (e) => {
    if (editing || !e.target.matches?.("[data-cell]")) return;
    const text = e.clipboardData.getData("text/plain");
    if (!text) return;
    let targets = rangeTargets();
    if (!targets.length) return;
    e.preventDefault();
    const lines = text.replace(/\r/g, "").replace(/\n$/, "").split("\n");
    if (lines.length > 1 && targets.length === 1) {
      // spreadsheet-style: fill down from the active cell, one line per row
      const col = targets[0].col;
      targets = [];
      for (let i = activeIndex; i < n && targets.length < lines.length; i++) {
        if (items[i].type === "row") targets.push({ row: items[i].row, col, key: items[i].key });
      }
    }
    onPaste(targets, text, lines);
  };

  const clickCell = (e, item, col) => {
    hasFocus.current = true;
    const next = { key: item.key, col: col?.id ?? active?.col ?? cols[0]?.id };
    if (e.shiftKey && item.type === "row" && active) {
      e.preventDefault();
      setAnchor(anchor && anchor.col === next.col ? anchor : { key: active.key, col: next.col });
    } else {
      setAnchor(null);
    }
    setActive(next);
  };

  const anyExpandable = items.some((x) => x.expandable || x.depth > 0);
  const tabRow = activeIndex >= 0 ? activeIndex : 0; // roving tabindex entry point
  const rows = [];
  for (let i = first; i < last; i++) {
    const item = items[i];
    const top = i * ROW_H;
    const isActiveRow = i === activeIndex;
    const common = {
      role: "row", "aria-rowindex": i + 2,
      style: { top, height: ROW_H, width: totalWidth },
      className: "absolute left-0 flex border-b border-line",
    };
    if (item.type === "group") {
      rows.push(
        <div key={item.key} {...common} aria-expanded={!item.collapsed} className={cn(common.className, "bg-bg-sunken")}>
          <div role="gridcell" aria-colspan={cols.length + 1} data-cell={cellId(item)} tabIndex={i === tabRow ? 0 : -1}
               onClick={(e) => { clickCell(e, item); onToggleGroup(item.gk); }}
               className={cn("sticky left-0 flex h-full cursor-pointer items-center gap-2 px-2 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus)]",
                             isActiveRow && "ring-2 ring-inset ring-[var(--focus)]")}>
            {item.collapsed ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
            <GroupLabel groupBy={groupBy} group={item.group} />
            <Badge>{item.group.count ?? item.loaded}</Badge>
            {item.group.count > item.loaded && !item.collapsed && <span className="text-xs font-normal text-fg-subtlest">{item.loaded} cargadas</span>}
          </div>
        </div>,
      );
      continue;
    }
    if (item.type === "loading" || item.type === "more") {
      rows.push(
        <div key={item.key} {...common}>
          <div role="gridcell" aria-colspan={cols.length + 1} data-cell={cellId(item)} tabIndex={i === tabRow ? 0 : -1}
               style={{ paddingLeft: SELECT_W + item.depth * INDENT }}
               className="sticky left-0 flex h-full items-center gap-2 text-sm text-fg-subtlest outline-none">
            <Spinner className="h-4 w-4" />{item.type === "more" ? "Cargando más incidencias…" : "Cargando…"}
          </div>
        </div>,
      );
      continue;
    }
    if (item.type === "create") {
      rows.push(
        <div key={item.key} {...common} className={cn(common.className, "border-b-0")}>
          <div role="gridcell" aria-colspan={cols.length + 1} data-cell={cellId(item)} tabIndex={i === tabRow ? 0 : -1}
               onClick={(e) => clickCell(e, item)}
               className={cn("sticky left-0 flex h-full w-full items-center outline-none", isActiveRow && "ring-2 ring-inset ring-[var(--focus)]")}>
            {renderCreate.node(isActiveRow)}
          </div>
        </div>,
      );
      continue;
    }
    const row = item.row;
    const picked = selected.has(row.id);
    rows.push(
      <div key={item.key} {...common} aria-selected={picked} aria-level={item.depth + 1} aria-expanded={item.expandable ? item.expanded : undefined}
           className={cn(common.className, "group/r bg-bg hover:bg-bg-hover", picked && "bg-bg-selected hover:bg-bg-selected", row.is_archived && "text-fg-subtle")}>
        <div role="gridcell" className={cn("sticky left-0 z-[1] flex h-full shrink-0 items-center justify-center border-r border-line bg-inherit")}
             style={{ width: SELECT_W }}>
          <input type="checkbox" data-grid-skip="" tabIndex={-1} aria-label={`Seleccionar ${row.key}`} className="h-4 w-4 accent-[var(--brand)]"
                 checked={picked} onChange={() => onToggleSelect(row)} />
        </div>
        {cols.map((col, ci) => {
          const isActive = isActiveRow && ci === colIndex;
          const inRange = range.has(item.key) && ci === colIndex;
          const isEditing = editing && editing.key === item.key && editing.col === col.id;
          const why = lockReason(col, row, ctx);
          const na = col.applies && !col.applies(row);
          return (
            <div key={col.id} role="gridcell" aria-colindex={ci + 2} data-cell={cellId(item, col.id)} tabIndex={i === tabRow && ci === colIndex ? 0 : -1}
                 aria-readonly={why ? true : undefined} aria-selected={inRange || undefined}
                 title={why && col.editor && !na ? why : undefined}
                 onMouseDown={(e) => { if (e.shiftKey) e.preventDefault(); }}
                 onClick={(e) => clickCell(e, item, col)}
                 onDoubleClick={() => startEdit(item, col)}
                 style={{ width: col.width, paddingLeft: ci === 0 ? 8 + item.depth * INDENT : undefined }}
                 className={cn("relative flex h-full shrink-0 items-center gap-1 overflow-hidden border-r border-line px-2 text-sm outline-none",
                               col.align === "right" && "justify-end",
                               inRange && "bg-[var(--brand-subtle)]",
                               isActive && "z-[2] ring-2 ring-inset ring-[var(--focus)]")}>
              {ci === 0 && (item.expandable ? (
                <button type="button" data-grid-skip="" tabIndex={-1} aria-label={item.expanded ? "Contraer" : "Expandir"}
                        onClick={(e) => { e.stopPropagation(); onToggleExpand(row.id); }}
                        className="-ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-[3px] text-fg-subtle hover:bg-bg-pressed">
                  {item.expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
              ) : anyExpandable ? <span className="w-4 shrink-0" /> : null)}
              {na ? <span className="text-fg-subtlest">—</span>
                : col.kind === "key" ? (
                  <button type="button" data-grid-skip="" tabIndex={-1} onClick={(e) => { e.stopPropagation(); onOpenIssue(row.key); }}
                          className={cn("truncate text-link hover:underline", row.status.category === "done" && "line-through")}>{row.key}</button>
                ) : col.display(row, ctx)}
              {row.is_archived && ci === 0 && <span className="ml-1 shrink-0 rounded-[3px] bg-bg-sunken px-1 text-[10px] font-bold uppercase text-fg-subtle">Archivada</span>}
              {isEditing && (
                <CellEditor col={col} row={row} ctx={ctx} initialText={editing.initialText}
                            onCancel={() => { hasFocus.current = true; setEditing(null); }}
                            onCommit={(value, move) => {
                              if (move) hasFocus.current = true;
                              setEditing(null);
                              onCommit([{ row, col }], value, move);
                              if (move === "down") go(i + 1, ci);
                              else if (move === "up") go(i - 1, ci);
                              else if (move === "right") go(i, ci + 1);
                              else if (move === "left") go(i, ci - 1);
                            }} />
              )}
            </div>
          );
        })}
      </div>,
    );
  }

  return (
    <div ref={scroller} role="grid" aria-rowcount={totalRows + 1} aria-colcount={cols.length + 1} aria-multiselectable="true"
         aria-label="Lista de incidencias"
         onScroll={(e) => { const t = e.currentTarget.scrollTop; setView((v) => (v.top === t ? v : { ...v, top: t })); }}
         onKeyDown={onKeyDown} onCopy={onCopy} onPaste={onPasteEvt}
         onFocus={(e) => {
           hasFocus.current = true;
           if (!active && n && e.target.matches?.("[data-cell]")) setActive({ key: items[0].key, col: cols[0]?.id });
         }}
         onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) hasFocus.current = false; }}
         className="relative min-h-0 flex-1 overflow-auto border-t border-line">
      <div role="rowgroup" className="sticky top-0 z-10" style={{ width: totalWidth }}>
        <div role="row" aria-rowindex={1} className="flex border-b-2 border-line bg-bg" style={{ height: HEADER_H }}>
          <div role="columnheader" aria-colindex={1} className="sticky left-0 z-[1] flex shrink-0 items-center justify-center border-r border-line bg-bg" style={{ width: SELECT_W }}>
            <input type="checkbox" aria-label="Seleccionar todas las cargadas" className="h-4 w-4 accent-[var(--brand)]"
                   checked={allSelected} onChange={(e) => onToggleAll(e.target.checked)} />
          </div>
          {cols.map((col, i) => (
            <HeaderCell key={col.id} col={col} index={i} count={cols.length} sort={sort} onSort={onSort}
                        onResize={onResize} onMove={onMove} onMoveBy={onMoveBy} onHide={onHide} />
          ))}
        </div>
      </div>
      <div role="rowgroup" className="relative" style={{ height: n * ROW_H, width: totalWidth }}>
        {rows}
      </div>
    </div>
  );
}

export function CreateRowButton({ onClick }) {
  return (
    <button type="button" data-grid-skip="" tabIndex={-1} onClick={onClick}
            className="flex h-full w-full items-center gap-2 px-3 text-sm text-fg-subtle hover:bg-bg-hover">
      <Plus size={16} />Crear incidencia
    </button>
  );
}
