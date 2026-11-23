"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { IssueTypeIcon, ProjectAvatar } from "@/components/icons";
import { PageSpinner } from "@/components/ui/button";
import { EmptyState, Lozenge, Tabs } from "@/components/ui/primitives";
import { useApp } from "@/components/shell/app-context";
import { api, unwrap } from "@/lib/api/client";
import { qk, useProjects } from "@/lib/api/hooks";
import { fmtRelative } from "@/lib/utils";

export default function YourWorkPage() {
  const { me } = useApp();
  const [tab, setTab] = useState("assigned");
  const summary = useQuery({ queryKey: ["your-work"], queryFn: () => unwrap(api.GET("/api/v1/dashboard/summary")) });
  const recent = useQuery({ queryKey: qk.recent("issue"), queryFn: () => unwrap(api.GET("/api/v1/recent", { params: { query: { kind: "issue", limit: 30 } } })) });
  const projects = useProjects({});
  const starred = useProjects({ starred: true });
  const recentProjects = (projects.data ?? []).slice(0, 6);

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1200px] px-8 py-8">
        <h1 className="text-2xl font-medium">Tu trabajo</h1>
        <p className="mt-1 text-fg-subtle">Hola, {me.name.split(" ")[0]}. Esto es lo que tienes pendiente.</p>

        <div className="mt-8 flex items-center justify-between">
          <h2 className="text-base font-semibold">Proyectos</h2>
          <Link href="/projects" className="text-sm text-link hover:underline">Ver todos los proyectos</Link>
        </div>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {recentProjects.map((p) => (
            <Link key={p.id} href={`/projects/${p.key}`}
                  className="group overflow-hidden rounded-[3px] bg-bg shadow-raised transition-shadow hover:shadow-overlay">
              <div className="flex gap-3 border-l-[20px] p-4" style={{ borderColor: p.color }}>
                <ProjectAvatar project={p} size={32} />
                <div className="min-w-0">
                  <div className="truncate font-semibold group-hover:underline">{p.name}</div>
                  <div className="text-xs text-fg-subtle">{p.template === "business" ? "Proyecto de negocio" : "Proyecto de software"}</div>
                  <div className="mt-3 text-xs font-semibold uppercase text-fg-subtle">Enlaces rápidos</div>
                  <div className="mt-1 flex items-center justify-between gap-4 text-sm">
                    <span>Incidencias</span><span className="rounded-full bg-bg-sunken px-2 text-xs">{p.issue_count ?? 0}</span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
          {!projects.isPending && !recentProjects.length && (
            <div className="col-span-full rounded-[3px] border border-dashed border-line p-6 text-center text-fg-subtle">
              Aún no tienes proyectos. {me.can_create_projects && <Link href="/projects/new" className="text-link hover:underline">Crea el primero</Link>}
            </div>
          )}
        </div>

        <Tabs className="mt-10" value={tab} onChange={setTab} tabs={[
          { value: "assigned", label: <>Asignadas a mí <span className="ml-1 rounded-full bg-bg-sunken px-1.5 text-xs">{summary.data?.assigned.length ?? 0}</span></> },
          { value: "worked", label: "Trabajado en" },
          { value: "viewed", label: "Visto" },
          { value: "starred", label: "Destacados" },
        ]} />
        <div className="mt-2">
          {summary.isPending ? <PageSpinner /> : tab === "assigned" || tab === "worked" ? (
            (tab === "assigned" ? summary.data?.assigned : summary.data?.worked_on)?.length ? (
              <ul>
                {(tab === "assigned" ? summary.data.assigned : summary.data.worked_on).map((i) => (
                  <li key={i.id}>
                    <Link href={`/browse/${i.key}`} className="flex items-center gap-3 rounded-[3px] px-2 py-2 hover:bg-bg-hover">
                      <IssueTypeIcon type={i.type} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm">{i.summary}</span>
                        <span className="block text-xs text-fg-subtle">{i.key} · {i.project_name}</span>
                      </span>
                      <Lozenge category={i.status.category}>{i.status.name}</Lozenge>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <EmptyState title={tab === "assigned" ? "No tienes incidencias asignadas" : "Aún no trabajaste en incidencias"}
                            body="Las incidencias abiertas asignadas a ti aparecerán aquí." />
          ) : tab === "viewed" ? (
            recent.data?.length ? (
              <ul>
                {recent.data.map((r) => (
                  <li key={r.id}>
                    <Link href={r.url} className="flex items-center gap-3 rounded-[3px] px-2 py-2 hover:bg-bg-hover">
                      <IssueTypeIcon type={{ icon: r.icon ?? "task", color: { epic: "#904EE2", story: "#63BA3C", bug: "#E5493A" }[r.icon ?? ""] ?? "#4BADE8" }} />
                      <span className="min-w-0 flex-1"><span className="block truncate text-sm">{r.title}</span>
                        <span className="block text-xs text-fg-subtle">{r.subtitle}</span></span>
                      <span className="text-xs text-fg-subtlest">{fmtRelative(r.viewed_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <EmptyState title="No viste incidencias recientemente" />
          ) : (
            starred.data?.length ? (
              <ul>
                {starred.data.map((p) => (
                  <li key={p.id}><Link href={`/projects/${p.key}`} className="flex items-center gap-3 rounded-[3px] px-2 py-2 hover:bg-bg-hover">
                    <ProjectAvatar project={p} size={20} /><span className="text-sm">{p.name}</span></Link></li>
                ))}
              </ul>
            ) : <EmptyState title="No tienes elementos destacados" body="Marca proyectos con la estrella para encontrarlos rápido." />
          )}
        </div>
      </div>
    </main>
  );
}
