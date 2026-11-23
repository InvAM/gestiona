"use client";

import {
  BarChart3, ChevronsLeft, ChevronsRight, Columns3, CalendarDays, GanttChart, ListTodo, Package, Settings, Rows3,
  Layers, Plus, Table2,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CreateBoardDialog, boardHref } from "@/components/board/create-board-dialog";
import { ProjectAvatar } from "@/components/icons";
import { useProjectMeta } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";
import { useApp } from "./app-context";

export function ProjectSidebar({ projectKey }) {
  const meta = useProjectMeta(projectKey);
  const pathname = usePathname();
  const router = useRouter();
  const [creatingBoard, setCreatingBoard] = useState(false);
  const { setLastProjectKey } = useApp();
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    try { return localStorage.getItem("gestiona-sidebar") === "1"; } catch { return false; }
  });
  useEffect(() => { setLastProjectKey(projectKey); }, [projectKey, setLastProjectKey]);
  const toggle = () => {
    setCollapsed((c) => { try { localStorage.setItem("gestiona-sidebar", c ? "0" : "1"); } catch { /* */ } return !c; });
  };

  const p = meta.data?.project;
  const board = meta.data?.boards[0];
  const base = `/projects/${projectKey}`;
  const isScrum = board?.kind === "scrum";
  const isAdmin = meta.data?.permissions.includes("administer");
  const items = [
    { href: `${base}/timeline`, label: "Cronograma", icon: GanttChart },
    { href: `${base}/calendar`, label: "Calendario", icon: CalendarDays },
    board && { href: `${base}/boards/${board.id}/backlog`, label: "Backlog", icon: ListTodo },
    board && { href: `${base}/boards/${board.id}`, label: isScrum ? "Sprint activo" : "Tablero", icon: Columns3, exact: true },
    // flow reports (control chart, time in status, throughput) work without a board
    { href: `${base}/reports`, label: "Informes", icon: BarChart3 },
    { href: `${base}/list`, label: "Lista", icon: Table2 },
    { href: `${base}/issues`, label: "Incidencias", icon: Rows3 },
    { href: `${base}/releases`, label: "Versiones", icon: Package },
    { href: `${base}/components`, label: "Componentes", icon: Layers },
  ].filter(Boolean);

  if (collapsed) {
    return (
      <aside className="relative w-5 shrink-0 border-r border-line bg-bg-subtle">
        <button onClick={toggle} aria-label="Expandir barra lateral"
                className="absolute left-2 top-8 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-line bg-bg text-fg-subtle shadow-raised hover:bg-brand hover:text-white">
          <ChevronsRight size={14} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="group/sb relative hidden w-60 shrink-0 flex-col border-r border-line bg-bg-subtle md:flex">
      <button onClick={toggle} aria-label="Contraer barra lateral"
              className="absolute -right-3 top-8 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-line bg-bg text-fg-subtle opacity-0 shadow-raised transition-opacity hover:bg-brand hover:text-white group-hover/sb:opacity-100">
        <ChevronsLeft size={14} />
      </button>
      <div className="flex items-center gap-2 px-4 pb-4 pt-6">
        <ProjectAvatar project={p} size={32} />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{p?.name ?? projectKey}</div>
          <div className="truncate text-xs text-fg-subtle">{p?.template === "business" ? "Proyecto de negocio" : "Proyecto de software"}</div>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto px-2">
        <div className="px-2 pb-1 text-[11px] font-bold uppercase text-fg-subtlest">Planificación</div>
        {meta.data && !board && (
          // Like Jira: a project without boards offers to create one where Backlog/Board were
          isAdmin ? (
            <button type="button" onClick={() => setCreatingBoard(true)}
                    className="mb-0.5 flex h-9 w-full items-center gap-3 rounded-[3px] px-2 text-left text-sm text-fg-subtle hover:bg-bg-hover">
              <Plus size={18} />Crear tablero
            </button>
          ) : (
            <div className="mb-0.5 flex h-9 items-center gap-3 px-2 text-sm text-fg-subtlest" title="Pide a un administrador del proyecto que cree uno">
              <Columns3 size={18} />Sin tableros
            </div>
          )
        )}
        {items.map((it) => {
          const active = it.exact ? pathname === it.href : pathname.startsWith(it.href);
          return (
            <Link key={it.href} href={it.href}
                  className={cn("relative mb-0.5 flex h-9 items-center gap-3 rounded-[3px] px-2 text-sm text-fg-subtle hover:bg-bg-hover",
                                active && "bg-bg-selected font-medium text-brand before:absolute before:inset-y-2 before:left-0 before:w-1 before:rounded-r before:bg-brand")}>
              <it.icon size={18} />{it.label}
            </Link>
          );
        })}
      </nav>
      {isAdmin && (
        <div className="border-t border-line p-2">
          <Link href={`${base}/settings`}
                className={cn("flex h-9 items-center gap-3 rounded-[3px] px-2 text-sm text-fg-subtle hover:bg-bg-hover",
                              pathname.startsWith(`${base}/settings`) && "bg-bg-selected font-medium text-brand")}>
            <Settings size={18} />Configuración del proyecto
          </Link>
        </div>
      )}
      {isAdmin && (
        <CreateBoardDialog projectKey={projectKey} open={creatingBoard} onOpenChange={setCreatingBoard}
                           onCreated={(b) => router.push(boardHref(projectKey, b))} />
      )}
    </aside>
  );
}
