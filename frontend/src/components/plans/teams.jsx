"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MoreHorizontal, Pencil, Plus, Trash2, Users, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { UserPicker } from "@/components/issue/pickers";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";
import { useApp } from "@/components/shell/app-context";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, AvatarStack, EmptyState, Field, Input, Menu, MenuContent, MenuItem, MenuTrigger, Modal, Textarea } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { useTeams } from "./api";

const num = (v) => (v === null || v === undefined ? "—" : String(v));

export function TeamsPage() {
  const { me } = useApp();
  const meta = useMeta();
  const [q, setQ] = useState("");
  const [view, setView] = useState("active");
  const [editing, setEditing] = useState(null); // null | "new" | team
  const teams = useTeams(q);
  const deleted = useDeletedList("/api/v1/teams", "teams", view === "deleted");
  const actions = useCatalogActions({
    path: "/api/v1/teams", queryKey: "teams", related: ["plan", "plan-data", "plan-capacity"],
    softBody: "Deja de poder elegirse en incidencias y planes. Las incidencias que ya lo tienen lo conservan.",
  });
  const unit = (v) => meta.data?.plans.estimations.find((e) => e.value === v)?.label ?? v;
  return (
    <div className="mx-auto w-full max-w-[1100px] px-6 py-6">
      <Link href="/plans" className="inline-flex items-center gap-1 text-sm text-fg-subtle hover:underline"><ArrowLeft size={14} />Planes</Link>
      <div className="mt-2 flex items-center gap-3">
        <h1 className="text-2xl font-medium">Equipos</h1>
        <Button variant="primary" className="ml-auto" onClick={() => setEditing("new")}><Plus size={16} />Crear equipo</Button>
      </div>
      <p className="mt-1 text-sm text-fg-subtle">Los equipos se comparten entre planes. Cada incidencia puede pertenecer a un equipo; su capacidad por iteración se compara con el trabajo asignado.</p>
      <CatalogTabs value={view} onChange={setView} className="mt-4" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} allowPurge={me.is_admin} empty="No hay equipos eliminados." />
      ) : <>
        <Input className="mt-4 w-72" placeholder="Buscar equipos" value={q} onChange={(e) => setQ(e.target.value)} />
        {teams.isPending ? <PageSpinner /> : !teams.data?.length ? (
          <EmptyState icon={<Users size={40} />} title={q ? "Sin resultados" : "Todavía no hay equipos"}
                      body="Crea equipos para repartir el trabajo de los planes y comparar lo asignado con su capacidad."
                      action={!q && <Button onClick={() => setEditing("new")}>Crear equipo</Button>} />
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
                <th className="py-2">Nombre</th><th>Miembros</th>
                <th className="text-right">{unit("story_points")}</th><th className="text-right">{unit("hours")}</th>
                <th className="text-right">Incidencias</th><th className="text-right">Planes</th><th className="w-10" />
              </tr></thead>
              <tbody>{teams.data.map((t) => (
                <tr key={t.id} className="border-b border-line hover:bg-bg-hover">
                  <td className="py-2"><div className="font-medium">{t.name}</div>{t.description && <div className="text-xs text-fg-subtle">{t.description}</div>}</td>
                  <td className="py-2">{t.members.length ? <AvatarStack users={t.members} max={5} /> : <span className="text-fg-subtlest">Sin miembros</span>}</td>
                  <td className="py-2 text-right tabular-nums">{num(t.capacity_points)}</td>
                  <td className="py-2 text-right tabular-nums">{num(t.capacity_hours)}</td>
                  <td className="py-2 text-right tabular-nums">{t.issue_count}</td>
                  <td className="py-2 text-right tabular-nums">{t.plan_count}</td>
                  <td className="py-2 text-right">
                    {t.can_edit && (
                      <Menu>
                        <MenuTrigger asChild><Button variant="subtle" size="icon-sm" aria-label={`Acciones de ${t.name}`}><MoreHorizontal size={16} /></Button></MenuTrigger>
                        <MenuContent align="end">
                          <MenuItem onSelect={() => setEditing(t)}><Pencil size={14} />Editar</MenuItem>
                          <MenuItem danger onSelect={() => actions.askDelete(t)}><Trash2 size={14} />Eliminar</MenuItem>
                        </MenuContent>
                      </Menu>
                    )}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </>}
      {actions.dialog}
      <TeamDialog team={editing === "new" ? null : editing} open={!!editing} onOpenChange={(o) => !o && setEditing(null)} />
    </div>
  );
}

export function TeamDialog({ team, open, onOpenChange, onSaved }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={team ? "Editar equipo" : "Crear equipo"} width={520}>
      {open && <TeamForm team={team} onClose={() => onOpenChange(false)} onSaved={onSaved} />}
    </Modal>
  );
}

function TeamForm({ team, onClose, onSaved }) {
  const qc = useQueryClient();
  const meta = useMeta();
  const [name, setName] = useState(team?.name ?? "");
  const [description, setDescription] = useState(team?.description ?? "");
  const [members, setMembers] = useState(team?.members ?? []);
  const [points, setPoints] = useState(team?.capacity_points ?? "");
  const [hours, setHours] = useState(team?.capacity_hours ?? "");
  const [error, setError] = useState(null);
  const unit = (v) => meta.data?.plans.estimations.find((e) => e.value === v)?.label ?? v;
  const toNum = (v) => (v === "" || v === null ? null : Number(v));
  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, member_ids: members.map((m) => m.id), capacity_points: toNum(points), capacity_hours: toNum(hours) };
      return team
        ? unwrap(api.PATCH("/api/v1/teams/{tid}", { params: { path: { tid: team.id } }, body }))
        : unwrap(api.POST("/api/v1/teams", { body }));
    },
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["teams"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["plan-data"] });
      qc.invalidateQueries({ queryKey: ["plan-capacity"] });
      toast.success(team ? "Equipo guardado" : `Equipo «${t.name}» creado`);
      onSaved?.(t);
      onClose();
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const toggle = (u) => {
    if (!u) return;
    setMembers((ms) => (ms.some((m) => m.id === u.id) ? ms.filter((m) => m.id !== u.id) : [...ms, u]));
  };
  return (
    <form className="space-y-4 pb-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label="Nombre" required><Input autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Descripción"><Textarea rows={2} value={description} maxLength={255} onChange={(e) => setDescription(e.target.value)} /></Field>
      <Field label="Miembros">
        <div className="flex flex-wrap items-center gap-1.5">
          {members.map((m) => (
            <span key={m.id} className="inline-flex items-center gap-1 rounded-full bg-bg-sunken py-0.5 pl-0.5 pr-1.5 text-xs">
              <Avatar user={m} size="xs" />{m.name}
              <button type="button" aria-label={`Quitar a ${m.name}`} onClick={() => toggle(m)} className="rounded-full hover:bg-bg-pressed"><X size={12} /></button>
            </span>
          ))}
          <UserPicker allowNone={false} value={members.map((m) => m.id)} multiple onSelect={() => {}} onPickUser={toggle}
                      trigger={<Button size="sm" type="button"><Plus size={14} />Añadir</Button>} />
        </div>
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label={`Capacidad por iteración · ${unit("story_points")}`} hint="Se usa en planes que estiman con puntos">
          <Input type="number" min={0} step="0.5" value={points ?? ""} onChange={(e) => setPoints(e.target.value)} />
        </Field>
        <Field label={`Capacidad por iteración · ${unit("hours")}`} hint="Se usa en planes que estiman en horas">
          <Input type="number" min={0} step="0.5" value={hours ?? ""} onChange={(e) => setHours(e.target.value)} />
        </Field>
      </div>
      {error && <p role="alert" className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="subtle" onClick={onClose}>Cancelar</Button>
        <Button type="submit" variant="primary" disabled={!name.trim()} loading={save.isPending}>Guardar</Button>
      </div>
    </form>
  );
}
