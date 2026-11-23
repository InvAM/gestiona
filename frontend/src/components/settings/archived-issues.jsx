"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon } from "@/components/icons";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, EmptyState, Input, Lozenge } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { invalidateIssueViews } from "@/lib/api/hooks";
import { fmtRelative } from "@/lib/utils";

export function ArchivedIssues({ projectKey }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const list = useQuery({
    queryKey: ["archived", projectKey, q],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{pkey}/archived-issues", { params: { path: { pkey: projectKey }, query: { q } } })),
  });
  const restore = useMutation({
    mutationFn: (key) => unwrap(api.POST("/api/v1/issues/{key}/restore", { params: { path: { key } } })),
    onSuccess: (i) => { toast.success(`${i.key} restaurada`); qc.invalidateQueries({ queryKey: ["archived", projectKey] }); invalidateIssueViews(qc); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="max-w-[920px]">
      <p className="mb-3 text-sm text-fg-subtle">Las incidencias archivadas son de solo lectura y no aparecen en tableros, backlog ni búsquedas. Archiva desde el menú «…» de la incidencia o con el cambio masivo.</p>
      <Input className="w-72" placeholder="Buscar por clave o resumen" value={q} onChange={(e) => setQ(e.target.value)} />
      {list.isPending ? <PageSpinner /> : !list.data?.length ? (
        <EmptyState title="No hay incidencias archivadas" body="Cuando archives incidencias terminadas u obsoletas aparecerán aquí." />
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="w-8" /><th className="py-2">Clave</th><th>Resumen</th><th>Estado</th><th>Archivada</th><th className="w-28" /></tr></thead>
          <tbody>{list.data.map((i) => (
            <tr key={i.id} className="border-b border-line">
              <td className="py-2"><IssueTypeIcon type={i.type} /></td>
              <td className="whitespace-nowrap py-2"><Link className="text-link hover:underline" href={`/browse/${i.key}`}>{i.key}</Link></td>
              <td className="max-w-0 truncate py-2 pr-2">{i.summary}</td>
              <td className="py-2"><Lozenge category={i.status.category}>{i.status.name}</Lozenge></td>
              <td className="whitespace-nowrap py-2 text-fg-subtle"><span className="flex items-center gap-1.5"><Avatar user={i.archived_by} size="xs" />{i.archived_at ? fmtRelative(i.archived_at) : ""}</span></td>
              <td className="py-2 text-right"><Button size="sm" loading={restore.isPending && restore.variables === i.key} onClick={() => restore.mutate(i.key)}>Restaurar</Button></td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}
