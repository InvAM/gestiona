"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { AutomationRules } from "@/components/automation/rules";
import { BoardSettings } from "@/components/board/board-settings";
import { ProjectForms } from "@/components/forms/forms";
import { ArchivedIssues } from "@/components/settings/archived-issues";
import { ProjectFields } from "@/components/settings/project-fields";
import { IssueTypeIcon, PROJECT_COLORS, PROJECT_ICONS, ProjectAvatar } from "@/components/icons";
import { UserPicker } from "@/components/issue/pickers";
import { useApp } from "@/components/shell/app-context";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, Checkbox, Confirm, EmptyState, Field, Input, Lozenge, Textarea } from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, qk, useMembers, useMeta, useProjectMeta, useUsers } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

const TABS = [
  ["details", "Detalles"], ["members", "Personas"], ["issue-types", "Tipos de incidencia"], ["fields", "Campos"],
  ["board", "Tableros"], ["workflow", "Flujo de trabajo"], ["automation", "Automatización"], ["forms", "Formularios"], ["archived", "Incidencias archivadas"],
];

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

function Details({ meta }) {
  const appMeta = useMeta();
  const qc = useQueryClient();
  const router = useRouter();
  const { me } = useApp();
  const p = meta.project;
  const [name, setName] = useState(p.name);
  const [description, setDescription] = useState(p.description);
  const [avatar, setAvatar] = useState(p.avatar);
  const [color, setColor] = useState(p.color);
  const [lead, setLead] = useState(p.lead.id);
  const [access, setAccess] = useState(p.access);
  const [defaultAssignee, setDefaultAssignee] = useState(p.default_assignee);
  const standardTypes = meta.issue_types.filter((t) => t.level === 0);
  const [defaultType, setDefaultType] = useState(p.default_issue_type_id ?? meta.default_issue_type_id ?? null);
  const [category, setCategory] = useState(p.category?.id ?? 0);
  const categories = useQuery({ queryKey: ["project-categories"], queryFn: () => unwrap(api.GET("/api/v1/project-categories")) });
  // A deleted category stays on the project (and is shown) but is no longer offered.
  const categoryOptions = [{ value: 0, label: "Sin categoría" },
    ...(categories.data ?? []).map((c) => ({ value: c.id, label: c.name, description: c.description })),
    ...(p.category && !(categories.data ?? []).some((c) => c.id === p.category.id) ? [{ value: p.category.id, label: p.category.name, description: "Eliminada" }] : [])];
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const users = useUsers("", p.key);
  const leadUser = users.data?.find((u) => u.id === lead) ?? p.lead;
  const save = useMutation({
    mutationFn: (body) => unwrap(api.PATCH("/api/v1/projects/{key}", { params: { path: { key: p.key } }, body })),
    onSuccess: () => { toast.success("Cambios guardados"); qc.invalidateQueries({ queryKey: qk.meta(p.key) }); qc.invalidateQueries({ queryKey: ["projects"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/projects/{key}", { params: { path: { key: p.key } } })),
    onSuccess: () => { toast.success("Proyecto eliminado"); qc.invalidateQueries({ queryKey: ["projects"] }); router.push("/projects"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="max-w-[480px] space-y-5">
      <div className="flex items-center gap-4">
        <ProjectAvatar project={{ avatar, color }} size={64} />
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1">{PROJECT_ICONS.map((i) => (
            <button key={i} onClick={() => setAvatar(i)} className={cn("rounded p-0.5", avatar === i && "ring-2 ring-brand")}><ProjectAvatar project={{ avatar: i, color }} size={22} /></button>
          ))}</div>
          <div className="flex gap-1">{PROJECT_COLORS.map((c) => (
            <button key={c} aria-label={`Color ${c}`} onClick={() => setColor(c)} style={{ background: c }} className={cn("h-5 w-5 rounded-full", color === c && "ring-2 ring-offset-2 ring-brand")} />
          ))}</div>
        </div>
      </div>
      <Field label="Nombre" required><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Clave" hint="La clave no se puede cambiar."><Input value={p.key} disabled className="w-40" /></Field>
      <Field label="Descripción"><Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Responsable del proyecto">
        <UserPicker projectKey={p.key} meId={me.id} value={lead} allowNone={false} onSelect={(id) => id && setLead(id)}
                    trigger={<button className={sel}><Avatar user={leadUser} size="xs" />{leadUser.name}</button>} />
      </Field>
      <Field label="Acceso">
        <Picker value={access} width={420} onSelect={setAccess} options={appMeta.data?.project_access ?? []}
                trigger={<button className={sel}>{choiceLabel(appMeta.data?.project_access, access)}</button>} />
      </Field>
      <Field label="Responsable por defecto">
        <Picker value={defaultAssignee} width={420} onSelect={setDefaultAssignee}
                options={appMeta.data?.project_default_assignee ?? []}
                trigger={<button className={sel}>{choiceLabel(appMeta.data?.project_default_assignee, defaultAssignee)}</button>} />
      </Field>
      <Field label="Categoría">
        <Picker value={category} width={420} onSelect={setCategory} options={categoryOptions}
                trigger={<button className={sel}>{categoryOptions.find((o) => o.value === category)?.label ?? "Sin categoría"}</button>} />
      </Field>
      <Field label="Tipo de incidencia por defecto" hint="Se preselecciona al crear incidencias en el tablero, el backlog y el diálogo de creación.">
        <Picker value={defaultType} width={420} onSelect={setDefaultType}
                options={standardTypes.map((t) => ({ value: t.id, label: t.name, icon: <IssueTypeIcon type={t} /> }))}
                trigger={<button className={sel}>{standardTypes.find((t) => t.id === defaultType)?.name ?? "El primero disponible"}</button>} />
      </Field>
      <Button variant="primary" loading={save.isPending}
              onClick={() => save.mutate({ name, description, avatar, color, lead_id: lead, access, default_assignee: defaultAssignee, default_issue_type_id: defaultType, category_id: category || null })}>Guardar</Button>
      <div className="border-t border-line pt-5">
        <h3 className="font-semibold">Zona de riesgo</h3>
        <div className="mt-3 flex gap-2">
          <Button onClick={() => setConfirmArchive(true)}>{p.is_archived ? "Restaurar proyecto" : "Archivar proyecto"}</Button>
          {me.is_superuser && <Button variant="danger" onClick={() => setConfirmDelete(true)}>Eliminar proyecto</Button>}
        </div>
      </div>
      <Confirm open={confirmArchive} onOpenChange={setConfirmArchive} title={p.is_archived ? "¿Restaurar proyecto?" : "¿Archivar proyecto?"}
               body={p.is_archived ? "El proyecto volverá a estar activo." : "El proyecto quedará en solo lectura y oculto de la lista principal. Puedes restaurarlo después."}
               onConfirm={() => { save.mutate({ archived: !p.is_archived }); setConfirmArchive(false); }} />
      <Confirm open={confirmDelete} onOpenChange={setConfirmDelete} danger confirmLabel="Eliminar definitivamente" loading={del.isPending}
               title={`¿Eliminar ${p.name}?`}
               body={<>Se eliminarán <b>todas</b> las incidencias, comentarios, adjuntos, sprints y tableros del proyecto. <b>No se puede deshacer.</b> Considera archivarlo en su lugar.</>}
               onConfirm={() => del.mutate()} />
    </div>
  );
}

function Members({ meta }) {
  const qc = useQueryClient();
  const { me } = useApp();
  const key = meta.project.key;
  const members = useMembers(key);
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => unwrap(api.GET("/api/v1/roles")) });
  const [removing, setRemoving] = useState(null);
  const setRole = useMutation({
    mutationFn: ({ userId, roleId }) =>
      unwrap(api.PUT("/api/v1/projects/{key}/members/{user_id}", { params: { path: { key, user_id: userId } }, body: { role_id: roleId } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.members(key) }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (userId) => unwrap(api.DELETE("/api/v1/projects/{key}/members/{user_id}", { params: { path: { key, user_id: userId } } })),
    onSuccess: () => { setRemoving(null); qc.invalidateQueries({ queryKey: qk.members(key) }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const existing = new Set(members.data?.map((m) => m.user.id));
  return (
    <div className="max-w-[860px]">
      <div className="flex items-center justify-between">
        <p className="text-sm text-fg-subtle">Los roles definen qué puede hacer cada persona en este proyecto.</p>
        <UserPicker meId={me.id} allowNone={false} align="end" onSelect={(id) => id && !existing.has(id) && setRole.mutate({ userId: id, roleId: null })}
                    trigger={<Button variant="primary"><Plus size={16} />Agregar personas</Button>} />
      </div>
      {members.isPending ? <PageSpinner /> : (
        <table className="mt-4 w-full text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Nombre</th><th className="py-2">Email</th><th className="w-56 py-2">Rol</th><th className="w-10" /></tr></thead>
          <tbody>
            {members.data?.map((m) => (
              <tr key={m.user.id} className="border-b border-line">
                <td className="py-2"><span className="flex items-center gap-2"><Avatar user={m.user} size="sm" />{m.user.name}
                  {m.user.id === meta.project.lead.id && <Lozenge category="in_progress">Responsable</Lozenge>}</span></td>
                <td className="py-2 text-fg-subtle">{m.user.email}</td>
                <td className="py-2">
                  <Picker value={m.role.id} width={300} onSelect={(roleId) => setRole.mutate({ userId: m.user.id, roleId })}
                          options={(roles.data ?? []).map((r) => ({ value: r.id, label: r.name, description: r.description }))}
                          trigger={<button className={sel}>{m.role.name}</button>} />
                </td>
                <td className="py-2">{m.user.id !== meta.project.lead.id && (
                  <Button variant="subtle" size="icon-sm" aria-label="Quitar" onClick={() => setRemoving(m)}><X size={14} /></Button>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Confirm open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`¿Quitar a ${removing?.user.name}?`} confirmLabel="Quitar" danger
               body="Perderá los permisos de su rol. Según el acceso del proyecto podría seguir viéndolo." loading={remove.isPending}
               onConfirm={() => removing && remove.mutate(removing.user.id)} />
    </div>
  );
}

function IssueTypes({ meta }) {
  const qc = useQueryClient();
  const all = useQuery({ queryKey: ["issue-types"], queryFn: () => unwrap(api.GET("/api/v1/issue-types")) });
  const [ids, setIds] = useState(meta.issue_types.map((t) => t.id));
  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/projects/{key}", { params: { path: { key: meta.project.key } }, body: { issue_type_ids: ids } })),
    onSuccess: () => { toast.success("Tipos actualizados"); qc.invalidateQueries({ queryKey: qk.meta(meta.project.key) }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="max-w-[560px] space-y-2">
      <p className="text-sm text-fg-subtle">Elige qué tipos de incidencia se pueden crear en este proyecto.</p>
      {all.data?.map((t) => (
        <div key={t.id} className="flex items-center gap-3 rounded-[3px] border border-line px-3 py-2">
          <Checkbox checked={ids.includes(t.id)} onChange={(c) => setIds(c ? [...ids, t.id] : ids.filter((x) => x !== t.id))} />
          <IssueTypeIcon type={t} size={20} />
          <div><div className="text-sm font-medium">{t.name}</div><div className="text-xs text-fg-subtle">{t.description}</div></div>
        </div>
      ))}
      <Button variant="primary" className="mt-2" loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button>
    </div>
  );
}

function WorkflowSettings({ meta }) {
  const qc = useQueryClient();
  const { me } = useApp();
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: () => unwrap(api.GET("/api/v1/workflows")) });
  const current = workflows.data?.find((w) => w.project_keys.includes(meta.project.key));
  const [target, setTarget] = useState(null);
  const [map, setMap] = useState({});
  const [needMap, setNeedMap] = useState(null);
  const change = useMutation({
    mutationFn: () => unwrap(api.PUT("/api/v1/projects/{key}/workflow", { params: { path: { key: meta.project.key } }, body: { workflow_id: target, status_map: needMap ? map : null } })),
    onSuccess: () => { toast.success("Flujo actualizado"); setTarget(null); setNeedMap(null); qc.invalidateQueries(); },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "status_map_required") setNeedMap(e.details?.status_ids ?? []);
      else toast.error(errorMessage(e));
    },
  });
  const targetWf = workflows.data?.find((w) => w.id === target);
  if (!workflows.data) return <PageSpinner />;
  return (
    <div className="max-w-[720px] space-y-6">
      <div>
        <h2 className="text-lg font-medium">Flujo actual: {current?.name}</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {current?.statuses.map((s, i) => (
            <span key={s.status.id} className="flex items-center gap-2"><Lozenge category={s.status.category}>{s.status.name}</Lozenge>{i < current.statuses.length - 1 && <span className="text-fg-subtlest">→</span>}</span>
          ))}
        </div>
        {me.is_admin && current && <Link href={`/settings/workflows/${current.id}`} className="mt-3 inline-block text-sm text-link hover:underline">Editar este flujo (afecta a {current.project_keys.length} proyecto/s)</Link>}
      </div>
      <div className="border-t border-line pt-5">
        <h3 className="font-semibold">Cambiar de flujo</h3>
        <div className="mt-2 flex items-center gap-2">
          <Picker value={target} width={320} onSelect={(v) => { setTarget(v); setNeedMap(null); }}
                  options={workflows.data.filter((w) => w.id !== current?.id).map((w) => ({ value: w.id, label: w.name, description: w.statuses.map((s) => s.status.name).join(" → ") }))}
                  trigger={<button className={cn(sel, "w-80")}>{targetWf?.name ?? "Selecciona un flujo"}</button>} />
          <Button variant="primary" disabled={!target || (!!needMap && needMap.some((s) => !map[String(s)]))} loading={change.isPending} onClick={() => change.mutate()}>Aplicar</Button>
        </div>
        {needMap && targetWf && (
          <div className="mt-4 space-y-2 rounded-[3px] bg-warning-subtle p-3">
            <p className="text-sm">Hay incidencias en estados que no existen en el nuevo flujo. Elige a dónde moverlas:</p>
            {needMap.map((sid) => {
              const s = meta.statuses.find((x) => x.id === sid);
              return (
                <div key={sid} className="flex items-center gap-3 text-sm">
                  <Lozenge category={s?.category ?? "todo"}>{s?.name ?? sid}</Lozenge>→
                  <Picker value={map[String(sid)]} width={240} onSelect={(v) => setMap({ ...map, [String(sid)]: v })}
                          options={targetWf.statuses.map((x) => ({ value: x.status.id, label: x.status.name }))}
                          trigger={<button className={cn(sel, "w-56")}>{targetWf.statuses.find((x) => x.status.id === map[String(sid)])?.status.name ?? "Elegir estado"}</button>} />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function ProjectSettings({ projectKey, tab }) {
  const meta = useProjectMeta(projectKey);
  if (meta.isPending) return <PageSpinner />;
  if (!meta.data) return null;
  if (!meta.data.permissions.includes("administer")) return <EmptyState title="Sin permiso" body="Solo los administradores del proyecto pueden ver la configuración." />;
  return (
    <div className="flex-1 overflow-y-auto px-6 py-5">
      <div className="text-sm text-fg-subtle">{meta.data.project.name} / Configuración del proyecto</div>
      <h1 className="mt-1 text-2xl font-medium">{TABS.find(([v]) => v === tab)?.[1]}</h1>
      <nav className="mt-4 flex gap-1 border-b-2 border-line">
        {TABS.map(([v, l]) => (
          <Link key={v} href={`/projects/${projectKey}/settings${v === "details" ? "" : `/${v}`}`}
                className={cn("-mb-0.5 border-b-2 px-2 pb-1.5 pt-1 text-sm font-medium", tab === v ? "border-brand text-brand" : "border-transparent text-fg-subtle hover:text-fg")}>{l}</Link>
        ))}
      </nav>
      <div className="mt-6">
        {tab === "details" && <Details meta={meta.data} />}
        {tab === "members" && <Members meta={meta.data} />}
        {tab === "issue-types" && <IssueTypes meta={meta.data} />}
        {tab === "fields" && <ProjectFields meta={meta.data} />}
        {tab === "board" && <BoardSettings meta={meta.data} />}
        {tab === "workflow" && <WorkflowSettings meta={meta.data} />}
        {tab === "automation" && <AutomationRules projectKey={meta.data.project.key} />}
        {tab === "forms" && <ProjectForms meta={meta.data} />}
        {tab === "archived" && <ArchivedIssues projectKey={meta.data.project.key} />}
      </div>
    </div>
  );
}
