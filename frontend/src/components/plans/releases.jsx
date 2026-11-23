"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, MoreHorizontal, Package, Pencil, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { ProjectAvatar } from "@/components/icons";
import { Button, PageSpinner } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Confirm, EmptyState, Field, Input, Lozenge, Menu, MenuContent, MenuItem, MenuTrigger, Modal, Textarea, Tip } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { fmtDate } from "@/lib/utils";
import { planKeys, usePlanReleases, usePlanVersionOptions } from "./api";

// Color follows the status category (the entity): its slot in the fixed /meta order.
const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);

/** Thin segmented bar (one whole split by status category) + legend with the counts. */
function Progress({ release, categories }) {
  const parts = (categories ?? release.progress.map((p) => ({ value: p.category, label: p.category })))
    .map((c, i) => ({ ...c, color: SERIES[i] ?? "var(--series-other)", ...(release.progress.find((p) => p.category === c.value) ?? { count: 0, points: 0 }) }));
  const total = release.total;
  const done = release.done;
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-semibold">{total ? Math.round((done / total) * 100) : 0}%</span>
        <span className="text-sm text-fg-subtle">hecho · {total === 1 ? "1 incidencia" : `${total} incidencias`}</span>
      </div>
      <div className="mt-2 flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-bg-sunken" role="img"
           aria-label={parts.map((p) => `${p.label}: ${p.count}`).join(", ")}>
        {total > 0 && parts.filter((p) => p.count > 0).map((p) => (
          <Tip key={p.value} content={`${p.label}: ${p.count} (${Math.round((p.count / total) * 100)}%)`}>
            <div className="h-full first:rounded-l-full last:rounded-r-full" style={{ width: `${(p.count / total) * 100}%`, backgroundColor: p.color }} />
          </Tip>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-subtle">
        {parts.map((p) => (
          <span key={p.value} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: p.color }} />
            {p.label} <b className="text-fg">{p.count}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export function PlanReleases({ plan }) {
  const meta = useMeta();
  const qc = useQueryClient();
  const releases = usePlanReleases(plan.id);
  const [editing, setEditing] = useState(null); // null | "new" | release
  const [removing, setRemoving] = useState(null);
  const remove = useMutation({
    mutationFn: (r) => unwrap(api.DELETE("/api/v1/plans/{pid}/releases/{rid}", { params: { path: { pid: plan.id, rid: r.id } } })),
    onSuccess: () => { setRemoving(null); qc.invalidateQueries({ queryKey: planKeys.releases(plan.id) }); toast.success("Versión del plan eliminada"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (releases.isPending) return <PageSpinner />;
  if (releases.error) return <p className="px-6 py-4 text-sm text-danger">{errorMessage(releases.error)}</p>;
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-8">
      <div className="flex items-center gap-3 pb-3">
        <p className="text-sm text-fg-subtle">Agrupa versiones de varios proyectos bajo una fecha objetivo común y sigue su progreso conjunto.</p>
        {plan.can_edit && <Button variant="primary" className="ml-auto" onClick={() => setEditing("new")}><Plus size={16} />Crear versión entre proyectos</Button>}
      </div>
      {!releases.data.length ? (
        <EmptyState icon={<Package size={40} />} title="Sin versiones entre proyectos"
                    body="Por ejemplo, «Lanzamiento de invierno» puede agrupar la 2.0 de la web, la 1.4 de la app y la Q4 de la plataforma." />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {releases.data.map((r) => (
            <section key={r.id} className="rounded-[3px] border border-line p-4">
              <header className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <h2 className="truncate text-base font-semibold">{r.name}</h2>
                  <p className="text-sm text-fg-subtle">{r.target_date ? `Fecha objetivo: ${fmtDate(r.target_date)}` : "Sin fecha objetivo"}</p>
                </div>
                {plan.can_edit && (
                  <Menu>
                    <MenuTrigger asChild><Button variant="subtle" size="icon-sm" aria-label={`Acciones de ${r.name}`}><MoreHorizontal size={16} /></Button></MenuTrigger>
                    <MenuContent align="end">
                      <MenuItem onSelect={() => setEditing(r)}><Pencil size={14} />Editar</MenuItem>
                      <MenuItem danger onSelect={() => setRemoving(r)}><Trash2 size={14} />Eliminar</MenuItem>
                    </MenuContent>
                  </Menu>
                )}
              </header>
              {r.description && <p className="mt-1 whitespace-pre-wrap text-sm">{r.description}</p>}
              <div className="mt-3"><Progress release={r} categories={meta.data?.status_categories} /></div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {r.versions.map((v) => (
                  <span key={v.id} title={v.late ? "Su fecha de publicación es posterior a la fecha objetivo" : undefined}
                        className="inline-flex items-center gap-1.5 rounded-[3px] border border-line px-1.5 py-0.5 text-xs">
                    <ProjectAvatar project={v.project} size={14} />
                    <Link className="hover:underline" href={`/projects/${v.project.key}/releases`}>{v.project.key} · {v.name}</Link>
                    <span className="text-fg-subtle">{choiceLabel(meta.data?.version_statuses, v.status)}{v.release_date ? ` · ${fmtDate(v.release_date, "d MMM")}` : ""}</span>
                    {v.late && <AlertTriangle size={12} className="text-warning" aria-label="Posterior a la fecha objetivo" />}
                    {v.deleted && <span className="text-fg-subtlest">(eliminada)</span>}
                  </span>
                ))}
                {!r.versions.length && <span className="text-sm text-fg-subtlest">Sin versiones</span>}
              </div>
              {r.late_count > 0 && (
                <div className="mt-3 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">
                  <p className="flex items-center gap-1.5 font-medium"><AlertTriangle size={14} className="text-warning" />
                    {r.late_count === 1 ? "1 incidencia vence" : `${r.late_count} incidencias vencen`} después de la fecha objetivo</p>
                  <ul className="mt-1 space-y-0.5">
                    {r.late_issues.slice(0, 8).map((i) => (
                      <li key={i.id} className="flex items-center gap-2">
                        <Link className="font-medium text-link hover:underline" href={`/browse/${i.key}`}>{i.key}</Link>
                        <span className="min-w-0 flex-1 truncate">{i.summary}</span>
                        <span className="shrink-0 text-xs text-fg-subtle">{fmtDate(i.due_date, "d MMM yyyy")}</span>
                        <Lozenge category={i.status.category} className="max-w-24 shrink-0">{i.status.name}</Lozenge>
                      </li>
                    ))}
                  </ul>
                  {r.late_count > 8 && <p className="mt-1 text-xs text-fg-subtle">y {r.late_count - 8} más</p>}
                </div>
              )}
            </section>
          ))}
        </div>
      )}
      <Modal open={!!editing} onOpenChange={(o) => !o && setEditing(null)} title={editing && editing !== "new" ? "Editar versión entre proyectos" : "Crear versión entre proyectos"} width={600}>
        {editing && <ReleaseForm plan={plan} release={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      </Modal>
      <Confirm open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} danger loading={remove.isPending}
               title={`¿Eliminar «${removing?.name ?? ""}»?`} confirmLabel="Eliminar" onConfirm={() => remove.mutate(removing)}
               body="Solo se elimina la agrupación del plan. Las versiones de cada proyecto y sus incidencias no cambian." />
    </div>
  );
}

function ReleaseForm({ plan, release, onClose }) {
  const qc = useQueryClient();
  const options = usePlanVersionOptions(plan.id);
  const [name, setName] = useState(release?.name ?? "");
  const [description, setDescription] = useState(release?.description ?? "");
  const [target, setTarget] = useState(release?.target_date ?? "");
  const [versions, setVersions] = useState(release?.versions ?? []);
  const [error, setError] = useState(null);
  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, target_date: target || null, version_ids: versions.map((v) => v.id) };
      return release
        ? unwrap(api.PATCH("/api/v1/plans/{pid}/releases/{rid}", { params: { path: { pid: plan.id, rid: release.id } }, body }))
        : unwrap(api.POST("/api/v1/plans/{pid}/releases", { params: { path: { pid: plan.id } }, body }));
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: planKeys.releases(plan.id) }); onClose(); },
    onError: (e) => setError(errorMessage(e)),
  });
  const all = options.data ?? [];
  const toggle = (id) => {
    const v = all.find((x) => x.id === id);
    setVersions((vs) => (vs.some((x) => x.id === id) ? vs.filter((x) => x.id !== id) : v ? [...vs, v] : vs));
  };
  return (
    <form className="space-y-4 pb-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label="Nombre" required><Input autoFocus value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Descripción"><Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Fecha objetivo" hint="Se avisa de las incidencias que vencen después."><Input type="date" value={target ?? ""} onChange={(e) => setTarget(e.target.value)} /></Field>
      <Field label="Versiones de los proyectos">
        <div className="flex flex-wrap items-center gap-1.5">
          {versions.map((v) => (
            <span key={v.id} className="inline-flex items-center gap-1 rounded-full bg-bg-sunken py-0.5 pl-1 pr-1.5 text-xs">
              <ProjectAvatar project={v.project} size={14} />{v.project.key} · {v.name}
              <button type="button" aria-label={`Quitar ${v.name}`} onClick={() => toggle(v.id)} className="rounded-full hover:bg-bg-pressed"><X size={12} /></button>
            </span>
          ))}
          <Picker multiple value={versions.map((v) => v.id)} onSelect={toggle} loading={options.isFetching} placeholder="Buscar versiones" width={340}
                  emptyText="Los proyectos del plan no tienen versiones"
                  options={all.map((v) => ({ value: v.id, label: `${v.project.key} · ${v.name}`, description: v.release_date ? fmtDate(v.release_date) : "Sin fecha", icon: <ProjectAvatar project={v.project} size={18} /> }))}
                  trigger={<Button size="sm" type="button"><Plus size={14} />Añadir versión</Button>} />
        </div>
      </Field>
      {error && <p role="alert" className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="subtle" onClick={onClose}>Cancelar</Button>
        <Button type="submit" variant="primary" disabled={!name.trim()} loading={save.isPending}>Guardar</Button>
      </div>
    </form>
  );
}
