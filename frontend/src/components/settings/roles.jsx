"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageSpinner } from "@/components/ui/button";
import { Badge, Field, Input, Modal, Tip } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "./catalog";

/** Permission matrix: one column per role, edited in place and saved per role. */
export function RolesMatrix() {
  const qc = useQueryClient();
  const [view, setView] = useState("active");
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  const perms = useQuery({ queryKey: ["permissions"], queryFn: () => unwrap(api.GET("/api/v1/permissions")) });
  const deleted = useDeletedList("/api/v1/roles", "roles", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/roles", queryKey: "roles", related: ["project-meta", "members"] });
  const [draft, setDraft] = useState({});
  const [creating, setCreating] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["roles"] }); qc.invalidateQueries({ queryKey: ["project-meta"] }); };
  const save = useMutation({
    mutationFn: (r) => unwrap(api.PUT("/api/v1/roles/{role_id}", { params: { path: { role_id: r.id } }, body: { name: r.name, description: r.description, permissions: draft[r.id] ?? r.permissions, is_default: r.is_default } })),
    onSuccess: (r) => { toast.success(`Rol «${r.name}» guardado`); setDraft((d) => { const next = { ...d }; delete next[r.id]; return next; }); refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const setDefault = useMutation({
    mutationFn: (r) => unwrap(api.PUT("/api/v1/roles/{role_id}", { params: { path: { role_id: r.id } }, body: { name: r.name, description: r.description, permissions: r.permissions, is_default: true } })),
    onSuccess: refresh, onError: (e) => toast.error(errorMessage(e)),
  });
  if (!roles.data || !perms.data) return <PageSpinner />;
  const current = (r) => draft[r.id] ?? r.permissions;
  // Locked = granted to every role by the server (e.g. «Ver proyecto») or pinned on this role.
  const isLocked = (r, p) => !!p.always || (r.locked_permissions ?? []).includes(p.key);
  const toggle = (r, p) => {
    if (isLocked(r, p)) return;
    const cur = current(r);
    setDraft({ ...draft, [r.id]: cur.includes(p.key) ? cur.filter((x) => x !== p.key) : [...cur, p.key] });
  };
  return (
    <div className="max-w-[1000px]">
      <p className="mb-3 text-sm text-fg-subtle">Los roles definen qué puede hacer cada persona dentro de un proyecto. Se asignan en <i>Proyecto → Configuración → Personas</i>. El rol predeterminado se usa al agregar miembros sin elegir rol. Los roles del sistema se pueden renombrar pero no eliminar, y algunos permisos quedan fijos (<Lock size={11} className="inline" />).</p>
      <div className="flex items-end justify-between gap-3">
        <CatalogTabs value={view} onChange={setView} className="flex-1" />
        {view === "active" && <Button variant="primary" onClick={() => setCreating(true)}><Plus size={16} />Crear rol</Button>}
      </div>
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} empty="No hay roles eliminados." />
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b-2 border-line align-bottom">
                <th className="py-2 text-left text-xs font-semibold text-fg-subtle">Permiso</th>
                {roles.data.map((r) => (
                  <th key={r.id} className="min-w-[120px] px-2 py-2 text-center">
                    <div className="font-semibold">{r.name}</div>
                    <div className="mt-0.5 flex flex-wrap justify-center gap-1 text-[11px] font-normal text-fg-subtle">
                      {r.is_system && <Badge>Sistema</Badge>}
                      {r.is_default ? <Badge>Predeterminado</Badge> : <button className="text-link hover:underline" onClick={() => setDefault.mutate(r)}>Hacer predeterminado</button>}
                      <span>{r.member_count === 1 ? "1 miembro" : `${r.member_count ?? 0} miembros`}</span>
                      {r.in_use && !r.member_count && <span>En uso</span>}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {perms.data.map((p) => (
                <tr key={p.key} className="border-b border-line hover:bg-bg-hover">
                  <td className="py-1.5">{p.label}</td>
                  {roles.data.map((r) => {
                    const on = current(r).includes(p.key);
                    const locked = isLocked(r, p);
                    return (
                      <td key={r.id} className="text-center">
                        <span className="inline-flex items-center gap-1">
                          <input type="checkbox" aria-label={`${p.label} para ${r.name}`} className="h-4 w-4 accent-[var(--brand)]" checked={on || locked} disabled={locked} onChange={() => toggle(r, p)} />
                          {locked && <Lock size={11} className="text-fg-subtlest" aria-hidden />}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr>
                <td />
                {roles.data.map((r) => (
                  <td key={r.id} className="py-2 text-center">
                    <div className="flex justify-center gap-1">
                      <Button size="sm" variant={draft[r.id] ? "primary" : "default"} disabled={!draft[r.id]} loading={save.isPending && save.variables?.id === r.id} onClick={() => save.mutate(r)}>Guardar</Button>
                      {!r.is_system && (r.in_use || r.member_count
                        ? <Tip content="En uso: cambia el rol de sus miembros antes de eliminarlo"><span><Button size="icon" variant="subtle" disabled aria-label={`Eliminar ${r.name}`}><Trash2 size={14} /></Button></span></Tip>
                        : <Button size="icon" variant="subtle" aria-label={`Eliminar ${r.name}`} onClick={() => actions.askDelete(r)}><Trash2 size={14} /></Button>)}
                    </div>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <Modal open={creating} onOpenChange={setCreating} title="Crear rol" width={480}>
        {creating && <CreateRole roles={roles.data} onDone={() => { setCreating(false); refresh(); }} />}
      </Modal>
      {actions.dialog}
    </div>
  );
}

function CreateRole({ roles, onDone }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [base, setBase] = useState(roles.find((r) => r.is_default)?.id ?? "");
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/roles", { body: { name, description, permissions: roles.find((r) => r.id === base)?.permissions ?? [] } })),
    onSuccess: () => { toast.success("Rol creado"); onDone(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <Field label="Nombre" required><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={60} placeholder="Ej. Cliente, QA, Líder técnico" /></Field>
      <Field label="Descripción"><Input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Copiar permisos de">
        <select className={cn("h-8 w-full rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-sm")} value={base} onChange={(e) => setBase(e.target.value ? Number(e.target.value) : "")}>
          <option value="">Ninguno (solo ver)</option>{roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
      </Field>
      <div className="flex justify-end gap-2"><Button type="button" variant="subtle" onClick={onDone}>Cancelar</Button><Button type="submit" variant="primary" disabled={!name.trim()} loading={create.isPending}>Crear</Button></div>
    </form>
  );
}
