"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  EmptyState, Field, Input, Lozenge, Menu, MenuContent, MenuItem, MenuSeparator,
  MenuTrigger, Modal, Textarea,
} from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, qk, useMeta, useProjectMeta } from "@/lib/api/hooks";
import { fmtDate } from "@/lib/utils";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";

// Labels from GET /meta (version_statuses); only the lozenge colour is decided here.
const STATUS_CATEGORY = { released: "done" };

export default function ReleasesPage({ params }) {
  const { key: raw } = use(params);
  const key = raw.toUpperCase();
  const qc = useQueryClient();
  const meta = useProjectMeta(key);
  const appMeta = useMeta();
  const [editing, setEditing] = useState(null);
  const [view, setView] = useState("active");
  const isAdmin = meta.data?.permissions.includes("administer");
  const refresh = () => qc.invalidateQueries({ queryKey: qk.meta(key) });

  const patch = useMutation({
    mutationFn: ({ id, body }) =>
      unwrap(api.PATCH("/api/v1/projects/{key}/versions/{vid}", { params: { path: { key, vid: id } }, body })),
    onSuccess: refresh, onError: (e) => toast.error(errorMessage(e)),
  });
  const path = `/api/v1/projects/${key}/versions`;
  const deleted = useDeletedList(path, `versions-${key}`, view === "deleted");
  const actions = useCatalogActions({ path, queryKey: `versions-${key}`, related: ["project-meta", "issue"],
                                      softBody: "Deja de ofrecerse al editar incidencias; las que ya la tienen la conservan." });

  const versions = meta.data?.versions ?? [];
  return (
    <div className="flex-1 overflow-y-auto px-6 py-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-medium">Versiones</h1>
        {isAdmin && <Button variant="primary" onClick={() => setEditing("new")}>Crear versión</Button>}
      </div>
      {isAdmin && <CatalogTabs value={view} onChange={setView} className="mt-4 max-w-[1100px]" />}
      {view === "deleted" ? (
        <div className="max-w-[1100px]"><DeletedList query={deleted} actions={actions} allowPurge={false} empty="No hay versiones eliminadas." /></div>
      ) : versions.length ? (
        <table className="mt-6 w-full max-w-[1100px] text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
            <th className="py-2">Versión</th><th className="py-2">Estado</th><th className="w-64 py-2">Progreso</th>
            <th className="py-2">Inicio</th><th className="py-2">Publicación</th><th className="py-2">Descripción</th><th className="w-10" /></tr></thead>
          <tbody>
            {versions.map((v) => {
              const pct = v.issue_count ? Math.round(((v.done_count ?? 0) / v.issue_count) * 100) : 0;
              const late = v.status === "unreleased" && v.release_date && v.release_date < new Date().toISOString().slice(0, 10);
              return (
                <tr key={v.id} className="border-b border-line hover:bg-bg-hover">
                  <td className="py-2"><Link className="font-medium text-link hover:underline" href={`/projects/${key}/issues?jql=${encodeURIComponent(`project = ${key} AND fixVersion = "${v.name}" ORDER BY rank`)}`}>{v.name}</Link></td>
                  <td className="py-2"><Lozenge category={STATUS_CATEGORY[v.status] ?? "todo"}>{choiceLabel(appMeta.data?.version_statuses, v.status)}</Lozenge>{late && <Lozenge category="todo" className="ml-1 bg-danger-subtle text-danger">Atrasada</Lozenge>}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-bg-sunken"><div className="h-full bg-success" style={{ width: `${pct}%` }} /></div>
                      <span className="w-24 text-xs text-fg-subtle">{v.done_count}/{v.issue_count} listas</span>
                    </div>
                  </td>
                  <td className="py-2 text-fg-subtle">{fmtDate(v.start_date)}</td>
                  <td className="py-2 text-fg-subtle">{fmtDate(v.release_date)}</td>
                  <td className="max-w-64 truncate py-2 text-fg-subtle">{v.description}</td>
                  <td className="py-2">
                    {isAdmin && (
                      <Menu>
                        <MenuTrigger asChild><Button variant="subtle" size="icon-sm" aria-label="Acciones"><MoreHorizontal size={16} /></Button></MenuTrigger>
                        <MenuContent align="end">
                          {v.status === "unreleased" && <MenuItem onSelect={() => patch.mutate({ id: v.id, body: { status: "released" } })}>Publicar</MenuItem>}
                          {v.status === "released" && <MenuItem onSelect={() => patch.mutate({ id: v.id, body: { status: "unreleased" } })}>Anular publicación</MenuItem>}
                          {v.status !== "archived" ? <MenuItem onSelect={() => patch.mutate({ id: v.id, body: { status: "archived" } })}>Archivar</MenuItem>
                            : <MenuItem onSelect={() => patch.mutate({ id: v.id, body: { status: "unreleased" } })}>Desarchivar</MenuItem>}
                          <MenuItem onSelect={() => setEditing(v)}>Editar</MenuItem>
                          <MenuSeparator />
                          <MenuItem danger onSelect={() => actions.askDelete(v)}>Eliminar</MenuItem>
                        </MenuContent>
                      </Menu>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : <EmptyState title="Aún no hay versiones" body="Las versiones agrupan incidencias que se publican juntas." />}
      {editing && <VersionDialog projectKey={key} version={editing === "new" ? null : editing} onClose={() => { setEditing(null); refresh(); }} />}
      {actions.dialog}
    </div>
  );
}

function VersionDialog({ projectKey, version, onClose }) {
  const [name, setName] = useState(version?.name ?? "");
  const [start, setStart] = useState(version?.start_date ?? "");
  const [release, setRelease] = useState(version?.release_date ?? "");
  const [description, setDescription] = useState(version?.description ?? "");
  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, start_date: start || null, release_date: release || null };
      return version
        ? unwrap(api.PATCH("/api/v1/projects/{key}/versions/{vid}", { params: { path: { key: projectKey, vid: version.id } }, body }))
        : unwrap(api.POST("/api/v1/projects/{key}/versions", { params: { path: { key: projectKey } }, body }));
    },
    onSuccess: onClose, onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={version ? "Editar versión" : "Crear versión"} width={480}
           footer={<><Button variant="subtle" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" disabled={!name.trim()} loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button></>}>
      <div className="space-y-4">
        <Field label="Nombre" required><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="v1.0" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Fecha de inicio"><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Fecha de publicación"><Input type="date" value={release} onChange={(e) => setRelease(e.target.value)} /></Field>
        </div>
        <Field label="Descripción"><Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
