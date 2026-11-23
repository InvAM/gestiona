"use client";

import { MoreHorizontal, Search, Star } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ProjectAvatar } from "@/components/icons";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, EmptyState, Menu, MenuContent, MenuItem, MenuTrigger, Tabs } from "@/components/ui/primitives";
import { useApp } from "@/components/shell/app-context";
import { useDebounced } from "@/components/board/filters-bar";
import { choiceLabel, useMeta, useProjects, useStarProject } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";


export default function ProjectsPage() {
  const { me } = useApp();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState("active");
  const dq = useDebounced(q);
  const projects = useProjects({ q: dq, archived: archived === "archived" });
  const star = useStarProject();
  const meta = useMeta();

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1200px] px-8 py-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-medium">Proyectos</h1>
          {me.can_create_projects && <Button variant="primary" onClick={() => router.push("/projects/new")}>Crear proyecto</Button>}
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-subtlest" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar proyectos"
                   className="h-8 w-60 rounded-[3px] border-2 border-line bg-bg pl-7 pr-2 text-sm outline-none focus:border-focus" />
          </div>
          <Tabs value={archived} onChange={setArchived} className="border-none"
                tabs={[{ value: "active", label: "Activos" }, { value: "archived", label: "Archivados" }]} />
        </div>
        {projects.isPending ? <PageSpinner /> : projects.data?.length ? (
          <table className="mt-6 w-full text-sm">
            <thead>
              <tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
                <th className="w-10 py-2"><Star size={14} /></th>
                <th className="py-2">Nombre</th><th className="py-2">Clave</th><th className="py-2">Tipo</th>
                <th className="py-2">Acceso</th><th className="py-2">Responsable</th><th className="py-2 text-right">Incidencias</th><th className="w-10" />
              </tr>
            </thead>
            <tbody>
              {projects.data.map((p) => (
                <tr key={p.id} className="border-b border-line hover:bg-bg-hover">
                  <td className="py-2">
                    <button aria-label={p.starred ? "Quitar de destacados" : "Destacar"} onClick={() => star.mutate({ key: p.key, starred: !p.starred })}>
                      <Star size={16} className={cn(p.starred ? "fill-warning text-warning" : "text-fg-subtlest")} />
                    </button>
                  </td>
                  <td className="py-2"><Link href={`/projects/${p.key}`} className="flex items-center gap-2 font-medium text-link hover:underline"><ProjectAvatar project={p} size={24} />{p.name}</Link></td>
                  <td className="py-2">{p.key}</td>
                  <td className="py-2 text-fg-subtle">{choiceLabel(meta.data?.project_templates, p.template)}</td>
                  <td className="py-2 text-fg-subtle">{choiceLabel(meta.data?.project_access, p.access)}</td>
                  <td className="py-2"><span className="flex items-center gap-2"><Avatar user={p.lead} size="xs" />{p.lead.name}</span></td>
                  <td className="py-2 text-right">{p.issue_count}</td>
                  <td className="py-2 text-right">
                    <Menu>
                      <MenuTrigger asChild><Button variant="subtle" size="icon-sm" aria-label="Acciones"><MoreHorizontal size={16} /></Button></MenuTrigger>
                      <MenuContent align="end">
                        <MenuItem onSelect={() => router.push(`/projects/${p.key}/issues`)}>Ver incidencias</MenuItem>
                        <MenuItem onSelect={() => router.push(`/projects/${p.key}/settings`)}>Configuración</MenuItem>
                      </MenuContent>
                    </Menu>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title={q ? "Ningún proyecto coincide" : archived === "archived" ? "No hay proyectos archivados" : "Aún no hay proyectos"}
                      body={me.can_create_projects && !q ? "Crea un proyecto para empezar a organizar el trabajo del equipo." : undefined}
                      action={me.can_create_projects && !q && archived === "active" ? <Button variant="primary" onClick={() => router.push("/projects/new")}>Crear proyecto</Button> : undefined} />
        )}
      </div>
    </main>
  );
}
