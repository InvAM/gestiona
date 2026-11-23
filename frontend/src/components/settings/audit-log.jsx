"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, Badge, EmptyState, Input } from "@/components/ui/primitives";
import { api, unwrap } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { fmtDateTime } from "@/lib/utils";

const PAGE = 50;
const sel = "h-8 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-sm";

export function AuditLog() {
  const meta = useMeta();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [start, setStart] = useState(0);
  const [open, setOpen] = useState(null);
  const page = useQuery({
    queryKey: ["audit", q, category, since, until, start],
    queryFn: () => unwrap(api.GET("/api/v1/admin/audit", { params: { query: { q, category, since: since || undefined, until: until || undefined, start, limit: PAGE } } })),
    placeholderData: keepPreviousData,
  });
  const reset = () => setStart(0);
  return (
    <div>
      <p className="mb-3 text-sm text-fg-subtle">Quién cambió la configuración, los permisos y los proyectos, cuándo y desde dónde. También se registran los inicios de sesión. Se conserva un año (configurable con <code>AUDIT_RETENTION_DAYS</code>).</p>
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-64" placeholder="Buscar acción, persona u objeto" value={q} onChange={(e) => { setQ(e.target.value); reset(); }} />
        <select className={sel} value={category} onChange={(e) => { setCategory(e.target.value); reset(); }}>
          <option value="">Todas las categorías</option>
          {(meta.data?.audit_categories ?? []).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        <label className="flex items-center gap-1 text-xs text-fg-subtle">Desde <Input type="date" className="h-8 w-40" value={since} onChange={(e) => { setSince(e.target.value); reset(); }} /></label>
        <label className="flex items-center gap-1 text-xs text-fg-subtle">Hasta <Input type="date" className="h-8 w-40" value={until} onChange={(e) => { setUntil(e.target.value); reset(); }} /></label>
      </div>
      {page.isPending ? <PageSpinner /> : !page.data?.items.length ? <EmptyState title="Sin registros" body="No hay eventos con esos filtros." /> : (
        <>
          <table className="mt-3 w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="w-6" /><th className="py-2">Fecha</th><th>Persona</th><th>Categoría</th><th>Acción</th><th>Objeto</th><th>IP</th></tr></thead>
            <tbody>{page.data.items.map((e) => (
              <Fragment key={e.id}>
                <tr className="cursor-pointer border-b border-line hover:bg-bg-hover" onClick={() => setOpen(open === e.id ? null : e.id)}>
                  <td className="py-2">{open === e.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                  <td className="whitespace-nowrap py-2 text-fg-subtle">{fmtDateTime(e.created_at)}</td>
                  <td className="py-2"><span className="flex items-center gap-1.5"><Avatar user={e.actor} size="xs" />{e.actor?.name ?? (e.actor_email || "Anónimo")}</span></td>
                  <td className="py-2"><Badge>{e.category_display}</Badge></td>
                  <td className="py-2">{e.action}</td>
                  <td className="py-2">{e.project_key && <b className="mr-1">{e.project_key}</b>}{e.object_repr !== e.project_key && e.object_repr}</td>
                  <td className="py-2 font-mono text-xs text-fg-subtle">{e.ip}</td>
                </tr>
                {open === e.id && (
                  <tr className="border-b border-line bg-bg-subtle">
                    <td />
                    <td colSpan={6} className="py-2 text-xs">
                      {e.method && <div className="mb-1 font-mono">{e.method} {e.path}</div>}
                      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-[3px] bg-bg-sunken p-2 font-mono">{JSON.stringify(e.details, null, 2)}</pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}</tbody>
          </table>
          <div className="mt-3 flex items-center gap-3 text-sm text-fg-subtle">
            <span>{start + 1}–{Math.min(start + PAGE, page.data.total)} de {page.data.total}</span>
            <Button size="sm" disabled={start === 0} onClick={() => setStart(Math.max(0, start - PAGE))}>Anterior</Button>
            <Button size="sm" disabled={start + PAGE >= page.data.total} onClick={() => setStart(start + PAGE)}>Siguiente</Button>
          </div>
        </>
      )}
    </div>
  );
}
