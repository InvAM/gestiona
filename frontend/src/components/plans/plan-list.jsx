"use client";

import { Map as MapIcon, Plus, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ProjectAvatar } from "@/components/icons";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";
import { useApp } from "@/components/shell/app-context";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, EmptyState, Input, Modal } from "@/components/ui/primitives";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { fmtRelative } from "@/lib/utils";
import { usePlans } from "./api";
import { PlanForm } from "./plan-form";

export function PlanList() {
  const router = useRouter();
  const { me } = useApp();
  const meta = useMeta();
  const [q, setQ] = useState("");
  const [view, setView] = useState("active");
  const [creating, setCreating] = useState(false);
  const plans = usePlans(q);
  const deleted = useDeletedList("/api/v1/plans", "plans", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/plans", queryKey: "plans",
                                      softBody: "Las incidencias, equipos y versiones no se tocan." });
  return (
    <div className="mx-auto w-full max-w-[1100px] px-6 py-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-medium">Planes</h1>
        <div className="ml-auto flex gap-2">
          <Button asChild><Link href="/plans/teams"><Users size={16} />Equipos</Link></Button>
          <Button variant="primary" onClick={() => setCreating(true)}><Plus size={16} />Crear plan</Button>
        </div>
      </div>
      <p className="mt-1 text-sm text-fg-subtle">Planifica el trabajo de varios proyectos a la vez: cronograma con dependencias, capacidad de los equipos y versiones entre proyectos.</p>
      <CatalogTabs value={view} onChange={setView} className="mt-4" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} allowPurge={me.is_admin} empty="No hay planes eliminados." />
      ) : <>
        <Input className="mt-4 w-72" placeholder="Buscar planes" value={q} onChange={(e) => setQ(e.target.value)} />
        {plans.isPending ? <PageSpinner /> : !plans.data?.length ? (
          <EmptyState icon={<MapIcon size={40} />} title={q ? "Sin resultados" : "Todavía no hay planes"}
                      body="Un plan reúne incidencias de varios proyectos en un cronograma con dependencias, equipos y capacidad."
                      action={!q && <Button onClick={() => setCreating(true)}>Crear mi primer plan</Button>} />
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
                <th className="py-2">Nombre</th><th>Proyectos</th><th>Propietario</th><th>Acceso</th><th>Actualizado</th>
              </tr></thead>
              <tbody>{plans.data.map((p) => (
                <tr key={p.id} className="border-b border-line hover:bg-bg-hover">
                  <td className="py-2"><Link className="font-medium text-link hover:underline" href={`/plans/${p.id}`}>{p.name}</Link>{p.description && <div className="line-clamp-1 text-xs text-fg-subtle">{p.description}</div>}</td>
                  <td className="py-2">
                    <span className="flex items-center gap-1">
                      {p.projects.slice(0, 5).map((pr) => <ProjectAvatar key={pr.id} project={pr} size={18} />)}
                      {p.projects.length > 5 && <span className="text-xs text-fg-subtle">+{p.projects.length - 5}</span>}
                      {!p.projects.length && <span className="text-fg-subtlest">—</span>}
                    </span>
                  </td>
                  <td className="py-2"><span className="flex items-center gap-2"><Avatar user={p.owner} size="xs" />{p.owner.name}</span></td>
                  <td className="py-2">{choiceLabel(meta.data?.plans.access, p.access)}</td>
                  <td className="py-2 text-fg-subtle">{fmtRelative(p.updated_at)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </>}
      {actions.dialog}
      <Modal open={creating} onOpenChange={setCreating} title="Crear plan" width={680}>
        {creating && <PlanForm submitLabel="Crear plan" onCancel={() => setCreating(false)} onSaved={(p) => { setCreating(false); router.push(`/plans/${p.id}`); }} />}
      </Modal>
    </div>
  );
}
