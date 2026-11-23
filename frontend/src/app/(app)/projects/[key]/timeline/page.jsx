"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Plus } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon } from "@/components/icons";
import { IssueModal } from "@/components/issue/issue-view";
import { useApp } from "@/components/shell/app-context";
import { PageSpinner } from "@/components/ui/button";
import { Lozenge, Tabs } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { invalidateIssueViews, useProjectMeta } from "@/lib/api/hooks";
import { cn, fmtDate } from "@/lib/utils";

const DAY = 864e5;
const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const parse = (s) => new Date(`${s}T00:00:00`);
const EPIC_COLORS = ["#6554C0", "#00875A", "#FF991F", "#0065FF", "#DE350B", "#00A3BF", "#5243AA", "#36B37E", "#FF5630", "#8777D9"];

const DAY_PX = { weeks: 28, months: 9, quarters: 3.2 };

function Bar({ row, origin, px, color, onChange, onOpen }) {
  const [drag, setDrag] = useState(null);
  const [preview, setPreview] = useState(null);
  const moved = useRef(false);
  if (!row.start_date && !row.due_date) return null;
  const s0 = parse(row.start_date ?? row.due_date).getTime();
  const e0 = parse(row.due_date ?? row.start_date).getTime();
  const s = preview?.s ?? s0, e = preview?.e ?? e0;
  const left = ((s - origin) / DAY) * px;
  const width = Math.max(px, ((e - s) / DAY + 1) * px);
  const down = (mode) => (ev) => {
    ev.stopPropagation();
    ev.target.setPointerCapture(ev.pointerId);
    moved.current = false;
    setDrag({ mode, x: ev.clientX, s: s0, e: e0 });
  };
  const move = (ev) => {
    if (!drag) return;
    const days = Math.round((ev.clientX - drag.x) / px);
    if (days) moved.current = true;
    const d = days * DAY;
    if (drag.mode === "move") setPreview({ s: drag.s + d, e: drag.e + d });
    else if (drag.mode === "start") setPreview({ s: Math.min(drag.s + d, drag.e), e: drag.e });
    else setPreview({ s: drag.s, e: Math.max(drag.e + d, drag.s) });
  };
  const up = () => {
    if (drag && preview && moved.current) onChange(iso(new Date(preview.s)), iso(new Date(preview.e)));
    else if (!moved.current) onOpen();
    setDrag(null);
    setTimeout(() => setPreview(null), 300);
  };
  return (
    <div className="absolute top-1.5 flex h-6 select-none items-center rounded-[3px] text-xs font-medium text-white shadow-raised"
         style={{ left, width, backgroundColor: color, cursor: drag ? "grabbing" : "grab" }}
         title={`${fmtDate(new Date(s))} – ${fmtDate(new Date(e))}`}
         onPointerDown={down("move")} onPointerMove={move} onPointerUp={up}>
      <span onPointerDown={down("start")} className="h-full w-2 shrink-0 cursor-ew-resize rounded-l-[3px] hover:bg-black/20" />
      <span className="min-w-0 flex-1 truncate px-1">{width > 80 ? row.summary : ""}</span>
      <span onPointerDown={down("end")} className="h-full w-2 shrink-0 cursor-ew-resize rounded-r-[3px] hover:bg-black/20" />
    </div>
  );
}

function Timeline({ projectKey }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const qc = useQueryClient();
  const { openCreate } = useApp();
  const meta = useProjectMeta(projectKey);
  const [zoom, setZoom] = useState("months");
  const [expanded, setExpanded] = useState(new Set());
  // Epic-level types come from the project's metadata (hierarchy level 1), never by name.
  const epicTypes = (meta.data?.issue_types ?? []).filter((t) => t.level === 1)
    .map((t) => `"${t.name.replace(/["\\]/g, "\\$&")}"`);
  const jql = epicTypes.length
    ? `project = ${projectKey} AND (type in (${epicTypes.join(", ")}) OR parent is not EMPTY) ORDER BY rank`
    : `project = ${projectKey} AND parent is not EMPTY ORDER BY rank`;
  const data = useQuery({
    queryKey: ["search", "timeline", projectKey, jql],
    queryFn: () => unwrap(api.POST("/api/v1/search", { body: { jql, limit: 200 } })),
    enabled: !!meta.data,
  });
  const selected = params.get("selectedIssue");
  const open = (k) => { const p = new URLSearchParams(params.toString()); p.set("selectedIssue", k); router.push(`${pathname}?${p}`, { scroll: false }); };
  const close = () => router.push(pathname, { scroll: false });

  const { epics, children } = useMemo(() => {
    const rows = data.data?.issues ?? [];
    const epics = rows.filter((r) => r.type.level === 1);
    const ids = new Set(epics.map((e) => e.id));
    const children = new Map();
    rows.filter((r) => r.parent_id && ids.has(r.parent_id)).forEach((r) => children.set(r.parent_id, [...(children.get(r.parent_id) ?? []), r]));
    return { epics, children };
  }, [data.data]);

  const px = DAY_PX[zoom];
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const origin = new Date(today.getFullYear(), today.getMonth() - (zoom === "weeks" ? 0 : 1), 1).getTime();
  const days = zoom === "weeks" ? 70 : zoom === "months" ? 240 : 540;
  const width = days * px;
  const ticks = [];
  for (let d = 0; d < days; d++) {
    const date = new Date(origin + d * DAY);
    if (zoom === "weeks" ? date.getDay() === 1 : date.getDate() === 1) {
      if (zoom === "quarters" && date.getMonth() % 3 !== 0) continue;
      ticks.push({ left: d * px, label: zoom === "weeks" ? fmtDate(date, "d MMM") : zoom === "months" ? fmtDate(date, "MMMM yyyy") : `T${date.getMonth() / 3 + 1} ${date.getFullYear()}` });
    }
  }
  const todayLeft = ((today.getTime() - origin) / DAY) * px;

  const setDates = async (r, start, due) => {
    try {
      await unwrap(api.PATCH("/api/v1/issues/{key}", { params: { path: { key: r.key } }, body: { start_date: start, due_date: due } }));
      invalidateIssueViews(qc, r.key);
      qc.invalidateQueries({ queryKey: ["search", "timeline", projectKey] });
    } catch (e) { toast.error(errorMessage(e)); }
  };
  const schedule = (r, ev) => {
    if (r.start_date || r.due_date || !meta.data?.permissions.includes("edit_issues")) return;
    const rect = ev.currentTarget.getBoundingClientRect();
    const day = Math.floor((ev.clientX - rect.left) / px);
    const start = new Date(origin + day * DAY);
    setDates(r, iso(start), iso(new Date(start.getTime() + 13 * DAY)));
  };

  if (data.isPending || meta.isPending) return <PageSpinner />;
  const epicType = meta.data?.issue_types.find((t) => t.level === 1);

  const rowsToRender = [];
  epics.forEach((e) => {
    const color = EPIC_COLORS[e.id % EPIC_COLORS.length];
    rowsToRender.push({ row: e, depth: 0, color });
    if (expanded.has(e.id)) (children.get(e.id) ?? []).forEach((c) => rowsToRender.push({ row: c, depth: 1, color: `${color}cc` }));
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-3 px-6 pt-5">
        <h1 className="text-2xl font-medium">Cronograma</h1>
        <div className="ml-auto"><Tabs value={zoom} onChange={setZoom} className="border-none" tabs={[{ value: "weeks", label: "Semanas" }, { value: "months", label: "Meses" }, { value: "quarters", label: "Trimestres" }]} /></div>
      </div>
      <p className="px-6 text-sm text-fg-subtle">Arrastra las barras para mover fechas o sus extremos para ajustar la duración. Haz clic en una fila sin fechas para programarla.</p>
      <div className="mt-3 flex min-h-0 flex-1 overflow-hidden border-t border-line">
        <div className="w-[340px] shrink-0 overflow-y-auto border-r border-line">
          <div className="sticky top-0 z-10 h-9 border-b border-line bg-bg px-3 text-xs font-semibold leading-9 text-fg-subtle">Épicas</div>
          {rowsToRender.map(({ row, depth }) => (
            <div key={row.id} className="flex h-9 items-center gap-1.5 border-b border-line px-2 text-sm hover:bg-bg-hover" style={{ paddingLeft: 8 + depth * 22 }}>
              {depth === 0 ? (
                <button aria-label="Expandir" className={cn("rounded p-0.5 hover:bg-bg-pressed", !(children.get(row.id)?.length) && "invisible")}
                        onClick={() => setExpanded((s) => { const n = new Set(s); if (n.has(row.id)) n.delete(row.id); else n.add(row.id); return n; })}>
                  <ChevronRight size={14} className={cn("transition-transform", expanded.has(row.id) && "rotate-90")} />
                </button>
              ) : null}
              <IssueTypeIcon type={row.type} />
              <button onClick={() => open(row.key)} className="min-w-0 flex-1 truncate text-left hover:underline">
                <span className="text-fg-subtle">{row.key}</span> {row.summary}
              </button>
              {depth === 0 && <Lozenge category={row.status.category} className="max-w-20">{row.status.name}</Lozenge>}
            </div>
          ))}
          {meta.data?.permissions.includes("create_issues") && epicType && (
            <button onClick={() => openCreate({ projectKey, issueTypeId: epicType.id })}
                    className="flex h-9 w-full items-center gap-1 px-3 text-sm font-medium text-fg-subtle hover:bg-bg-hover"><Plus size={16} />Crear épica</button>
          )}
        </div>
        <div className="min-w-0 flex-1 overflow-auto">
          <div className="relative" style={{ width }}>
            <div className="sticky top-0 z-10 h-9 border-b border-line bg-bg">
              {ticks.map((t) => <div key={t.left} className="absolute top-0 h-9 border-l border-line pl-2 text-xs capitalize leading-9 text-fg-subtle" style={{ left: t.left }}>{t.label}</div>)}
            </div>
            <div className="pointer-events-none absolute bottom-0 top-9 z-[1] w-0.5 bg-warning" style={{ left: todayLeft }} />
            {ticks.map((t) => <div key={`g${t.left}`} className="pointer-events-none absolute bottom-0 top-9 border-l border-line/60" style={{ left: t.left }} />)}
            {rowsToRender.map(({ row, color }) => (
              <div key={row.id} className={cn("relative h-9 border-b border-line", !row.start_date && !row.due_date && "cursor-copy hover:bg-bg-hover")}
                   onClick={(e) => schedule(row, e)}>
                <Bar row={row} origin={origin} px={px} color={color} onOpen={() => open(row.key)}
                     onChange={(s, d) => setDates(row, s, d)} />
              </div>
            ))}
          </div>
        </div>
      </div>
      {!epics.length && <div className="px-6 py-10 text-center text-fg-subtle">Crea épicas para planificar el trabajo en el tiempo.</div>}
      <IssueModal issueKey={selected} onClose={close} />
    </div>
  );
}

export default function TimelinePage({ params }) {
  const { key } = use(params);
  return <Suspense fallback={<PageSpinner />}><Timeline projectKey={key.toUpperCase()} /></Suspense>;
}
