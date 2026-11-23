"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { IssueModal } from "@/components/issue/issue-view";
import { useApp } from "@/components/shell/app-context";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, Input } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { invalidateIssueViews, useProjectMeta } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const MAX_PER_DAY = 4;

function monthGrid(year, month) {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7; // Monday first
  const start = new Date(year, month, 1 - offset);
  const days = [];
  for (let i = 0; i < 42; i++) days.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  // drop the 6th week when it is entirely next month
  return days[35].getMonth() !== month ? days.slice(0, 35) : days;
}

function Calendar({ projectKey }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const qc = useQueryClient();
  const { openCreate } = useApp();
  const meta = useProjectMeta(projectKey);
  const today = new Date();
  const [cursor, setCursor] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [q, setQ] = useState("");
  const [dragKey, setDragKey] = useState(null);
  const [overDay, setOverDay] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const selected = params.get("selectedIssue");
  const days = monthGrid(cursor.y, cursor.m);
  const from = iso(days[0]), to = iso(days[days.length - 1]);
  const text = q.trim() ? ` AND text ~ "${q.trim().replace(/"/g, "")}"` : "";

  const scheduled = useQuery({
    queryKey: ["search", "calendar", projectKey, from, to, text],
    queryFn: () => unwrap(api.POST("/api/v1/search", { body: { jql: `project = ${projectKey} AND due >= "${from}" AND due <= "${to}"${text} ORDER BY due ASC, priority ASC`, start: 0, limit: 200 } })),
  });
  const unscheduled = useQuery({
    queryKey: ["search", "calendar-unscheduled", projectKey, text],
    queryFn: () => unwrap(api.POST("/api/v1/search", { body: { jql: `project = ${projectKey} AND due is EMPTY AND resolution = Unresolved${text} ORDER BY rank ASC`, start: 0, limit: 50 } })),
  });
  const setDue = useMutation({
    mutationFn: ({ key, due }) => unwrap(api.PATCH("/api/v1/issues/{key}", { params: { path: { key } }, body: { due_date: due } })),
    onSuccess: () => { invalidateIssueViews(qc); qc.invalidateQueries({ queryKey: ["search"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const byDay = new Map();
  for (const i of scheduled.data?.issues ?? []) {
    if (!i.due_date) continue;
    byDay.set(i.due_date, [...(byDay.get(i.due_date) ?? []), i]);
  }
  const open = (key) => { const p = new URLSearchParams(params.toString()); p.set("selectedIssue", key); router.push(`${pathname}?${p}`, { scroll: false }); };
  const close = () => { const p = new URLSearchParams(params.toString()); p.delete("selectedIssue"); router.push(`${pathname}?${p}`, { scroll: false }); };
  const shift = (n) => setCursor(({ y, m }) => { const d = new Date(y, m + n, 1); return { y: d.getFullYear(), m: d.getMonth() }; });
  const drop = (day) => {
    if (dragKey) setDue.mutate({ key: dragKey, due: day });
    setDragKey(null); setOverDay(null);
  };
  const canEdit = meta.data?.permissions.includes("edit_issues");

  const card = (i) => (
    <button key={i.key} draggable={canEdit} onDragStart={(e) => { setDragKey(i.key); e.dataTransfer.setData("text/plain", i.key); e.dataTransfer.effectAllowed = "move"; }}
            onDragEnd={() => { setDragKey(null); setOverDay(null); }} onClick={() => open(i.key)}
            className={cn("flex w-full items-center gap-1 rounded-[3px] border border-line bg-bg px-1.5 py-0.5 text-left text-xs shadow-[var(--shadow-raised)] hover:bg-bg-hover",
                          i.status.category === "done" && "opacity-60", dragKey === i.key && "opacity-40")}
            title={`${i.key} ${i.summary}`}>
      <IssueTypeIcon type={i.type} size={12} />
      <span className={cn("shrink-0 font-medium text-fg-subtle", i.status.category === "done" && "line-through")}>{i.key}</span>
      <span className="truncate">{i.summary}</span>
    </button>
  );

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col px-6 py-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-medium">Calendario</h1>
          <div className="ml-4 flex items-center gap-1">
            <Button size="icon" variant="subtle" aria-label="Mes anterior" onClick={() => shift(-1)}><ChevronLeft size={18} /></Button>
            <span className="w-40 text-center font-medium">{MONTHS[cursor.m]} {cursor.y}</span>
            <Button size="icon" variant="subtle" aria-label="Mes siguiente" onClick={() => shift(1)}><ChevronRight size={18} /></Button>
            <Button size="sm" onClick={() => setCursor({ y: today.getFullYear(), m: today.getMonth() })}>Hoy</Button>
          </div>
          <Input className="ml-auto w-56" placeholder="Buscar en el calendario" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <p className="mt-1 text-xs text-fg-subtle">Las incidencias se ubican por su fecha de vencimiento. Arrástralas para cambiarla.</p>
        <div className="mt-3 grid grid-cols-7 border-l border-t border-line text-xs font-semibold text-fg-subtle">
          {WEEKDAYS.map((w) => <div key={w} className="border-b border-r border-line px-2 py-1">{w}</div>)}
        </div>
        <div className="grid min-h-0 flex-1 auto-rows-fr grid-cols-7 border-l border-line">
          {days.map((d) => {
            const key = iso(d);
            const items = byDay.get(key) ?? [];
            const out = d.getMonth() !== cursor.m;
            const isToday = key === iso(today);
            const showAll = expanded === key;
            return (
              <div key={key} onDragOver={(e) => { if (dragKey) { e.preventDefault(); setOverDay(key); } }} onDragLeave={() => setOverDay((o) => (o === key ? null : o))} onDrop={(e) => { e.preventDefault(); drop(key); }}
                   className={cn("group relative flex min-h-[96px] flex-col gap-0.5 border-b border-r border-line p-1", out && "bg-bg-subtle", overDay === key && "bg-bg-selected")}>
                <div className="flex items-center">
                  <span className={cn("flex h-6 w-6 items-center justify-center rounded-full text-xs", out ? "text-fg-subtlest" : "text-fg-subtle", isToday && "bg-brand font-semibold text-fg-inverse")}>{d.getDate()}</span>
                  {meta.data?.permissions.includes("create_issues") && (
                    <button aria-label={`Crear incidencia el ${key}`} className="ml-auto hidden rounded p-0.5 text-fg-subtle hover:bg-bg-hover group-hover:block" onClick={() => openCreate({ projectKey, dueDate: key })}><Plus size={14} /></button>
                  )}
                </div>
                {(showAll ? items : items.slice(0, MAX_PER_DAY)).map(card)}
                {items.length > MAX_PER_DAY && (
                  <button className="text-left text-xs text-link hover:underline" onClick={() => setExpanded(showAll ? null : key)}>{showAll ? "Ver menos" : `+${items.length - MAX_PER_DAY} más`}</button>
                )}
              </div>
            );
          })}
        </div>
        {scheduled.data && scheduled.data.total > 200 && <p className="mt-2 text-xs text-warning">Se muestran 200 de {scheduled.data.total} incidencias del mes. Usa la búsqueda para acotar.</p>}
      </div>
      <aside onDragOver={(e) => { if (dragKey) e.preventDefault(); }} onDrop={(e) => { e.preventDefault(); drop(null); }}
             className="hidden w-72 shrink-0 flex-col border-l border-line bg-bg-subtle lg:flex">
        <div className="border-b border-line px-3 py-3"><h2 className="text-sm font-semibold">Sin fecha</h2><p className="text-xs text-fg-subtle">Arrastra al calendario para programar. Suelta aquí para quitar la fecha.</p></div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
          {unscheduled.isPending ? <PageSpinner /> : unscheduled.data?.issues.map((i) => (
            <div key={i.key} className="space-y-0.5">
              {card(i)}
              <div className="flex items-center gap-1 px-1"><PriorityIcon priority={i.priority} size={12} /><Avatar user={i.assignee} size="xs" /></div>
            </div>
          ))}
          {unscheduled.data && !unscheduled.data.issues.length && <p className="p-2 text-xs text-fg-subtle">Todas las incidencias abiertas tienen fecha.</p>}
        </div>
      </aside>
      <IssueModal issueKey={selected} onClose={close} />
    </div>
  );
}

export default function CalendarPage({ params }) {
  const { key } = use(params);
  return <main className="flex min-w-0 flex-1 flex-col"><Suspense fallback={<PageSpinner />}><Calendar projectKey={key.toUpperCase()} /></Suspense></main>;
}
