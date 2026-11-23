"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, EmptyState, Tabs } from "@/components/ui/primitives";
import { api, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";

export default function FiltersPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState("all");
  const meta = useMeta();
  const filters = useQuery({
    queryKey: ["filters", tab],
    queryFn: () => unwrap(api.GET("/api/v1/filters", { params: { query: { mine: tab === "mine", starred: tab === "starred" } } })),
    enabled: tab !== "deleted",
  });
  const deleted = useDeletedList("/api/v1/filters", "filters", tab === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/filters", queryKey: "filters", softBody: "Deja de aparecer en búsquedas y paneles." });
  const star = useMutation({
    mutationFn: ({ id, on }) => on
      ? unwrap(api.POST("/api/v1/filters/{fid}/star", { params: { path: { fid: id } } }))
      : unwrap(api.DELETE("/api/v1/filters/{fid}/star", { params: { path: { fid: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["filters"] }),
  });
  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1100px] px-8 py-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-medium">Filtros</h1>
          <Button variant="primary" asChild><Link href="/issues">Crear filtro</Link></Button>
        </div>
        <Tabs className="mt-6" value={tab} onChange={setTab} tabs={[{ value: "all", label: "Todos" }, { value: "mine", label: "Mis filtros" }, { value: "starred", label: "Destacados" }, { value: "deleted", label: "Eliminados" }]} />
        {tab === "deleted" ? (
          <DeletedList query={deleted} actions={actions} allowPurge={false} render={(f) => <span><b>{f.name}</b> <span className="font-mono text-xs text-fg-subtle">{f.jql}</span></span>} empty="No hay filtros eliminados." />
        ) : filters.isPending ? <PageSpinner /> : filters.data?.length ? (
          <table className="mt-4 w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
              <th className="w-8 py-2" /><th className="py-2">Nombre</th><th className="py-2">Propietario</th><th className="py-2">Visible para</th><th className="py-2">Consulta</th><th className="w-10" /></tr></thead>
            <tbody>
              {filters.data.map((f) => (
                <tr key={f.id} className="border-b border-line hover:bg-bg-hover">
                  <td className="py-2"><button aria-label="Destacar" onClick={() => star.mutate({ id: f.id, on: !f.starred })}><Star size={16} className={cn(f.starred ? "fill-warning text-warning" : "text-fg-subtlest")} /></button></td>
                  <td className="py-2"><Link href={`/issues?filter=${f.id}`} className="font-medium text-link hover:underline">{f.name}</Link>
                    {f.description && <div className="text-xs text-fg-subtle">{f.description}</div>}</td>
                  <td className="py-2"><span className="flex items-center gap-2"><Avatar user={f.owner} size="xs" />{f.owner.name}</span></td>
                  <td className="py-2 text-fg-subtle">{choiceLabel(meta.data?.filter_visibility, f.visibility)}</td>
                  <td className="max-w-80 truncate py-2 font-mono text-xs text-fg-subtle">{f.jql}</td>
                  <td className="py-2">{f.is_owner && <Button variant="subtle" size="icon-sm" aria-label="Eliminar filtro" onClick={() => actions.askDelete(f)}><Trash2 size={14} /></Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <EmptyState title="No hay filtros" body="Guarda una búsqueda desde la página de incidencias para reutilizarla." />}
        {actions.dialog}
      </div>
    </main>
  );
}
