"use client";

import { Flag, GitBranch } from "lucide-react";
import { useRef } from "react";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { Avatar, Tip } from "@/components/ui/primitives";
import { useCardDnd } from "@/lib/dnd";
import { cn, fmtPoints } from "@/lib/utils";

export function EpicTag({ epic }) {
  if (!epic) return null;
  return (
    <span className="inline-flex max-w-full items-center truncate rounded-[3px] px-1 text-[11px] font-semibold uppercase leading-4"
          style={{ backgroundColor: `${epic.color}26`, color: epic.color }} title={epic.summary}>
      {epic.summary}
    </span>
  );
}

export function PointsBadge({ value, className }) {
  const p = fmtPoints(value);
  if (p === null) return null;
  return <Tip content="Puntos de historia"><span className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-bg-sunken px-1.5 text-xs font-semibold text-fg-subtle", className)}>{p}</span></Tip>;
}

export function BoardCard({ card, list, onOpen, selected, onSelectToggle, disabled }) {
  const ref = useRef(null);
  const { dragging, edge } = useCardDnd(ref, { type: "issue", issueId: card.id, issueIds: [card.id], sourceList: list }, { disabled });
  const done = card.status.category === "done";
  const overdue = card.due_date && !done && card.due_date < new Date().toISOString().slice(0, 10);
  return (
    <div className="relative">
      {edge === "top" && <div className="absolute -top-[5px] left-0 right-0 z-10 h-0.5 rounded bg-brand" />}
      <div ref={ref} role="button" tabIndex={0}
           onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey) onSelectToggle?.(card.id, true); else onOpen(card.key); }}
           onKeyDown={(e) => e.key === "Enter" && onOpen(card.key)}
           className={cn("group cursor-pointer rounded-[3px] bg-bg p-3 shadow-raised transition-colors hover:bg-bg-subtle",
                         card.flagged && "bg-warning-subtle hover:bg-warning-subtle",
                         selected && "outline-2 outline-brand",
                         dragging && "opacity-40")}>
        <div className={cn("mb-2 text-sm text-fg", done && "text-fg-subtle")}>{card.summary}</div>
        {(card.epic || card.labels.length > 0) && (
          <div className="mb-2 flex flex-wrap gap-1">
            <EpicTag epic={card.epic} />
            {card.labels.slice(0, 3).map((l) => <span key={l} className="rounded-[3px] border border-line px-1 text-[11px] text-fg-subtle">{l}</span>)}
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <IssueTypeIcon type={card.type} />
          {card.flagged && <Flag size={14} className="fill-danger text-danger" />}
          <span className={cn("text-xs font-semibold text-fg-subtle", done && "line-through")}>{card.key}</span>
          {card.subtasks_total > 0 && (
            <Tip content={`${card.subtasks_done} de ${card.subtasks_total} subtareas listas`}>
              <span className="inline-flex items-center gap-0.5 text-xs text-fg-subtlest"><GitBranch size={12} />{card.subtasks_done}/{card.subtasks_total}</span>
            </Tip>
          )}
          {overdue && <span className="rounded-[3px] bg-danger-subtle px-1 text-[11px] font-semibold text-danger">Vencida</span>}
          <span className="ml-auto flex items-center gap-1.5">
            <PointsBadge value={card.story_points} />
            <PriorityIcon priority={card.priority} />
            <Avatar user={card.assignee} size="sm" />
          </span>
        </div>
      </div>
      {edge === "bottom" && <div className="absolute -bottom-[5px] left-0 right-0 z-10 h-0.5 rounded bg-brand" />}
    </div>
  );
}
