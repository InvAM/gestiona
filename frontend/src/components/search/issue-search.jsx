"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, Layers, Star, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { IssueModal } from "@/components/issue/issue-view";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, EmptyState, Field, Input, Lozenge, Modal, Textarea } from "@/components/ui/primitives";
import { AskJql } from "@/components/ai/ai";
import { BulkDialog } from "./bulk-dialog";
import { Picker } from "@/components/ui/picker";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { qk, useMeta } from "@/lib/api/hooks";
import { cn, fmtDate, fmtPoints } from "@/lib/utils";
import { JqlEditor } from "./jql-editor";

const PAGE = 50;
const SORTABLE = {
  key: "key", summary: "summary", status: "status", priority: "priority", assignee: "assignee",
  created: "created", updated: "updated", type: "type", due: "due",
};

function setOrder(jql, field) {
  const m = jql.match(/\s*order\s+by\s+(.+)$/i);
  const base = m ? jql.slice(0, m.index).trim() : jql.trim();
  const [curField, curDir] = (m?.[1].split(",")[0].trim().toLowerCase() ?? "").split(/\s+/);
  // same column: toggle direction; new column: start ascending
  const dir = curField === field && curDir !== "desc" ? "DESC" : "ASC";
  return `${base}${base ? " " : ""}ORDER BY ${field} ${dir}`;
}

function SortTh({ f, children, className, onSort, icon }) {
  return (
    <th className={cn("whitespace-nowrap px-2 py-2 text-left text-xs font-semibold text-fg-subtle", className)}>
      {f ? <button className="inline-flex items-center gap-1 hover:text-fg" onClick={() => onSort(SORTABLE[f])}>{children}{icon(SORTABLE[f])}</button> : children}
    </th>
  );
}

/** Loads a saved filter (if any) first, then mounts the search with its JQL as initial state. */
export function IssueSearch({ projectKey }) {
  const params = useSearchParams();
  const filterId = params.get("filter");
  const filter = useQuery({
    queryKey: ["filter", filterId],
    queryFn: () => unwrap(api.GET("/api/v1/filters/{fid}", { params: { path: { fid: Number(filterId) } } })),
    enabled: !!filterId,
  });
  if (filterId && filter.isPending) return <PageSpinner />;
  return <IssueSearchInner key={`${filterId ?? ""}:${filter.data?.id ?? ""}`} projectKey={projectKey} filter={filter.data} />;
}

function IssueSearchInner({ projectKey, filter: savedFilter }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const qc = useQueryClient();
  const filterId = params.get("filter");
  const defaultJql = projectKey ? `project = ${projectKey} ORDER BY created DESC` : "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC";
  const initial = params.get("jql") ?? savedFilter?.jql ?? defaultJql;
  const [jql, setJql] = useState(initial);
  const [applied, setApplied] = useState(initial);
  const [start, setStart] = useState(0);
  const [saveOpen, setSaveOpen] = useState(false);
  const [picked, setPicked] = useState(new Map());
  const [bulkOpen, setBulkOpen] = useState(false);
  const selected = params.get("selectedIssue");

  const filter = { data: savedFilter };

  const results = useQuery({
    queryKey: qk.search(applied, start, PAGE),
    queryFn: () => unwrap(api.POST("/api/v1/search", { body: { jql: applied, start, limit: PAGE } })),
    placeholderData: keepPreviousData,
    retry: false,
  });
  const error = results.error instanceof ApiError ? results.error.message : null;

  const run = (q = jql) => {
    setApplied(q);
    setStart(0);
    const p = new URLSearchParams(params.toString());
    p.set("jql", q);
    router.replace(`${pathname}?${p}`, { scroll: false });
  };
  const sort = (f) => { const q = setOrder(applied, f); setJql(q); run(q); };
  const open = (key) => {
    const p = new URLSearchParams(params.toString());
    p.set("selectedIssue", key);
    router.push(`${pathname}?${p}`, { scroll: false });
  };
  const close = () => {
    const p = new URLSearchParams(params.toString());
    p.delete("selectedIssue");
    router.push(`${pathname}?${p}`, { scroll: false });
  };

  const updateFilter = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/filters/{fid}", { params: { path: { fid: Number(filterId) } }, body: { jql: applied } })),
    onSuccess: () => { toast.success("Filtro actualizado"); qc.invalidateQueries({ queryKey: ["filter", filterId] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const starFilter = useMutation({
    mutationFn: (on) => on
      ? unwrap(api.POST("/api/v1/filters/{fid}/star", { params: { path: { fid: Number(filterId) } } }))
      : unwrap(api.DELETE("/api/v1/filters/{fid}/star", { params: { path: { fid: Number(filterId) } } })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["filter", filterId] }); qc.invalidateQueries({ queryKey: ["filters"] }); },
  });

  const orderField = applied.match(/order\s+by\s+(\w+)\s*(asc|desc)?/i);
  const sortIcon = (f) => orderField?.[1].toLowerCase() === f
    ? (orderField[2]?.toLowerCase() === "desc" ? <ArrowDown size={12} /> : <ArrowUp size={12} />) : null;
  const dirty = filter.data && filter.data.jql !== applied;
  const data = results.data;
  const pageRows = data?.issues ?? [];
  const allOnPage = pageRows.length > 0 && pageRows.every((i) => picked.has(i.id));
  const togglePick = (rows, on) => setPicked((m) => {
    const next = new Map(m);
    for (const r of rows) { if (on) next.set(r.id, r); else next.delete(r.id); }
    return next;
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-6 pt-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-medium">{filter.data?.name ?? (projectKey ? "Incidencias" : "Buscar incidencias")}</h1>
          {filter.data && (
            <button aria-label="Destacar filtro" onClick={() => starFilter.mutate(!filter.data.starred)}>
              <Star size={18} className={cn(filter.data.starred ? "fill-warning text-warning" : "text-fg-subtlest")} />
            </button>
          )}
          <div className="ml-auto flex gap-2">
            {filter.data?.is_owner && dirty && <Button variant="primary" loading={updateFilter.isPending} onClick={() => updateFilter.mutate()}>Guardar cambios</Button>}
            <Button onClick={() => setSaveOpen(true)}>{filter.data ? "Guardar como" : "Guardar filtro"}</Button>
            <Button asChild><a href={`/api/v1/search/export?jql=${encodeURIComponent(applied)}`}><Download size={16} />Exportar CSV</a></Button>
          </div>
        </div>
        <div className="mt-4"><JqlEditor value={jql} onChange={setJql} onSubmit={() => run()} error={error} /></div>
        <AskJql projectKey={projectKey} onJql={(q) => { setJql(q); run(q); }} />
        <QuickBuilder projectKey={projectKey} onApply={(q) => { setJql(q); run(q); }} />
        {picked.size > 0 && (
          <div role="toolbar" aria-label="Acciones de selección"
               className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-md border border-line bg-bg px-4 py-2 text-sm shadow-lg">
            <b>{picked.size} {picked.size === 1 ? "seleccionada" : "seleccionadas"}</b>
            <Button size="sm" variant="primary" onClick={() => setBulkOpen(true)}><Layers size={14} />Cambio masivo</Button>
            <button className="inline-flex items-center gap-1 text-fg-subtle hover:text-fg" onClick={() => setPicked(new Map())}><X size={14} />Limpiar</button>
          </div>
        )}
      </div>
      <div className="mt-3 min-h-0 flex-1 overflow-auto px-6 pb-6">
        {results.isPending && !data ? <PageSpinner /> : !data?.issues.length ? (
          <EmptyState title="No encontramos incidencias" body="Prueba con otros criterios de búsqueda." />
        ) : (
          <>
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-bg">
                <tr className="border-b-2 border-line">
                  <th className="w-8 px-2"><input type="checkbox" aria-label="Seleccionar página" className="h-4 w-4 accent-[var(--brand)]" checked={allOnPage} onChange={(e) => togglePick(pageRows, e.target.checked)} /></th>
                  <SortTh onSort={sort} icon={sortIcon} f="type" className="w-10">T</SortTh><SortTh onSort={sort} icon={sortIcon} f="key">Clave</SortTh><SortTh onSort={sort} icon={sortIcon} f="summary">Resumen</SortTh>
                  <SortTh onSort={sort} icon={sortIcon} f="assignee">Responsable</SortTh><SortTh onSort={sort} icon={sortIcon}>Informador</SortTh><SortTh onSort={sort} icon={sortIcon} f="priority">P</SortTh><SortTh onSort={sort} icon={sortIcon} f="status">Estado</SortTh>
                  <SortTh onSort={sort} icon={sortIcon}>Resolución</SortTh><SortTh onSort={sort} icon={sortIcon}>Puntos</SortTh><SortTh onSort={sort} icon={sortIcon} f="created">Creada</SortTh><SortTh onSort={sort} icon={sortIcon} f="updated">Actualizada</SortTh><SortTh onSort={sort} icon={sortIcon} f="due">Vence</SortTh>
                </tr>
              </thead>
              <tbody>
                {data.issues.map((i) => (
                  <tr key={i.id} onClick={() => open(i.key)} className={cn("cursor-pointer border-b border-line hover:bg-bg-hover", (selected === i.key || picked.has(i.id)) && "bg-bg-selected")}>
                    <td className="px-2 py-1.5" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Seleccionar ${i.key}`} className="h-4 w-4 accent-[var(--brand)]" checked={picked.has(i.id)} onChange={(e) => togglePick([i], e.target.checked)} />
                    </td>
                    <td className="px-2 py-1.5"><IssueTypeIcon type={i.type} /></td>
                    <td className={cn("whitespace-nowrap px-2 py-1.5 text-link", i.status.category === "done" && "line-through")}>{i.key}</td>
                    <td className="max-w-[420px] truncate px-2 py-1.5">{i.summary}</td>
                    <td className="whitespace-nowrap px-2 py-1.5"><span className="flex items-center gap-1.5"><Avatar user={i.assignee} size="xs" />{i.assignee?.name ?? <span className="text-fg-subtlest">Sin asignar</span>}</span></td>
                    <td className="whitespace-nowrap px-2 py-1.5">{i.reporter?.name}</td>
                    <td className="px-2 py-1.5"><PriorityIcon priority={i.priority} /></td>
                    <td className="px-2 py-1.5"><Lozenge category={i.status.category}>{i.status.name}</Lozenge></td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-fg-subtle">{i.resolution ?? "Sin resolver"}</td>
                    <td className="px-2 py-1.5">{fmtPoints(i.story_points)}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-fg-subtle">{fmtDate(i.created_at, "d/MMM/yy")}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-fg-subtle">{fmtDate(i.updated_at, "d/MMM/yy")}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-fg-subtle">{fmtDate(i.due_date, "d/MMM/yy")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex items-center gap-3 text-sm text-fg-subtle">
              <span>{start + 1}–{Math.min(start + PAGE, data.total)} de {data.total}</span>
              <Button size="sm" disabled={start === 0} onClick={() => setStart(Math.max(0, start - PAGE))}>Anterior</Button>
              <Button size="sm" disabled={start + PAGE >= data.total} onClick={() => setStart(start + PAGE)}>Siguiente</Button>
            </div>
          </>
        )}
      </div>
      <SaveFilterDialog open={saveOpen} onOpenChange={setSaveOpen} jql={applied}
                        onSaved={(id) => router.push(`/issues?filter=${id}`)} />
      <IssueModal issueKey={selected} onClose={close} />
      <BulkDialog open={bulkOpen} onOpenChange={setBulkOpen} rows={Array.from(picked.values())} onDone={() => setPicked(new Map())} />
    </div>
  );
}

function QuickBuilder({ projectKey, onApply }) {
  const presets = [
    ["Mis incidencias abiertas", "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"],
    ["Informadas por mí", "reporter = currentUser() ORDER BY created DESC"],
    ["Sin asignar", "assignee is EMPTY AND resolution = Unresolved ORDER BY created DESC"],
    ["Creadas recientemente", "created >= -1w ORDER BY created DESC"],
    ["Resueltas recientemente", "resolved >= -1w ORDER BY resolved DESC"],
    ["Actualizadas recientemente", "updated >= -1w ORDER BY updated DESC"],
    ["Vencidas", "due < now() AND resolution = Unresolved ORDER BY due ASC"],
  ];
  const scope = projectKey ? `project = ${projectKey} AND ` : "";
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {presets.map(([label, q]) => (
        <Button key={label} size="sm" variant="subtle" onClick={() => onApply(scope + q)}>{label}</Button>
      ))}
    </div>
  );
}

function SaveFilterDialog({ open, onOpenChange, jql, onSaved }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("private");
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/filters", { body: { name, description, jql, visibility } })),
    onSuccess: (f) => { onOpenChange(false); setName(""); qc.invalidateQueries({ queryKey: ["filters"] }); toast.success("Filtro guardado"); onSaved(f.id); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const meta = useMeta();
  // "project" visibility needs a project, which this dialog doesn't ask for.
  const opts = (meta.data?.filter_visibility ?? []).filter((o) => o.value !== "project");
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Guardar filtro" width={480}
           footer={<><Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant="primary" disabled={!name.trim()} loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button></>}>
      <div className="space-y-4">
        <Field label="Nombre" required><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
        <Field label="Descripción"><Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <Field label="Visible para">
          <Picker value={visibility} options={opts} onSelect={setVisibility} width={300}
                  trigger={<button className="flex h-8 w-72 items-center rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm">{opts.find((o) => o.value === visibility)?.label}</button>} />
        </Field>
        <div className="rounded-[3px] bg-bg-sunken p-2 font-mono text-xs">{jql}</div>
      </div>
    </Modal>
  );
}
