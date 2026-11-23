"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageSpinner } from "@/components/ui/button";
import { Confirm, EmptyState, Tabs } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { fmtRelative } from "@/lib/utils";

/*
 * Shared behaviour for soft-deletable admin catalogs (statuses, issue types, priorities,
 * resolutions, custom fields, link types, workflows, roles). Backend contract:
 *   DELETE {path}/{id}                 → papelera (409 in_use while something depends on it)
 *   DELETE {path}/{id}?permanent=true  → borrado definitivo (409 protected si hay referencias)
 *   POST   {path}/{id}/restore         → restaurar (409 name_taken)
 *   GET    {path}?deleted=true         → elementos eliminados
 * Conflicts are shown with the backend message inside the confirmation dialog.
 */

export function useDeletedList(path, queryKey, enabled, query = {}) {
  return useQuery({
    queryKey: [queryKey, "deleted", query],
    queryFn: () => unwrap(api.GET(path, { params: { query: { ...query, deleted: true } } })),
    enabled,
  });
}

const SOFT_BODY = "Deja de estar disponible para nuevas incidencias y configuraciones. Lo que ya lo usa lo conserva.";

export function useCatalogActions({ path, queryKey, related = [], label = (r) => r.name, onDeleted, softBody = SOFT_BODY }) {
  const qc = useQueryClient();
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const refresh = () => {
    for (const k of [queryKey, ...related]) qc.invalidateQueries({ queryKey: [k] });
  };
  const restore = useMutation({
    mutationFn: (row) => unwrap(api.POST(`${path}/${row.id}/restore`)),
    onSuccess: (_d, row) => { refresh(); toast.success(`«${label(row)}» restaurado`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: ({ row, permanent }) =>
      unwrap(api.DELETE(`${path}/${row.id}`, { params: { query: permanent ? { permanent: true } : {} } })),
    onSuccess: (_d, { row, permanent }) => {
      setPending(null);
      refresh();
      onDeleted?.(row, permanent);
      if (permanent) toast.success(`«${label(row)}» eliminado definitivamente`);
      else toast.success(`«${label(row)}» eliminado`, { action: { label: "Deshacer", onClick: () => restore.mutate(row) } });
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const ask = (row, permanent = false) => { setError(null); setPending({ row, permanent }); };
  const close = () => { setPending(null); setError(null); };
  const name = pending ? label(pending.row) : "";
  const dialog = (
    <Confirm open={!!pending} onOpenChange={(o) => !o && close()} danger loading={remove.isPending}
             title={pending?.permanent ? `¿Eliminar definitivamente «${name}»?` : `¿Eliminar «${name}»?`}
             confirmLabel={pending?.permanent ? "Eliminar definitivamente" : "Eliminar"}
             body={(
               <div className="space-y-3">
                 <p>{pending?.permanent
                   ? "Se borra para siempre. No se puede deshacer."
                   : `${softBody} Puedes restaurarlo desde «Eliminados».`}</p>
                 {error && <p role="alert" className="rounded-[3px] bg-danger-subtle px-3 py-2 text-danger">{error}</p>}
               </div>
             )}
             onConfirm={() => pending && remove.mutate(pending)} />
  );
  return { askDelete: (row) => ask(row), askPurge: (row) => ask(row, true), restore, dialog };
}

/** «Activos / Eliminados» switch shown above each catalog. */
export function CatalogTabs({ value, onChange, className }) {
  return (
    <Tabs className={className} value={value} onChange={onChange}
          tabs={[{ value: "active", label: "Activos" }, { value: "deleted", label: "Eliminados" }]} />
  );
}

/** Generic list of deleted rows with Restaurar / Eliminar definitivamente. */
export function DeletedList({ query, actions, render = (r) => r.name, empty = "No hay elementos eliminados.", allowPurge = true }) {
  if (query.isPending) return <PageSpinner />;
  if (query.error) return <p className="mt-4 text-sm text-danger">{errorMessage(query.error)}</p>;
  if (!query.data?.length) return <EmptyState title="Papelera vacía" body={empty} />;
  return (
    <table className="mt-3 w-full text-sm">
      <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Nombre</th><th className="py-2">Eliminado</th><th className={allowPurge ? "w-72" : "w-32"} /></tr></thead>
      <tbody>{query.data.map((r) => (
        <tr key={r.id} className="border-b border-line">
          <td className="py-2">{render(r)}</td>
          <td className="py-2 text-fg-subtle">{r.deleted_at ? fmtRelative(r.deleted_at) : "—"}</td>
          <td className="py-2 text-right">
            <span className="inline-flex gap-1">
              <Button size="sm" loading={actions.restore.isPending && actions.restore.variables?.id === r.id} onClick={() => actions.restore.mutate(r)}><RotateCcw size={14} />Restaurar</Button>
              {allowPurge && <Button size="sm" variant="subtle" onClick={() => actions.askPurge(r)}><Trash2 size={14} />Eliminar definitivamente</Button>}
            </span>
          </td>
        </tr>
      ))}</tbody>
    </table>
  );
}
