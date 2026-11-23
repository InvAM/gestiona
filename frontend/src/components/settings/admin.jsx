"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { useApp } from "@/components/shell/app-context";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, Badge, Checkbox, EmptyState, Field, Input, Lozenge, Modal, Textarea, Toggle } from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { AutomationRules } from "@/components/automation/rules";
import { AuditLog } from "./audit-log";
import { JiraImport } from "./jira-import";
import { Provisioning } from "./provisioning";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "./catalog";
import { RolesMatrix } from "./roles";
import {
  COLLECTIONS, FieldConfigurationSchemes, FieldConfigurations, IssueTypeScreenSchemes, ScreenSchemes, Screens,
  useCollection, useFieldCatalog,
} from "./fields-admin";
import { cn, fmtRelative } from "@/lib/utils";

export const ADMIN_SECTIONS = [
  ["users", "Usuarios"], ["roles", "Roles y permisos"], ["provisioning", "SSO y SCIM"], ["workflows", "Flujos de trabajo"], ["statuses", "Estados"],
  ["issue-types", "Tipos de incidencia"], ["priorities", "Prioridades"], ["resolutions", "Resoluciones"], ["fields", "Campos personalizados"],
  ["field-configurations", "Configuraciones de campos"], ["field-configuration-schemes", "Esquemas de configuración de campos"],
  ["screens", "Pantallas"], ["screen-schemes", "Esquemas de pantalla"], ["issue-type-screen-schemes", "Esquemas de pantalla por tipo"],
  ["links", "Tipos de vínculo"], ["project-categories", "Categorías de proyecto"], ["automation", "Automatización global"], ["audit", "Registro de auditoría"], ["import", "Importar desde Jira"],
];

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

// Status categories, issue type levels and custom field kinds come from GET /meta.
function useChoices(key) {
  return useMeta().data?.[key] ?? [];
}

/* ------------------------------------------------------------------ users */

function Users() {
  const qc = useQueryClient();
  const { me } = useApp();
  const [q, setQ] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const users = useQuery({ queryKey: ["admin-users", q], queryFn: () => unwrap(api.GET("/api/v1/admin/users", { params: { query: { q } } })) });
  const patch = useMutation({
    mutationFn: ({ id, body }) => unwrap(api.PATCH("/api/v1/admin/users/{user_id}", { params: { path: { user_id: id } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }), onError: (e) => toast.error(errorMessage(e)),
  });
  const resend = useMutation({
    mutationFn: (id) => unwrap(api.POST("/api/v1/admin/users/{user_id}/invite", { params: { path: { user_id: id } } })),
    onSuccess: () => toast.success("Invitación enviada"), onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div>
      <div className="flex items-center gap-3">
        <Input placeholder="Buscar por nombre o email" value={q} onChange={(e) => setQ(e.target.value)} className="w-72" />
        <Button variant="primary" className="ml-auto" onClick={() => setInviteOpen(true)}><Plus size={16} />Invitar usuario</Button>
      </div>
      {users.isPending ? <PageSpinner /> : (
        <table className="mt-4 w-full text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
            <th className="py-2">Usuario</th><th className="py-2">Último acceso</th><th className="py-2">Administrador</th><th className="py-2">Activo</th><th className="w-32" /></tr></thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className={cn("border-b border-line", u.active === false && "opacity-60")}>
                <td className="py-2"><span className="flex items-center gap-2"><Avatar user={u} size="md" />
                  <span><span className="block font-medium">{u.name}</span><span className="block text-xs text-fg-subtle">{u.email}</span></span></span></td>
                <td className="py-2 text-fg-subtle">{u.last_login ? fmtRelative(u.last_login) : "Nunca"}</td>
                <td className="py-2"><Toggle label="Administrador" checked={u.is_admin} onChange={(v) => {
                  if (!me.is_superuser) return toast.error("Solo un superadministrador puede cambiar esto");
                  patch.mutate({ id: u.id, body: { is_admin: v } });
                }} /></td>
                <td className="py-2"><Toggle label="Activo" checked={u.active ?? true} onChange={(v) => patch.mutate({ id: u.id, body: { is_active: v } })} /></td>
                <td className="py-2 text-right">{!u.last_login && u.active && <Button size="sm" variant="subtle" loading={resend.isPending} onClick={() => resend.mutate(u.id)}>Reenviar invitación</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} />
    </div>
  );
}

function InviteDialog({ open, onOpenChange }) {
  const qc = useQueryClient();
  const { me } = useApp();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const invite = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/admin/users", { body: { email, full_name: name, is_admin: isAdmin, send_invite: true } })),
    onSuccess: () => { toast.success(`Invitación enviada a ${email}`); setEmail(""); setName(""); onOpenChange(false); qc.invalidateQueries({ queryKey: ["admin-users"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Invitar usuario" width={460}
           footer={<><Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant="primary" disabled={!email} loading={invite.isPending} onClick={() => invite.mutate()}>Enviar invitación</Button></>}>
      <div className="space-y-4">
        <Field label="Email" required><Input type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Nombre completo"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        {me.is_superuser && <Checkbox checked={isAdmin} onChange={setIsAdmin} label="Administrador del sistema (puede crear proyectos y configurar Gestiona)" />}
        <p className="text-xs text-fg-subtle">Recibirá un correo con un enlace para crear su contraseña.</p>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ workflows */

function Workflows() {
  const router = useRouter();
  const qc = useQueryClient();
  const wfs = useQuery({ queryKey: ["workflows"], queryFn: () => unwrap(api.GET("/api/v1/workflows")) });
  const statuses = useQuery({ queryKey: ["statuses"], queryFn: () => unwrap(api.GET("/api/v1/statuses")) });
  const create = useMutation({
    mutationFn: () => {
      const st = statuses.data ?? [];
      const todo = st.find((s) => s.category === "todo"), prog = st.find((s) => s.category === "in_progress"), done = st.find((s) => s.category === "done");
      const list = [todo, prog, done];
      return unwrap(api.POST("/api/v1/workflows", { body: {
        name: `Nuevo flujo ${(wfs.data?.length ?? 0) + 1}`, initial_status_id: todo.id,
        statuses: list.map((s, i) => ({ status_id: s.id, x: i * 220, y: 0 })),
        transitions: list.map((s) => ({ name: s.name, to_status_id: s.id, from_status_ids: [] })),
      } }));
    },
    onSuccess: (wf) => { qc.invalidateQueries({ queryKey: ["workflows"] }); router.push(`/settings/workflows/${wf.id}`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/workflows", "workflows", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/workflows", queryKey: "workflows", related: ["project-meta"] });
  if (!wfs.data) return <PageSpinner />;
  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <CatalogTabs value={view} onChange={setView} className="flex-1" />
        {view === "active" && <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()}><Plus size={16} />Crear flujo</Button>}
      </div>
      {view === "deleted" ? <DeletedList query={deleted} actions={actions} empty="No hay flujos eliminados." /> : <div className="mt-4 space-y-3">
        {wfs.data.map((w) => (
          <Link key={w.id} href={`/settings/workflows/${w.id}`} className="block rounded-[3px] border border-line p-4 hover:bg-bg-hover">
            <div className="flex items-center gap-3"><b>{w.name}</b><span className="text-xs text-fg-subtle">Usado por: {w.project_keys.join(", ") || "ningún proyecto"}</span></div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {w.statuses.map((s, i) => <span key={s.status.id} className="flex items-center gap-2"><Lozenge category={s.status.category}>{s.status.name}</Lozenge>{i < w.statuses.length - 1 && "→"}</span>)}
            </div>
          </Link>
        ))}
      </div>}
      {actions.dialog}
    </div>
  );
}

export function WorkflowEditor({ id }) {
  const wf = useQuery({ queryKey: ["workflow", id], queryFn: () => unwrap(api.GET("/api/v1/workflows/{wid}", { params: { path: { wid: id } } })) });
  if (!wf.data) return <PageSpinner />;
  return <WorkflowForm key={wf.dataUpdatedAt} id={id} wf={wf.data} />;
}

function WorkflowForm({ id, wf: initialWf }) {
  const qc = useQueryClient();
  const router = useRouter();
  const wf = { data: initialWf };
  const statuses = useQuery({ queryKey: ["statuses"], queryFn: () => unwrap(api.GET("/api/v1/statuses")) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  const resolutions = useQuery({ queryKey: ["resolutions"], queryFn: () => unwrap(api.GET("/api/v1/resolutions")) });
  const screens = useCollection(COLLECTIONS.screens);
  const fieldCatalog = useFieldCatalog();
  const cats = useChoices("status_categories");
  const [name, setName] = useState(initialWf.name);
  const [description, setDescription] = useState(initialWf.description);
  const [templates, setTemplates] = useState(initialWf.templates ?? []);
  const templateChoices = useChoices("project_templates");
  const [initial, setInitial] = useState(initialWf.initial_status_id);
  const [sts, setSts] = useState(() => initialWf.statuses.map((s) => ({ status_id: s.status.id, x: s.x, y: s.y })));
  const [trs, setTrs] = useState(() => initialWf.transitions.map((t) => ({ ...t })));
  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/workflows/{wid}", { params: { path: { wid: id } }, body: { name, description, templates, initial_status_id: initial, statuses: sts, transitions: trs } })),
    onSuccess: () => { toast.success("Flujo guardado"); qc.invalidateQueries(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const actions = useCatalogActions({ path: "/api/v1/workflows", queryKey: "workflows", related: ["project-meta"], onDeleted: () => router.push("/settings/workflows") });
  if (!statuses.data) return <PageSpinner />;
  const byId = new Map(statuses.data.map((s) => [s.id, s]));
  const inWf = new Set(sts.map((s) => s.status_id));
  const name_ = (sid) => byId.get(sid)?.name ?? sid;
  const updT = (i, patch) => setTrs(trs.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  const multi = (val, opts, onChange, empty) => (
    <Picker multiple value={val ?? []} options={opts} width={260} onSelect={(v) => onChange((val ?? []).includes(v) ? (val ?? []).filter((x) => x !== v) : [...(val ?? []), v])}
            trigger={<button className={cn(sel, "h-auto min-h-8 py-1 text-xs")}>{val?.length ? opts.filter((o) => val.includes(o.value)).map((o) => o.label).join(", ") : <span className="text-fg-subtlest">{empty}</span>}</button>} />
  );
  return (
    <div className="space-y-8">
      <div className="flex items-center gap-2">
        <Link href="/settings/workflows" className="text-sm text-link hover:underline">← Flujos</Link>
        <div className="ml-auto flex gap-2">
          {!wf.data.project_keys.length && <Button variant="subtle" onClick={() => actions.askDelete(wf.data)}><Trash2 size={16} />Eliminar</Button>}
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Guardar flujo</Button>
        </div>
      </div>
      {wf.data.project_keys.length > 0 && <div className="rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">Este flujo lo usan: <b>{wf.data.project_keys.join(", ")}</b>. Los cambios aplican a todos.</div>}
      <div className="grid max-w-[720px] gap-4 sm:grid-cols-2">
        <Field label="Nombre" required><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Estado inicial" required>
          <Picker value={initial} width={280} onSelect={setInitial} options={sts.map((s) => ({ value: s.status_id, label: String(name_(s.status_id)) }))}
                  trigger={<button className={sel}>{name_(initial)}</button>} />
        </Field>
        <Field label="Descripción" className="sm:col-span-2"><Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        <Field label="Plantillas de proyecto" className="sm:col-span-2" hint="Los proyectos nuevos de estas plantillas usan este flujo.">
          <div className="flex flex-wrap gap-x-4 gap-y-1">{templateChoices.map((t) => (
            <Checkbox key={t.value} label={t.label} checked={templates.includes(t.value)} onChange={(on) => setTemplates(on ? [...templates, t.value] : templates.filter((x) => x !== t.value))} />
          ))}</div>
        </Field>
      </div>
      <section>
        <h2 className="text-lg font-medium">Estados</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {sts.map((s, i) => {
            const st = byId.get(s.status_id);
            return (
              <span key={s.status_id} className="flex items-center gap-1 rounded-[3px] border border-line bg-bg py-1 pl-2 pr-1">
                <Lozenge category={st?.category ?? "todo"}>{st?.name}</Lozenge>
                <button aria-label="Mover antes" disabled={i === 0} className="px-0.5 disabled:opacity-30" onClick={() => { const n = [...sts]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setSts(n); }}>‹</button>
                <button aria-label="Mover después" disabled={i === sts.length - 1} className="px-0.5 disabled:opacity-30" onClick={() => { const n = [...sts]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; setSts(n); }}>›</button>
                <button aria-label="Quitar estado" className="rounded p-0.5 hover:bg-bg-hover" onClick={() => {
                  setSts(sts.filter((x) => x.status_id !== s.status_id));
                  setTrs(trs.filter((t) => t.to_status_id !== s.status_id).map((t) => ({ ...t, from_status_ids: (t.from_status_ids ?? []).filter((f) => f !== s.status_id) })));
                }}><X size={12} /></button>
              </span>
            );
          })}
          <Picker options={statuses.data.filter((s) => !inWf.has(s.id)).map((s) => ({ value: s.id, label: s.name, description: choiceLabel(cats, s.category) }))}
                  onSelect={(sid) => { setSts([...sts, { status_id: sid, x: sts.length * 220, y: 0 }]); setTrs([...trs, { name: byId.get(sid).name, to_status_id: sid, from_status_ids: [] }]); }}
                  trigger={<Button size="sm"><Plus size={14} />Agregar estado</Button>} />
        </div>
      </section>
      <section>
        <h2 className="text-lg font-medium">Transiciones</h2>
        <p className="mt-1 text-sm text-fg-subtle">Sin estados de origen = la transición está disponible desde cualquier estado.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[1200px] text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
              <th className="py-2">Nombre</th><th className="py-2">Desde</th><th className="py-2">Hacia</th><th className="py-2">Solo roles</th>
              <th className="py-2">Reglas</th><th className="py-2">Resolución</th><th className="py-2">Pantalla y campos obligatorios</th><th className="w-8" /></tr></thead>
            <tbody>
              {trs.map((t, i) => (
                <tr key={i} className="border-b border-line align-top">
                  <td className="py-2 pr-2"><Input value={t.name} onChange={(e) => updT(i, { name: e.target.value })} /></td>
                  <td className="w-56 py-2 pr-2">{multi(t.from_status_ids ?? [], sts.map((s) => ({ value: s.status_id, label: String(name_(s.status_id)) })), (v) => updT(i, { from_status_ids: v }), "Cualquier estado")}</td>
                  <td className="w-40 py-2 pr-2">
                    <Picker value={t.to_status_id} width={220} onSelect={(v) => updT(i, { to_status_id: v })} options={sts.map((s) => ({ value: s.status_id, label: String(name_(s.status_id)) }))}
                            trigger={<button className={sel}>{name_(t.to_status_id)}</button>} />
                  </td>
                  <td className="w-44 py-2 pr-2">{multi(t.required_role_ids ?? [], (roles.data ?? []).map((r) => ({ value: r.id, label: r.name })), (v) => updT(i, { required_role_ids: v }), "Todos")}</td>
                  <td className="py-2 pr-2 text-xs">
                    <div className="space-y-1">
                      <Checkbox checked={!!t.only_assignee} onChange={(v) => updT(i, { only_assignee: v })} label="Solo el responsable" />
                      <Checkbox checked={!!t.require_comment} onChange={(v) => updT(i, { require_comment: v })} label="Pedir comentario" />
                      <Checkbox checked={!!t.assign_to_current_user} onChange={(v) => updT(i, { assign_to_current_user: v })} label="Asignar a quien la ejecuta" />
                    </div>
                  </td>
                  <td className="w-48 py-2 pr-2 text-xs">
                    <div className="space-y-1">
                      <Checkbox checked={!!t.require_resolution} onChange={(v) => updT(i, { require_resolution: v })} label="Pedir resolución" />
                      <Checkbox checked={!!t.clear_resolution} onChange={(v) => updT(i, { clear_resolution: v })} label="Limpiar resolución" />
                      <Picker value={t.set_resolution_id ?? 0} width={220} onSelect={(v) => updT(i, { set_resolution_id: v || null })}
                              options={[{ value: 0, label: "No fijar resolución" }, ...(resolutions.data ?? []).map((r) => ({ value: r.id, label: r.name }))]}
                              trigger={<button className={cn(sel, "h-7 text-xs")}>{resolutions.data?.find((r) => r.id === t.set_resolution_id)?.name ?? "No fijar resolución"}</button>} />
                    </div>
                  </td>
                  <td className="w-60 py-2 pr-2 text-xs">
                    <div className="space-y-1">
                      <Picker value={t.screen_id ?? 0} width={260} onSelect={(v) => updT(i, { screen_id: v || null })} placeholder="Pantalla"
                              options={[{ value: 0, label: "Sin pantalla", description: "La transición no pide campos" }, ...(screens.data ?? []).map((s) => ({ value: s.id, label: s.name, description: s.description }))]}
                              trigger={<button className={cn(sel, "h-7 text-xs")} aria-label={`Pantalla de «${t.name}»`}>{screens.data?.find((s) => s.id === t.screen_id)?.name ?? (t.screen_id ? "Pantalla eliminada" : "Sin pantalla")}</button>} />
                      {multi(t.required_fields ?? [], (fieldCatalog.data ?? []).filter((f) => f.key !== "summary" && f.key !== "issue_type").map((f) => ({ value: f.key, label: f.label })),
                             (v) => updT(i, { required_fields: v }), "Sin campos obligatorios")}
                      {(t.required_fields ?? []).length > 0 && !t.screen_id && <p className="text-[11px] text-fg-subtle">Se pedirán en un diálogo al hacer la transición.</p>}
                    </div>
                  </td>
                  <td className="py-2"><Button variant="subtle" size="icon-sm" aria-label="Eliminar transición" onClick={() => setTrs(trs.filter((_, j) => j !== i))}><Trash2 size={14} /></Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button size="sm" className="mt-3" onClick={() => sts[0] && setTrs([...trs, { name: "Nueva transición", to_status_id: sts[0].status_id, from_status_ids: [] }])}><Plus size={14} />Agregar transición</Button>
      </section>
      {actions.dialog}
    </div>
  );
}

/* ------------------------------------------------------------------ statuses */

function Statuses() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["statuses"], queryFn: () => unwrap(api.GET("/api/v1/statuses")) });
  const cats = useChoices("status_categories");
  const [name, setName] = useState("");
  const [cat, setCat] = useState("todo");
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/statuses", { body: { name, category: cat } })),
    onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: ["statuses"] }); }, onError: (e) => toast.error(errorMessage(e)),
  });
  const update = useMutation({
    mutationFn: (s) => unwrap(api.PATCH("/api/v1/statuses/{sid}", { params: { path: { sid: s.id } }, body: { name: s.name, category: s.category } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["statuses"] }), onError: (e) => toast.error(errorMessage(e)),
  });
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/statuses", "statuses", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/statuses", queryKey: "statuses", related: ["workflows", "project-meta"] });
  return (
    <div className="max-w-[720px]">
      <CatalogTabs value={view} onChange={setView} className="mb-4" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} render={(s) => <Lozenge category={s.category}>{s.name}</Lozenge>} empty="No hay estados eliminados." />
      ) : (
        <>
          <div className="flex gap-2">
            <Input placeholder="Nombre del estado" value={name} onChange={(e) => setName(e.target.value)} className="w-64" />
            <Picker value={cat} options={cats} onSelect={setCat} width={200} trigger={<button className={cn(sel, "w-40")}><Lozenge category={cat}>{choiceLabel(cats, cat)}</Lozenge></button>} />
            <Button variant="primary" disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>Agregar</Button>
          </div>
          <table className="mt-4 w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Estado</th><th className="py-2">Categoría</th><th className="w-10" /></tr></thead>
            <tbody>{list.data?.map((s) => (
              <tr key={s.id} className="border-b border-line">
                <td className="py-2"><input defaultValue={s.name} onBlur={(e) => e.target.value !== s.name && update.mutate({ ...s, name: e.target.value })} className="rounded px-1 py-0.5 outline-none hover:bg-bg-hover focus:bg-bg-hover" /></td>
                <td className="py-2"><Picker value={s.category} options={cats} width={200} onSelect={(c) => update.mutate({ ...s, category: c })}
                                             trigger={<button><Lozenge category={s.category}>{choiceLabel(cats, s.category)}</Lozenge></button>} /></td>
                <td className="py-2"><Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${s.name}`} onClick={() => actions.askDelete(s)}><Trash2 size={14} /></Button></td>
              </tr>
            ))}</tbody>
          </table>
        </>
      )}
      {actions.dialog}
    </div>
  );
}

/* ------------------------------------------------------------------ issue types / priorities / links */

const ICONS = ["epic", "story", "task", "bug", "subtask"];
const COLORS = ["#904EE2", "#63BA3C", "#4BADE8", "#E5493A", "#FFAB00", "#0E7C86", "#AE2E74", "#44546F"];

function IssueTypes() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["issue-types"], queryFn: () => unwrap(api.GET("/api/v1/issue-types")) });
  const levels = useChoices("issue_type_levels");
  const templates = useChoices("project_templates");
  const [edit, setEdit] = useState(null);
  const save = useMutation({
    mutationFn: () => edit.id
      ? unwrap(api.PATCH("/api/v1/issue-types/{tid}", { params: { path: { tid: edit.id } }, body: edit }))
      : unwrap(api.POST("/api/v1/issue-types", { body: edit })),
    onSuccess: () => { setEdit(null); qc.invalidateQueries({ queryKey: ["issue-types"] }); qc.invalidateQueries({ queryKey: ["project-meta"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/issue-types", "issue-types", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/issue-types", queryKey: "issue-types", related: ["project-meta"] });
  return (
    <div className="max-w-[760px]">
      <div className="flex items-end justify-between gap-3">
        <CatalogTabs value={view} onChange={setView} className="flex-1" />
        {view === "active" && <Button variant="primary" onClick={() => setEdit({ name: "", icon: "task", color: "#4BADE8", level: 0, description: "", templates: [], has_affects_versions: false })}><Plus size={16} />Crear tipo</Button>}
      </div>
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} render={(t) => <span className="flex items-center gap-2"><IssueTypeIcon type={t} />{t.name}</span>} empty="No hay tipos eliminados." />
      ) : (
        <div className="mt-3 space-y-2">
          {list.data?.map((t) => (
            <div key={t.id} className="flex items-center gap-1 rounded-[3px] border border-line pr-1 hover:bg-bg-hover">
              <button onClick={() => setEdit({ ...t, description: t.description ?? "" })} className="flex flex-1 items-center gap-3 px-3 py-2 text-left">
                <IssueTypeIcon type={t} size={22} />
                <span className="flex-1"><b className="text-sm">{t.name}</b><span className="block text-xs text-fg-subtle">{t.description}</span></span>
                <span className="text-xs text-fg-subtle">{choiceLabel(levels, t.level)}</span>
              </button>
              <Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${t.name}`} onClick={() => actions.askDelete(t)}><Trash2 size={14} /></Button>
            </div>
          ))}
        </div>
      )}
      {actions.dialog}
      {edit && (
        <Modal open onOpenChange={(o) => !o && setEdit(null)} title={edit.id ? "Editar tipo" : "Crear tipo"} width={460}
               footer={<><Button variant="subtle" onClick={() => setEdit(null)}>Cancelar</Button><Button variant="primary" disabled={!edit.name} loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button></>}>
          <div className="space-y-4">
            <Field label="Nombre" required><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Descripción"><Input value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            <Field label="Icono"><div className="flex gap-2">{ICONS.map((i) => <button key={i} onClick={() => setEdit({ ...edit, icon: i })} className={cn("rounded p-1", edit.icon === i && "ring-2 ring-brand")}><IssueTypeIcon type={{ icon: i, color: edit.color ?? "#4BADE8" }} size={22} /></button>)}</div></Field>
            <Field label="Color"><div className="flex gap-2">{COLORS.map((c) => <button key={c} aria-label={c} onClick={() => setEdit({ ...edit, color: c })} style={{ background: c }} className={cn("h-6 w-6 rounded", edit.color === c && "ring-2 ring-offset-2 ring-brand")} />)}</div></Field>
            <Field label="Jerarquía">
              <Picker value={edit.level ?? 0} width={300} onSelect={(v) => setEdit({ ...edit, level: v })}
                      options={levels}
                      trigger={<button className={sel}>{choiceLabel(levels, edit.level ?? 0)}</button>} />
            </Field>
            <Field label="Plantillas de proyecto" hint="Los proyectos nuevos de estas plantillas incluyen este tipo.">
              <div className="flex flex-wrap gap-x-4 gap-y-1">{templates.map((t) => (
                <Checkbox key={t.value} label={t.label} checked={(edit.templates ?? []).includes(t.value)}
                          onChange={(on) => setEdit({ ...edit, templates: on ? [...(edit.templates ?? []), t.value] : (edit.templates ?? []).filter((x) => x !== t.value) })} />
              ))}</div>
            </Field>
            <Checkbox checked={!!edit.has_affects_versions} onChange={(v) => setEdit({ ...edit, has_affects_versions: v })} label="Usa «Versión afectada» (p. ej. errores)" />
          </div>
        </Modal>
      )}
    </div>
  );
}

function Priorities() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["priorities"], queryFn: () => unwrap(api.GET("/api/v1/priorities")) });
  const reorder = useMutation({
    mutationFn: (ids) => unwrap(api.PUT("/api/v1/priorities/order", { body: ids })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["priorities"] }); qc.invalidateQueries({ queryKey: ["project-meta"] }); },
  });
  const [name, setName] = useState("");
  const patch = useMutation({
    mutationFn: ({ p, ...changes }) => unwrap(api.PATCH(`/api/v1/priorities/${p.id}`, { body: { name: p.name, icon: p.icon, color: p.color, is_default: p.is_default, ...changes } })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["priorities"] }); qc.invalidateQueries({ queryKey: ["project-meta"] }); }, onError: (e) => toast.error(errorMessage(e)),
  });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/priorities", { body: { name } })),
    onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: ["priorities"] }); }, onError: (e) => toast.error(errorMessage(e)),
  });
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/priorities", "priorities", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/priorities", queryKey: "priorities", related: ["project-meta"] });
  const ids = list.data?.map((p) => p.id) ?? [];
  const move = (i, d) => { const n = [...ids]; [n[i], n[i + d]] = [n[i + d], n[i]]; reorder.mutate(n); };
  return (
    <div className="max-w-[520px]">
      <CatalogTabs value={view} onChange={setView} className="mb-3" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} render={(p) => <span className="flex items-center gap-2"><PriorityIcon priority={p} />{p.name}</span>} empty="No hay prioridades eliminadas." />
      ) : (
        <>
          <p className="text-sm text-fg-subtle">El orden define qué tan alta es cada prioridad (arriba = más alta).</p>
          <div className="mt-3 space-y-1">
            {list.data?.map((p, i) => (
              <div key={p.id} className="flex items-center gap-3 rounded-[3px] border border-line px-3 py-2">
                <PriorityIcon priority={p} />
                <input aria-label="Nombre" defaultValue={p.name} onBlur={(e) => e.target.value.trim() && e.target.value !== p.name && patch.mutate({ p, name: e.target.value.trim() })}
                       className="flex-1 rounded px-1 py-0.5 text-sm outline-none hover:bg-bg-hover focus:bg-bg-hover" />
                {p.is_default ? <Badge>Predeterminada</Badge> : <button className="text-xs text-link hover:underline" onClick={() => patch.mutate({ p, is_default: true })}>Hacer predeterminada</button>}
                <Button variant="subtle" size="icon-sm" disabled={i === 0} aria-label="Subir" onClick={() => move(i, -1)}><ArrowUp size={14} /></Button>
                <Button variant="subtle" size="icon-sm" disabled={i === ids.length - 1} aria-label="Bajar" onClick={() => move(i, 1)}><ArrowDown size={14} /></Button>
                <Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${p.name}`} onClick={() => actions.askDelete(p)}><Trash2 size={14} /></Button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2"><Input placeholder="Nueva prioridad" value={name} onChange={(e) => setName(e.target.value)} /><Button disabled={!name} onClick={() => create.mutate()}>Agregar</Button></div>
        </>
      )}
      {actions.dialog}
    </div>
  );
}

function Resolutions() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["resolutions"], queryFn: () => unwrap(api.GET("/api/v1/resolutions")) });
  const [name, setName] = useState("");
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/resolutions", "resolutions", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/resolutions", queryKey: "resolutions", related: ["project-meta", "workflow"] });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/resolutions", { body: { name } })),
    onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: ["resolutions"] }); }, onError: (e) => toast.error(errorMessage(e)),
  });
  const patch = useMutation({
    mutationFn: ({ r, ...changes }) => unwrap(api.PATCH(`/api/v1/resolutions/${r.id}`, { body: { name: r.name, description: r.description, is_default: r.is_default, ...changes } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["resolutions"] }), onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="max-w-[520px]">
      <CatalogTabs value={view} onChange={setView} className="mb-3" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} empty="No hay resoluciones eliminadas." />
      ) : (
        <>
          <p className="text-sm text-fg-subtle">Indican cómo terminó una incidencia (ej. Hecho, Duplicado, No se hará). Se piden o fijan en las transiciones del flujo.</p>
          <div className="mt-3 space-y-1">
            {list.data?.map((r) => (
              <div key={r.id} className="flex items-center gap-3 rounded-[3px] border border-line px-3 py-1.5">
                <input aria-label="Nombre" defaultValue={r.name} onBlur={(e) => e.target.value.trim() && e.target.value !== r.name && patch.mutate({ r, name: e.target.value.trim() })}
                       className="flex-1 rounded px-1 py-0.5 text-sm outline-none hover:bg-bg-hover focus:bg-bg-hover" />
                {r.is_default ? <Badge>Predeterminada</Badge> : <button className="text-xs text-link hover:underline" onClick={() => patch.mutate({ r, is_default: true })}>Hacer predeterminada</button>}
                <Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${r.name}`} onClick={() => actions.askDelete(r)}><Trash2 size={14} /></Button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2"><Input placeholder="Nueva resolución" value={name} onChange={(e) => setName(e.target.value)} /><Button disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>Agregar</Button></div>
        </>
      )}
      {actions.dialog}
    </div>
  );
}

function LinkTypes() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["link-types"], queryFn: () => unwrap(api.GET("/api/v1/link-types")) });
  const [f, setF] = useState({ name: "", outward: "", inward: "" });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/link-types", { body: f })),
    onSuccess: () => { setF({ name: "", outward: "", inward: "" }); qc.invalidateQueries({ queryKey: ["link-types"] }); qc.invalidateQueries({ queryKey: ["project-meta"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/link-types", "link-types", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/link-types", queryKey: "link-types", related: ["project-meta"] });
  // Planning dependency flag (plans draw these links as arrows and flag date conflicts)
  const setDependency = useMutation({
    mutationFn: (l) => unwrap(api.PATCH("/api/v1/link-types/{lid}", { params: { path: { lid: l.id } }, body: { name: l.name, outward: l.outward, inward: l.inward, is_dependency: !l.is_dependency } })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["link-types"] }); qc.invalidateQueries({ queryKey: ["plan-data"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  // Link type used when cloning an issue (only one at a time)
  const setClone = useMutation({
    mutationFn: (l) => unwrap(api.PATCH("/api/v1/link-types/{lid}", { params: { path: { lid: l.id } }, body: { name: l.name, outward: l.outward, inward: l.inward, is_clone: !l.is_clone } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["link-types"] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="max-w-[720px]">
      <CatalogTabs value={view} onChange={setView} className="mb-3" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} render={(l) => <span><b>{l.name}</b> <span className="text-fg-subtle">({l.outward} / {l.inward})</span></span>} empty="No hay tipos de vínculo eliminados." />
      ) : (
        <>
          <table className="w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Nombre</th><th className="py-2">Saliente</th><th className="py-2">Entrante</th><th className="py-2" title="En los planes, el origen debe terminar antes de que empiece el destino">Dependencia</th><th className="py-2" title="Vínculo que se crea entre la copia y la original al clonar">Al clonar</th><th className="w-10" /></tr></thead>
            <tbody>{list.data?.map((l) => (
              <tr key={l.id} className="border-b border-line">
                <td className="py-2 font-medium">{l.name}</td><td className="py-2">{l.outward}</td><td className="py-2">{l.inward}</td>
                <td className="py-2"><Toggle checked={!!l.is_dependency} label={`${l.name}: dependencia en planes`} onChange={() => setDependency.mutate(l)} /></td>
                <td className="py-2"><Toggle checked={!!l.is_clone} label={`${l.name}: vínculo al clonar`} onChange={() => setClone.mutate(l)} /></td>
                <td className="py-2"><Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${l.name}`} onClick={() => actions.askDelete(l)}><Trash2 size={14} /></Button></td>
              </tr>
            ))}</tbody>
          </table>
          <div className="mt-3 flex gap-2">
            <Input placeholder="Nombre" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <Input placeholder="ej. causa" value={f.outward} onChange={(e) => setF({ ...f, outward: e.target.value })} />
            <Input placeholder="ej. es causada por" value={f.inward} onChange={(e) => setF({ ...f, inward: e.target.value })} />
            <Button disabled={!f.name || !f.outward || !f.inward} onClick={() => create.mutate()}>Agregar</Button>
          </div>
        </>
      )}
      {actions.dialog}
    </div>
  );
}

function ProjectCategories() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["project-categories"], queryFn: () => unwrap(api.GET("/api/v1/project-categories")) });
  const [f, setF] = useState({ name: "", description: "" });
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/project-categories", "project-categories", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/project-categories", queryKey: "project-categories", related: ["projects"],
                                      softBody: "Deja de ofrecerse al configurar proyectos; los que ya la tienen la conservan." });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["project-categories"] }); qc.invalidateQueries({ queryKey: ["projects"] }); };
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/project-categories", { body: f })),
    onSuccess: () => { setF({ name: "", description: "" }); refresh(); }, onError: (e) => toast.error(errorMessage(e)),
  });
  const patch = useMutation({
    mutationFn: ({ c, ...changes }) => unwrap(api.PATCH(`/api/v1/project-categories/${c.id}`, { body: { name: c.name, description: c.description, ...changes } })),
    onSuccess: refresh, onError: (e) => toast.error(errorMessage(e)),
  });
  const inline = "w-full rounded px-1 py-0.5 outline-none hover:bg-bg-hover focus:bg-bg-hover";
  return (
    <div className="max-w-[720px]">
      <p className="mb-3 text-sm text-fg-subtle">Agrupan proyectos en el listado (ej. Producto, Operaciones, Clientes). Se asignan en la configuración de cada proyecto.</p>
      <CatalogTabs value={view} onChange={setView} className="mb-3" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} empty="No hay categorías eliminadas." />
      ) : (
        <>
          <table className="w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Nombre</th><th className="py-2">Descripción</th><th className="py-2 text-right">Proyectos</th><th className="w-10" /></tr></thead>
            <tbody>{list.data?.map((c) => (
              <tr key={c.id} className="border-b border-line">
                <td className="py-1.5"><input aria-label="Nombre" defaultValue={c.name} className={cn(inline, "font-medium")} onBlur={(e) => e.target.value.trim() && e.target.value !== c.name && patch.mutate({ c, name: e.target.value.trim() })} /></td>
                <td className="py-1.5"><input aria-label="Descripción" defaultValue={c.description} className={inline} onBlur={(e) => e.target.value !== c.description && patch.mutate({ c, description: e.target.value })} /></td>
                <td className="py-1.5 text-right">{c.project_count}</td>
                <td className="py-1.5"><Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${c.name}`} onClick={() => actions.askDelete(c)}><Trash2 size={14} /></Button></td>
              </tr>
            ))}</tbody>
          </table>
          {list.data && !list.data.length && <p className="py-3 text-sm text-fg-subtlest">Todavía no hay categorías.</p>}
          <div className="mt-3 flex gap-2">
            <Input placeholder="Nombre" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <Input placeholder="Descripción (opcional)" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
            <Button disabled={!f.name.trim()} loading={create.isPending} onClick={() => create.mutate()}>Agregar</Button>
          </div>
        </>
      )}
      {actions.dialog}
    </div>
  );
}

/* ------------------------------------------------------------------ custom fields */


function CustomFields() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["custom-fields"], queryFn: () => unwrap(api.GET("/api/v1/custom-fields")) });
  const projects = useQuery({ queryKey: ["projects", {}], queryFn: () => unwrap(api.GET("/api/v1/projects", { params: { query: {} } })) });
  const types = useQuery({ queryKey: ["issue-types"], queryFn: () => unwrap(api.GET("/api/v1/issue-types")) });
  const kinds = useChoices("custom_field_kinds");
  const [edit, setEdit] = useState(null);
  const [view, setView] = useState("active");
  const deleted = useDeletedList("/api/v1/custom-fields", "custom-fields", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/custom-fields", queryKey: "custom-fields", related: ["project-meta"] });
  const save = useMutation({
    mutationFn: () => edit.id
      ? unwrap(api.PUT("/api/v1/custom-fields/{cid}", { params: { path: { cid: edit.id } }, body: cfBody(edit) }))
      : unwrap(api.POST("/api/v1/custom-fields", { body: cfBody(edit) })),
    onSuccess: () => {
      setEdit(null);
      for (const k of ["custom-fields", "project-meta", "field-rules", "fields-catalog", "field-configurations", "screens"]) qc.invalidateQueries({ queryKey: [k] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const hasOptions = !!edit && !!kinds.find((k) => k.value === edit.kind)?.has_options;
  const opts = edit?.options ?? [];
  // Options removed earlier stay stored as `deleted` (issues keep showing them); they can be
  // brought back by sending them again without the flag.
  const setOpt = (id, patch) => setEdit({ ...edit, options: opts.map((x) => (x.id === id ? { ...x, ...patch } : x)) });
  return (
    <div className="max-w-[860px]">
      <div className="flex items-end justify-between gap-3">
        <CatalogTabs value={view} onChange={setView} className="flex-1" />
        {view === "active" && <Button variant="primary" onClick={() => setEdit({ name: "", kind: "text", options: [], project_ids: [], issue_type_ids: [], required: false, description: "" })}><Plus size={16} />Crear campo</Button>}
      </div>
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} render={(c) => <span><b>{c.name}</b> <span className="text-fg-subtle">· {choiceLabel(kinds, c.kind)}</span></span>} empty="No hay campos eliminados." />
      ) : list.data?.length ? (
        <table className="mt-3 w-full text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Campo</th><th className="py-2">Tipo</th><th className="py-2">Proyectos</th><th className="py-2" title="En la configuración de campos predeterminada">Obligatorio (predeterminada)</th><th className="w-10" /></tr></thead>
          <tbody>{list.data.map((c) => (
            <tr key={c.id} className="border-b border-line">
              <td className="py-2"><button className="font-medium text-link hover:underline" onClick={() => setEdit({ ...c, options: c.options })}>{c.name}</button><div className="text-xs text-fg-subtle">JQL: cf[{c.id}]</div></td>
              <td className="py-2">{choiceLabel(kinds, c.kind)}</td>
              <td className="py-2 text-fg-subtle">{c.project_ids.length ? projects.data?.filter((p) => c.project_ids.includes(p.id)).map((p) => p.key).join(", ") : "Todos"}</td>
              <td className="py-2">{c.required ? "Sí" : "No"}</td>
              <td className="py-2"><Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${c.name}`} onClick={() => actions.askDelete(c)}><Trash2 size={14} /></Button></td>
            </tr>
          ))}</tbody>
        </table>
      ) : <EmptyState title="Sin campos personalizados" body="Agrega campos propios del equipo (ej. Cliente, Entorno, Sprint goal…)." />}
      {edit && (
        <Modal open onOpenChange={(o) => !o && setEdit(null)} title={edit.id ? "Editar campo" : "Crear campo"} width={560}
               footer={<><Button variant="subtle" onClick={() => setEdit(null)}>Cancelar</Button><Button variant="primary" disabled={!edit.name} loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button></>}>
          <div className="space-y-4">
            <Field label="Nombre" required><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Tipo" hint={edit.id ? "El tipo no se puede cambiar." : undefined}>
              <Picker value={edit.kind} width={300} onSelect={(k) => !edit.id && setEdit({ ...edit, kind: k })} options={kinds}
                      trigger={<button className={sel} disabled={!!edit.id}>{choiceLabel(kinds, edit.kind)}</button>} />
            </Field>
            <Field label="Descripción"><Input value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            {hasOptions && (
              <Field label="Opciones">
                <div className="space-y-1">
                  {opts.filter((o) => !o.deleted).map((o) => (
                    <div key={o.id} className="flex gap-2">
                      <Input value={o.value} onChange={(e) => setOpt(o.id, { value: e.target.value })} />
                      <Button variant="subtle" size="icon" aria-label="Quitar opción"
                              onClick={() => (o.isNew ? setEdit({ ...edit, options: opts.filter((x) => x.id !== o.id) }) : setOpt(o.id, { deleted: true }))}><X size={14} /></Button>
                    </div>
                  ))}
                  <Button size="sm" onClick={() => setEdit({ ...edit, options: [...opts, { id: `o${Date.now()}`, value: "", isNew: true }] })}><Plus size={14} />Agregar opción</Button>
                  {opts.some((o) => o.deleted) && (
                    <div className="pt-2 text-xs text-fg-subtle">
                      <div className="mb-1 font-semibold">Opciones eliminadas (las incidencias que las usan las conservan)</div>
                      <div className="flex flex-wrap gap-2">{opts.filter((o) => o.deleted).map((o) => (
                        <span key={o.id} className="flex items-center gap-1 rounded-[3px] border border-line px-1.5 py-0.5">
                          <span className="line-through">{o.value}</span>
                          <button className="text-link hover:underline" onClick={() => setOpt(o.id, { deleted: false })}>Restaurar</button>
                        </span>
                      ))}</div>
                    </div>
                  )}
                </div>
              </Field>
            )}
            <Field label="Proyectos" hint="Vacío = todos los proyectos">
              <Picker multiple value={edit.project_ids ?? []} width={380} options={(projects.data ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.key})` }))}
                      onSelect={(id) => setEdit({ ...edit, project_ids: (edit.project_ids ?? []).includes(id) ? (edit.project_ids ?? []).filter((x) => x !== id) : [...(edit.project_ids ?? []), id] })}
                      trigger={<button className={sel}>{edit.project_ids?.length ? projects.data?.filter((p) => edit.project_ids.includes(p.id)).map((p) => p.key).join(", ") : "Todos"}</button>} />
            </Field>
            <Field label="Tipos de incidencia" hint="Vacío = todos los tipos">
              <Picker multiple value={edit.issue_type_ids ?? []} width={380} options={(types.data ?? []).map((t) => ({ value: t.id, label: t.name, icon: <IssueTypeIcon type={t} /> }))}
                      onSelect={(id) => setEdit({ ...edit, issue_type_ids: (edit.issue_type_ids ?? []).includes(id) ? (edit.issue_type_ids ?? []).filter((x) => x !== id) : [...(edit.issue_type_ids ?? []), id] })}
                      trigger={<button className={sel}>{edit.issue_type_ids?.length ? types.data?.filter((t) => edit.issue_type_ids.includes(t.id)).map((t) => t.name).join(", ") : "Todos"}</button>} />
            </Field>
            <div>
              <Checkbox checked={!!edit.required} onChange={(v) => setEdit({ ...edit, required: v })} label="Obligatorio en la configuración de campos predeterminada" />
              <p className="ml-6 mt-0.5 text-xs text-fg-subtle">Para hacerlo obligatorio u ocultarlo solo en algunos tipos, usa <Link href="/settings/field-configurations" className="text-link hover:underline">Configuraciones de campos</Link>. Los campos nuevos se añaden al final de la pantalla predeterminada.</p>
            </div>
          </div>
        </Modal>
      )}
      {actions.dialog}
    </div>
  );
}

// Deleted options are omitted (the backend keeps them as deleted); restored ones are sent
// again without the flag.
function cfBody(edit) {
  return { ...edit, options: (edit.options ?? []).filter((o) => !o.deleted).map(({ deleted: _d, isNew: _n, ...o }) => o) };
}

/* ------------------------------------------------------------------ shell */

export function AdminSettings({ section, workflowId }) {
  const { me } = useApp();
  if (!me.is_admin) return <EmptyState title="Sin permiso" body="Solo los administradores pueden acceder." />;
  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-bg-subtle p-3 md:block">
        <div className="px-2 pb-2 pt-3 text-[11px] font-bold uppercase text-fg-subtlest">Administración</div>
        {ADMIN_SECTIONS.map(([v, l]) => (
          <Link key={v} href={`/settings/${v}`} className={cn("mb-0.5 flex h-9 items-center rounded-[3px] px-2 text-sm text-fg-subtle hover:bg-bg-hover", section === v && "bg-bg-selected font-medium text-brand")}>{l}</Link>
        ))}
        <a href="/admin/" className="mt-4 flex h-9 items-center rounded-[3px] px-2 text-sm text-fg-subtle hover:bg-bg-hover">Panel técnico (Django) ↗</a>
      </aside>
      <main className="flex-1 overflow-y-auto px-8 py-6">
        <h1 className="mb-6 text-2xl font-medium">{ADMIN_SECTIONS.find(([v]) => v === section)?.[1]}</h1>
        {section === "users" && <Users />}
        {section === "roles" && <RolesMatrix />}
        {section === "provisioning" && <Provisioning />}
        {section === "workflows" && (workflowId ? <WorkflowEditor id={workflowId} /> : <Workflows />)}
        {section === "statuses" && <Statuses />}
        {section === "issue-types" && <IssueTypes />}
        {section === "priorities" && <Priorities />}
        {section === "resolutions" && <Resolutions />}
        {section === "fields" && <CustomFields />}
        {section === "field-configurations" && <FieldConfigurations />}
        {section === "field-configuration-schemes" && <FieldConfigurationSchemes />}
        {section === "screens" && <Screens />}
        {section === "screen-schemes" && <ScreenSchemes />}
        {section === "issue-type-screen-schemes" && <IssueTypeScreenSchemes />}
        {section === "links" && <LinkTypes />}
        {section === "project-categories" && <ProjectCategories />}
        {section === "automation" && <AutomationRules />}
        {section === "audit" && <AuditLog />}
        {section === "import" && <JiraImport />}
      </main>
    </div>
  );
}
