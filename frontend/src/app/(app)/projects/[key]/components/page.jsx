"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { toast } from "sonner";
import { UserPicker } from "@/components/issue/pickers";
import { Button } from "@/components/ui/button";
import { Avatar, EmptyState, Field, Input, Modal, Textarea } from "@/components/ui/primitives";
import { useApp } from "@/components/shell/app-context";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { qk, useProjectMeta, useUsers } from "@/lib/api/hooks";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";

export default function ComponentsPage({ params }) {
  const { key: raw } = use(params);
  const key = raw.toUpperCase();
  const qc = useQueryClient();
  const meta = useProjectMeta(key);
  const [editing, setEditing] = useState(null);
  const [view, setView] = useState("active");
  const isAdmin = meta.data?.permissions.includes("administer");
  const path = `/api/v1/projects/${key}/components`;
  const deleted = useDeletedList(path, `components-${key}`, view === "deleted");
  const actions = useCatalogActions({ path, queryKey: `components-${key}`, related: ["project-meta", "issue"],
                                      softBody: "Deja de ofrecerse al editar incidencias; las que ya lo tienen lo conservan." });
  const comps = meta.data?.components ?? [];
  return (
    <div className="flex-1 overflow-y-auto px-6 py-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-medium">Componentes</h1>
        {isAdmin && <Button variant="primary" onClick={() => setEditing("new")}>Crear componente</Button>}
      </div>
      <p className="mt-1 text-sm text-fg-subtle">Agrupa incidencias por partes del producto (ej. API, Web, App móvil).</p>
      {isAdmin && <CatalogTabs value={view} onChange={setView} className="mt-4 max-w-[1000px]" />}
      {view === "deleted" ? (
        <div className="max-w-[1000px]"><DeletedList query={deleted} actions={actions} allowPurge={false} empty="No hay componentes eliminados." /></div>
      ) : comps.length ? (
        <table className="mt-6 w-full max-w-[1000px] text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
            <th className="py-2">Componente</th><th className="py-2">Descripción</th><th className="py-2">Responsable</th><th className="py-2 text-right">Incidencias</th><th className="w-10" /></tr></thead>
          <tbody>
            {comps.map((c) => (
              <tr key={c.id} className="border-b border-line hover:bg-bg-hover">
                <td className="py-2">{isAdmin ? <button className="font-medium text-link hover:underline" onClick={() => setEditing(c)}>{c.name}</button> : c.name}</td>
                <td className="max-w-80 truncate py-2 text-fg-subtle">{c.description}</td>
                <td className="py-2">{c.lead ? <span className="flex items-center gap-2"><Avatar user={c.lead} size="xs" />{c.lead.name}</span> : <span className="text-fg-subtlest">—</span>}</td>
                <td className="py-2 text-right"><Link className="text-link hover:underline" href={`/projects/${key}/issues?jql=${encodeURIComponent(`project = ${key} AND component = "${c.name}"`)}`}>{c.issue_count}</Link></td>
                <td className="py-2 text-right">{isAdmin && <Button variant="subtle" size="icon-sm" aria-label="Eliminar" onClick={() => actions.askDelete(c)}><Trash2 size={14} /></Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <EmptyState title="Aún no hay componentes" />}
      {editing && <ComponentDialog projectKey={key} comp={editing === "new" ? null : editing}
                                   onClose={() => { setEditing(null); qc.invalidateQueries({ queryKey: qk.meta(key) }); }} />}
      {actions.dialog}
    </div>
  );
}

function ComponentDialog({ projectKey, comp, onClose }) {
  const { me } = useApp();
  const [name, setName] = useState(comp?.name ?? "");
  const [description, setDescription] = useState(comp?.description ?? "");
  const [lead, setLead] = useState(comp?.lead?.id ?? null);
  const users = useUsers("", projectKey);
  const leadUser = users.data?.find((u) => u.id === lead) ?? (comp?.lead?.id === lead ? comp?.lead : null);
  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, lead_id: lead };
      return comp
        ? unwrap(api.PATCH("/api/v1/projects/{key}/components/{cid}", { params: { path: { key: projectKey, cid: comp.id } }, body }))
        : unwrap(api.POST("/api/v1/projects/{key}/components", { params: { path: { key: projectKey } }, body }));
    },
    onSuccess: onClose, onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={comp ? "Editar componente" : "Crear componente"} width={480}
           footer={<><Button variant="subtle" onClick={onClose}>Cancelar</Button>
             <Button variant="primary" disabled={!name.trim()} loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button></>}>
      <div className="space-y-4">
        <Field label="Nombre" required><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Descripción"><Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <Field label="Responsable del componente">
          <UserPicker projectKey={projectKey} meId={me.id} value={lead} onSelect={setLead} noneLabel="Ninguno"
                      trigger={<button className="flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm">
                        <Avatar user={leadUser ?? null} size="xs" />{leadUser?.name ?? "Ninguno"}</button>} />
        </Field>
      </div>
    </Modal>
  );
}
