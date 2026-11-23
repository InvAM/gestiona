"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, GripVertical, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { BOARD_VIEWS, CreateBoardDialog, boardHref } from "@/components/board/create-board-dialog";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";
import { useApp } from "@/components/shell/app-context";
import { Button, PageSpinner } from "@/components/ui/button";
import { EmptyState, Field, Input, Lozenge } from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { BOARD_LANES, cn, pluralize } from "@/lib/utils";

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

const SOFT_BODY = "Deja de aparecer en la navegación del proyecto, en los selectores y en los planes. "
  + "Sus columnas, filtros rápidos y sprints se conservan y las incidencias no se tocan.";

/*
 * «Tablero» tab of the project settings: the project's boards (create / delete to the
 * papelera / restore / purge) and the configuration of the selected one.
 * Backend: GET /projects/{key}/boards[?deleted=true], DELETE /boards/{id}[?permanent=true],
 * POST /boards/{id}/restore. Conflicts (409 active_sprint / protected) are shown inside the
 * confirmation dialog. Like Jira, the last board can be deleted: the project lives without one.
 */
export function BoardSettings({ meta }) {
  const { me } = useApp();
  const appMeta = useMeta();
  const search = useSearchParams();
  const key = meta.project.key;
  const boards = meta.boards;
  const [view, setView] = useState("active");
  const [picked, setPicked] = useState(() => Number(search.get("board")) || null);
  const [creating, setCreating] = useState(() => search.get("create") === "1");
  const selected = boards.find((b) => b.id === picked) ?? boards[0];
  const listKey = `boards-${key}`;
  const deleted = useDeletedList(`/api/v1/projects/${key}/boards`, listKey, view === "deleted");
  const actions = useCatalogActions({
    path: "/api/v1/boards", queryKey: listKey, related: BOARD_VIEWS, softBody: SOFT_BODY,
    onDeleted: (row) => { if (row.id === picked) setPicked(null); },
  });
  const kind = (k) => choiceLabel(appMeta.data?.board_kinds, k);

  return (
    <div className="space-y-8">
      <section className="max-w-[860px]">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-medium">Tableros del proyecto</h2>
            <p className="mt-1 text-sm text-fg-subtle">
              Un tablero con un sprint activo no se puede eliminar: complétalo antes. Sin tableros, las incidencias siguen en la Lista y en Incidencias.
            </p>
          </div>
          <Button variant="primary" onClick={() => setCreating(true)}><Plus size={16} />Crear tablero</Button>
        </div>
        <CatalogTabs value={view} onChange={setView} className="mt-4" />
        {view === "deleted" ? (
          <DeletedList query={deleted} actions={actions} allowPurge={!!me.is_admin}
                       empty="No hay tableros eliminados. Al restaurar uno vuelven sus columnas, filtros rápidos y sprints."
                       render={(b) => (
                         <span>
                           <b>{b.name}</b>
                           <span className="ml-2 text-xs text-fg-subtle">
                             {kind(b.kind)} · {pluralize(b.columns.length, "columna", "columnas")} · {pluralize(b.quick_filters.length, "filtro rápido", "filtros rápidos")}
                           </span>
                         </span>
                       )} />
        ) : boards.length ? (
          <table className="mt-3 w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
              <th className="py-2">Nombre</th><th className="py-2">Tipo</th><th className="w-48" /></tr></thead>
            <tbody>
              {boards.map((b) => (
                <tr key={b.id} className={cn("border-b border-line", b.id === selected?.id && "bg-bg-selected")}>
                  <td className="py-2">
                    <button className="font-medium text-link hover:underline" aria-current={b.id === selected?.id || undefined}
                            onClick={() => setPicked(b.id)}>{b.name}</button>
                  </td>
                  <td className="py-2 text-fg-subtle">{kind(b.kind)}</td>
                  <td className="py-2 text-right">
                    <span className="inline-flex items-center gap-1">
                      <Button variant="subtle" size="sm" asChild>
                        <Link href={boardHref(key, b)}><ExternalLink size={14} />Abrir</Link>
                      </Button>
                      <Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${b.name}`} onClick={() => actions.askDelete(b)}><Trash2 size={14} /></Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="Este proyecto no tiene tableros"
                      body="Las incidencias siguen disponibles en la Lista y en Incidencias. Crea un tablero o restaura uno eliminado." />
        )}
      </section>

      {view === "active" && selected && (
        <section>
          <h2 className="border-t border-line pt-6 text-lg font-medium">Configuración de «{selected.name}»</h2>
          <div className="mt-4"><BoardConfig meta={meta} boardId={selected.id} /></div>
        </section>
      )}

      <CreateBoardDialog projectKey={key} open={creating} onOpenChange={setCreating} onCreated={(b) => setPicked(b.id)} />
      {actions.dialog}
    </div>
  );
}

function BoardConfig({ meta, boardId }) {
  const board = useQuery({
    queryKey: ["board-config", boardId],
    queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}", { params: { path: { board_id: boardId } } })),
  });
  if (board.error) return <p className="text-sm text-danger">{errorMessage(board.error)}</p>;
  if (!board.data) return <PageSpinner />;
  return <BoardForm key={`${boardId}-${board.dataUpdatedAt}`} meta={meta} board={board.data} />;
}

function BoardForm({ meta, board: initialBoard }) {
  const appMeta = useMeta();
  const qc = useQueryClient();
  const boardId = initialBoard.id;
  const board = { data: initialBoard };
  const [cols, setCols] = useState(() => initialBoard.columns.map((c) => ({ id: c.id, name: c.name, status_ids: c.status_ids, min_issues: c.min_issues, max_issues: c.max_issues })));
  const [cfg, setCfg] = useState(
    () => ({ name: initialBoard.name, filter_jql: initialBoard.filter_jql, swimlanes: initialBoard.swimlanes, estimation: initialBoard.estimation, hide_done_after_days: initialBoard.hide_done_after_days }));
  const [qfName, setQfName] = useState("");
  const [qfJql, setQfJql] = useState("");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["board-config", boardId] });
    qc.invalidateQueries({ queryKey: ["board"] });
    qc.invalidateQueries({ queryKey: ["backlog"] });
  };
  const saveCols = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/boards/{board_id}/columns", { params: { path: { board_id: boardId } }, body: cols })),
    onSuccess: () => { toast.success("Columnas guardadas"); refresh(); }, onError: (e) => toast.error(errorMessage(e)),
  });
  const saveCfg = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/boards/{board_id}", { params: { path: { board_id: boardId } }, body: cfg })),
    onSuccess: () => { toast.success("Tablero actualizado"); refresh(); qc.invalidateQueries({ queryKey: ["project-meta"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const addQf = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/boards/{board_id}/quick-filters", { params: { path: { board_id: boardId } }, body: { name: qfName, jql: qfJql } })),
    onSuccess: () => { setQfName(""); setQfJql(""); refresh(); }, onError: (e) => toast.error(errorMessage(e)),
  });
  const delQf = useMutation({
    mutationFn: (id) => unwrap(api.DELETE("/api/v1/boards/{board_id}/quick-filters/{qid}", { params: { path: { board_id: boardId, qid: id } } })),
    onSuccess: refresh, onError: (e) => toast.error(errorMessage(e)),
  });
  const mapped = new Set(cols.flatMap((c) => c.status_ids));
  const unmapped = meta.statuses.filter((s) => !mapped.has(s.id));
  const moveStatus = (sid, toIdx) =>
    setCols(cols.map((c, i) => ({ ...c, status_ids: i === toIdx ? [...c.status_ids.filter((x) => x !== sid), sid] : c.status_ids.filter((x) => x !== sid) })));
  const statusChip = (sid) => {
    const s = meta.statuses.find((x) => x.id === sid);
    if (!s) return null;
    return (
      <Picker key={sid} value={cols.findIndex((c) => c.status_ids.includes(sid))} width={220}
              options={[{ value: -1, label: "Sin asignar (oculto)" }, ...cols.map((c, i) => ({ value: i, label: c.name }))]}
              onSelect={(i) => moveStatus(sid, i === -1 ? null : i)}
              trigger={<button className="w-full rounded-[3px] bg-bg p-2 text-left shadow-raised hover:bg-bg-hover"><Lozenge category={s.category}>{s.name}</Lozenge></button>} />
    );
  };
  return (
    <div className="space-y-10">
      <section>
        <h3 className="font-semibold">Columnas</h3>
        <p className="mt-1 text-sm text-fg-subtle">Asigna estados a columnas. Haz clic en un estado para moverlo. Los límites mín/máx resaltan la columna (WIP).</p>
        <div className="mt-4 flex gap-3 overflow-x-auto pb-2">
          <div className="w-48 shrink-0 rounded-[3px] bg-bg-column p-2">
            <div className="mb-2 text-xs font-semibold uppercase text-fg-subtle">Estados sin asignar</div>
            <div className="space-y-2">{unmapped.map((s) => statusChip(s.id))}{!unmapped.length && <p className="text-xs text-fg-subtlest">Ninguno</p>}</div>
          </div>
          {cols.map((c, i) => (
            <div key={c.id ?? `n${i}`} className="w-52 shrink-0 rounded-[3px] bg-bg-column p-2">
              <div className="mb-2 flex items-center gap-1">
                <GripVertical size={14} className="text-fg-subtlest" />
                <input value={c.name} aria-label="Nombre de la columna" onChange={(e) => setCols(cols.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                       className="min-w-0 flex-1 rounded bg-transparent px-1 text-xs font-semibold uppercase outline-none focus:bg-bg" />
                <button aria-label="Mover a la izquierda" disabled={i === 0} className="px-1 text-fg-subtle disabled:opacity-30"
                        onClick={() => { const n = [...cols]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setCols(n); }}>‹</button>
                <button aria-label="Mover a la derecha" disabled={i === cols.length - 1} className="px-1 text-fg-subtle disabled:opacity-30"
                        onClick={() => { const n = [...cols]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; setCols(n); }}>›</button>
                <button aria-label="Eliminar columna" onClick={() => setCols(cols.filter((_, j) => j !== i))} className="text-fg-subtle hover:text-danger"><Trash2 size={13} /></button>
              </div>
              <div className="mb-2 flex gap-1 text-xs">
                <input type="number" min={0} placeholder="Mín" aria-label="Mínimo" value={c.min_issues ?? ""} className="w-1/2 rounded border border-line bg-bg px-1"
                       onChange={(e) => setCols(cols.map((x, j) => (j === i ? { ...x, min_issues: e.target.value ? Number(e.target.value) : null } : x)))} />
                <input type="number" min={0} placeholder="Máx" aria-label="Máximo" value={c.max_issues ?? ""} className="w-1/2 rounded border border-line bg-bg px-1"
                       onChange={(e) => setCols(cols.map((x, j) => (j === i ? { ...x, max_issues: e.target.value ? Number(e.target.value) : null } : x)))} />
              </div>
              <div className="space-y-2">{c.status_ids.map(statusChip)}</div>
            </div>
          ))}
          <button onClick={() => setCols([...cols, { name: "Nueva columna", status_ids: [], min_issues: null, max_issues: null }])}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[3px] bg-bg-column hover:bg-bg-hover" aria-label="Agregar columna"><Plus size={18} /></button>
        </div>
        <Button variant="primary" className="mt-3" loading={saveCols.isPending} onClick={() => saveCols.mutate()}>Guardar columnas</Button>
      </section>

      <section className="max-w-[520px] space-y-4">
        <h3 className="font-semibold">General</h3>
        <Field label="Nombre del tablero"><Input value={cfg.name} maxLength={80} onChange={(e) => setCfg({ ...cfg, name: e.target.value })} /></Field>
        <Field label="Filtro adicional (JQL)" hint="Limita qué incidencias del proyecto aparecen. Vacío = todas.">
          <Input className="font-mono text-xs" value={cfg.filter_jql} onChange={(e) => setCfg({ ...cfg, filter_jql: e.target.value })} placeholder='labels = "frontend"' />
        </Field>
        <Field label="Carriles (swimlanes) por defecto">
          <Picker value={cfg.swimlanes} width={300} onSelect={(v) => setCfg({ ...cfg, swimlanes: v })}
                  options={(appMeta.data?.board_swimlanes ?? []).filter((o) => BOARD_LANES.includes(o.value))}
                  trigger={<button className={sel}>{choiceLabel(appMeta.data?.board_swimlanes, cfg.swimlanes)}</button>} />
        </Field>
        <Field label="Estimación">
          <Picker value={cfg.estimation} width={300} onSelect={(v) => setCfg({ ...cfg, estimation: v })}
                  options={appMeta.data?.board_estimations ?? []}
                  trigger={<button className={sel}>{choiceLabel(appMeta.data?.board_estimations, cfg.estimation)}</button>} />
        </Field>
        {board.data.kind === "kanban" && (
          <Field label="Ocultar incidencias listas después de (días)" hint="0 = nunca ocultar">
            <Input type="number" min={0} className="w-24" value={cfg.hide_done_after_days} onChange={(e) => setCfg({ ...cfg, hide_done_after_days: Number(e.target.value) })} />
          </Field>
        )}
        <Button variant="primary" disabled={!cfg.name.trim()} loading={saveCfg.isPending} onClick={() => saveCfg.mutate()}>Guardar</Button>
      </section>

      <section className="max-w-[720px]">
        <h3 className="font-semibold">Filtros rápidos</h3>
        <p className="mt-1 text-sm text-fg-subtle">Botones en el tablero y backlog que aplican una consulta JQL.</p>
        <div className="mt-3 space-y-2">
          {board.data.quick_filters.map((q) => (
            <div key={q.id} className="flex items-center gap-3 rounded-[3px] border border-line px-3 py-2 text-sm">
              <b className="w-40 truncate">{q.name}</b><code className="min-w-0 flex-1 truncate text-xs text-fg-subtle">{q.jql}</code>
              <Button variant="subtle" size="icon-sm" aria-label={`Eliminar filtro ${q.name}`} onClick={() => delQf.mutate(q.id)}><Trash2 size={14} /></Button>
            </div>
          ))}
          <div className="flex gap-2">
            <Input placeholder="Nombre" value={qfName} onChange={(e) => setQfName(e.target.value)} className="w-40" />
            <Input placeholder="assignee = currentUser()" value={qfJql} onChange={(e) => setQfJql(e.target.value)} className="flex-1 font-mono text-xs" />
            <Button disabled={!qfName || !qfJql} loading={addQf.isPending} onClick={() => addQf.mutate()}>Agregar</Button>
          </div>
        </div>
      </section>
    </div>
  );
}
