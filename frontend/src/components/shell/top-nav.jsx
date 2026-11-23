"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, ChevronDown, HelpCircle, Moon, Plus, Search, Settings, Sun, LogOut, User } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { IssueTypeIcon, Logo, ProjectAvatar } from "@/components/icons";
import { Button } from "@/components/ui/button";
import {
  Avatar, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Popover,
  PopoverContent, PopoverTrigger, Kbd,
} from "@/components/ui/primitives";
import { api, hardNavigate, unwrap } from "@/lib/api/client";
import { qk, useProjects, useUnreadCount } from "@/lib/api/hooks";
import { logout } from "@/lib/auth";
import { cn, fmtRelative } from "@/lib/utils";
import { useApp } from "./app-context";

function NavMenu({ label, active, children }) {
  return (
    <Menu modal={false}>
      <MenuTrigger asChild>
        <button className={cn("relative flex h-8 items-center gap-1 rounded-[3px] px-2 text-sm font-medium text-fg-subtle hover:bg-bg-hover data-[state=open]:bg-bg-selected data-[state=open]:text-brand",
                              active && "text-brand after:absolute after:inset-x-1 after:-bottom-[12px] after:h-[3px] after:rounded-t after:bg-brand")}>
          {label}<ChevronDown size={14} />
        </button>
      </MenuTrigger>
      <MenuContent className="w-80">{children}</MenuContent>
    </Menu>
  );
}

function ProjectsMenu() {
  const router = useRouter();
  const { me } = useApp();
  const recent = useQuery({
    queryKey: qk.recent("project"),
    queryFn: () => unwrap(api.GET("/api/v1/recent", { params: { query: { kind: "project", limit: 5 } } })),
  });
  const starred = useProjects({ starred: true });
  return (
    <>
      {!!starred.data?.length && (
        <>
          <MenuLabel>Destacados</MenuLabel>
          {starred.data.slice(0, 5).map((p) => (
            <MenuItem key={p.id} onSelect={() => router.push(`/projects/${p.key}`)}>
              <ProjectAvatar project={p} size={20} /><span className="truncate">{p.name}</span>
            </MenuItem>
          ))}
          <MenuSeparator />
        </>
      )}
      <MenuLabel>Recientes</MenuLabel>
      {recent.data?.length ? recent.data.map((r) => (
        <MenuItem key={r.id} onSelect={() => router.push(r.url)}>
          <ProjectAvatar project={{ avatar: r.icon ?? "rocket", color: "#1D5FD6" }} size={20} />
          <span className="min-w-0"><span className="block truncate">{r.title}</span>
            <span className="block truncate text-xs text-fg-subtlest">{r.subtitle}</span></span>
        </MenuItem>
      )) : <div className="px-3 py-1.5 text-sm text-fg-subtlest">Aún no visitaste proyectos</div>}
      <MenuSeparator />
      <MenuItem onSelect={() => router.push("/projects")}>Ver todos los proyectos</MenuItem>
      {me.can_create_projects && <MenuItem onSelect={() => router.push("/projects/new")}>Crear proyecto</MenuItem>}
    </>
  );
}

function FiltersMenu() {
  const router = useRouter();
  const starred = useQuery({
    queryKey: qk.filters({ starred: true }),
    queryFn: () => unwrap(api.GET("/api/v1/filters", { params: { query: { starred: true } } })),
  });
  return (
    <>
      <MenuItem onSelect={() => router.push("/issues")}>Ver todas las incidencias</MenuItem>
      <MenuItem onSelect={() => router.push("/issues?jql=" + encodeURIComponent("assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"))}>Mis incidencias abiertas</MenuItem>
      <MenuItem onSelect={() => router.push("/issues?jql=" + encodeURIComponent("reporter = currentUser() ORDER BY created DESC"))}>Informadas por mí</MenuItem>
      <MenuSeparator />
      <MenuLabel>Filtros destacados</MenuLabel>
      {starred.data?.length ? starred.data.map((f) => (
        <MenuItem key={f.id} onSelect={() => router.push(`/issues?filter=${f.id}`)}>{f.name}</MenuItem>
      )) : <div className="px-3 py-1.5 text-sm text-fg-subtlest">Sin filtros destacados</div>}
      <MenuSeparator />
      <MenuItem onSelect={() => router.push("/filters")}>Ver todos los filtros</MenuItem>
    </>
  );
}

function GlobalSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const results = useQuery({
    queryKey: ["picker", q],
    queryFn: () => unwrap(api.GET("/api/v1/issues/picker", { params: { query: { q, limit: 8 } } })),
    enabled: open,
  });
  const go = (url) => { setOpen(false); setQ(""); router.push(url); };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div className="relative w-[200px] transition-[width] focus-within:w-[360px] lg:w-[240px]">
          <Search size={16} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-subtlest" />
          <input id="global-search" value={q} placeholder="Buscar"
                 onChange={(e) => { setQ(e.target.value); setOpen(true); }}
                 onFocus={() => setOpen(true)}
                 onKeyDown={(e) => {
                   if (e.key === "Enter" && q.trim()) {
                     const s = q.trim();
                     go(/^[A-Z][A-Z0-9]+-\d+$/i.test(s) ? `/browse/${s.toUpperCase()}`
                       : `/issues?jql=${encodeURIComponent(`text ~ "${s.replace(/"/g, "")}" ORDER BY updated DESC`)}`);
                   }
                   if (e.key === "Escape") setOpen(false);
                 }}
                 className="h-8 w-full rounded-[3px] border-2 border-line bg-bg pl-8 pr-2 text-sm outline-none placeholder:text-fg-subtlest focus:border-focus" />
        </div>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[480px] py-2" onOpenAutoFocus={(e) => e.preventDefault()}
                      onInteractOutside={(e) => { if (e.target.id === "global-search") e.preventDefault(); }}>
        <div className="px-3 pb-1 text-[11px] font-bold uppercase text-fg-subtlest">{q ? "Incidencias" : "Vistas recientemente"}</div>
        {results.data?.map((i) => (
          <button key={i.id} onClick={() => go(`/browse/${i.key}`)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-bg-hover">
            <IssueTypeIcon type={i.type} />
            <span className="min-w-0 flex-1"><span className="block truncate text-sm">{i.summary}</span>
              <span className="block text-xs text-fg-subtlest">{i.key}</span></span>
          </button>
        ))}
        {results.data && !results.data.length && <div className="px-3 py-2 text-sm text-fg-subtlest">Sin resultados</div>}
        <div className="mt-1 border-t border-line px-3 pt-2 text-xs text-fg-subtlest">
          Pulsa <Kbd>Enter</Kbd> para búsqueda avanzada · <Kbd>/</Kbd> para enfocar
        </div>
      </PopoverContent>
    </Popover>
  );
}

function Notifications() {
  const router = useRouter();
  const qc = useQueryClient();
  const unread = useUnreadCount();
  const [open, setOpen] = useState(false);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const list = useQuery({
    queryKey: [...qk.notifications, onlyUnread],
    queryFn: () => unwrap(api.GET("/api/v1/notifications", { params: { query: { unread: onlyUnread } } })),
    enabled: open,
  });
  const markAll = async () => {
    await unwrap(api.POST("/api/v1/notifications/read", { body: { all: true } }));
    qc.invalidateQueries({ queryKey: qk.notifications });
    qc.invalidateQueries({ queryKey: qk.unread });
  };
  const openOne = async (id, key) => {
    await unwrap(api.POST("/api/v1/notifications/read", { body: { ids: [id] } }));
    qc.invalidateQueries({ queryKey: qk.unread });
    setOpen(false);
    if (key) router.push(`/browse/${key}`);
  };
  const count = unread.data?.unread ?? 0;
  const VERB = {
    issue_created: "creó", issue_assigned: "te asignó", issue_updated: "actualizó",
    issue_transitioned: "cambió el estado de", comment_added: "comentó en", mentioned: "te mencionó en",
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="subtle" size="icon" aria-label="Notificaciones" className="relative rounded-full">
          <Bell size={18} />
          {count > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-danger px-1 text-[10px] font-bold leading-4 text-white">{count > 9 ? "9+" : count}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[440px]">
        <div className="flex items-center justify-between px-4 pb-2 pt-4">
          <h2 className="text-xl font-medium">Notificaciones</h2>
          <label className="flex items-center gap-2 text-xs text-fg-subtle">
            Solo no leídas <input type="checkbox" checked={onlyUnread} onChange={(e) => setOnlyUnread(e.target.checked)} />
          </label>
        </div>
        <div className="flex justify-end px-4 pb-2"><Button variant="link" size="sm" onClick={markAll}>Marcar todo como leído</Button></div>
        <div className="max-h-[60vh] overflow-y-auto border-t border-line">
          {list.data?.length ? list.data.map((n) => (
            <button key={n.id} onClick={() => openOne(n.id, n.issue_key)}
                    className={cn("flex w-full gap-3 border-b border-line px-4 py-3 text-left hover:bg-bg-hover", !n.read && "bg-bg-selected/40")}>
              <Avatar user={n.actor} size="md" />
              <span className="min-w-0 flex-1 text-sm">
                <span><b>{n.actor?.name ?? "Alguien"}</b> {VERB[n.event] ?? "actualizó"} <b>{n.issue_key}</b></span>
                <span className="block truncate text-fg-subtle">{n.issue_summary}</span>
                {n.event === "issue_transitioned" && <span className="block text-xs text-fg-subtlest">{String(n.data.from)} → {String(n.data.to)}</span>}
                <span className="block text-xs text-fg-subtlest">{fmtRelative(n.created_at)}</span>
              </span>
              {!n.read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand" />}
            </button>
          )) : <div className="px-4 py-10 text-center text-sm text-fg-subtlest">{list.isLoading ? "Cargando…" : "No hay notificaciones"}</div>}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(() => typeof document !== "undefined" && document.documentElement.dataset.theme === "dark");
  const toggle = () => {
    const next = !dark;
    setDark(next);
    if (next) document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("gestiona-theme", next ? "dark" : "light"); } catch { /* ignore */ }
  };
  return (
    <MenuItem onSelect={(e) => { e.preventDefault(); toggle(); }}>
      {dark ? <Sun size={16} /> : <Moon size={16} />} Tema {dark ? "claro" : "oscuro"}
    </MenuItem>
  );
}

export function TopNav() {
  const { me, openCreate, lastProjectKey } = useApp();
  const pathname = usePathname();
  const router = useRouter();
  return (
    <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center gap-1 border-b border-line bg-bg px-3">
      <Link href="/your-work" className="mr-3 rounded-[3px] px-1 py-1 hover:bg-bg-hover"><Logo size={24} /></Link>
      <nav className="hidden items-center gap-1 md:flex">
        <Link href="/your-work" className={cn("relative flex h-8 items-center rounded-[3px] px-2 text-sm font-medium text-fg-subtle hover:bg-bg-hover",
                                              pathname === "/your-work" && "text-brand after:absolute after:inset-x-1 after:-bottom-[12px] after:h-[3px] after:rounded-t after:bg-brand")}>
          Tu trabajo
        </Link>
        <NavMenu label="Proyectos" active={pathname.startsWith("/projects")}><ProjectsMenu /></NavMenu>
        <NavMenu label="Filtros" active={pathname.startsWith("/issues") || pathname.startsWith("/filters")}><FiltersMenu /></NavMenu>
        <Link href="/dashboards" className={cn("flex h-8 items-center rounded-[3px] px-2 text-sm font-medium text-fg-subtle hover:bg-bg-hover", pathname.startsWith("/dashboards") && "text-brand")}>Paneles</Link>
        <Link href="/plans" className={cn("flex h-8 items-center rounded-[3px] px-2 text-sm font-medium text-fg-subtle hover:bg-bg-hover", pathname.startsWith("/plans") && "text-brand")}>Planes</Link>
        <Link href="/analytics" className={cn("flex h-8 items-center rounded-[3px] px-2 text-sm font-medium text-fg-subtle hover:bg-bg-hover", pathname.startsWith("/analytics") && "text-brand")}>Analíticas</Link>
        {me.is_admin && (
          <Link href="/settings" className={cn("flex h-8 items-center rounded-[3px] px-2 text-sm font-medium text-fg-subtle hover:bg-bg-hover", pathname.startsWith("/settings") && "text-brand")}>
            Administración
          </Link>
        )}
      </nav>
      <Button variant="primary" className="ml-2" onClick={() => openCreate({ projectKey: lastProjectKey })}>
        <Plus size={16} className="md:hidden" /><span className="hidden md:inline">Crear</span>
      </Button>
      <div className="ml-auto flex items-center gap-1">
        <GlobalSearch />
        <Notifications />
        <Button variant="subtle" size="icon" className="rounded-full" aria-label="Ayuda" asChild>
          <Link href="/help"><HelpCircle size={18} /></Link>
        </Button>
        {me.is_admin && (
          <Button variant="subtle" size="icon" className="rounded-full" aria-label="Configuración" asChild>
            <Link href="/settings"><Settings size={18} /></Link>
          </Button>
        )}
        <Menu>
          <MenuTrigger asChild>
            <button className="ml-1 rounded-full p-0.5 hover:bg-bg-hover" aria-label="Tu perfil"><Avatar user={me} size="sm" /></button>
          </MenuTrigger>
          <MenuContent align="end" className="w-64">
            <div className="flex items-center gap-3 px-3 py-2">
              <Avatar user={me} size="lg" />
              <div className="min-w-0"><div className="truncate font-medium">{me.name}</div>
                <div className="truncate text-xs text-fg-subtlest">{me.email}</div></div>
            </div>
            <MenuSeparator />
            <MenuItem onSelect={() => router.push("/profile")}><User size={16} /> Perfil y preferencias</MenuItem>
            <ThemeToggle />
            <MenuSeparator />
            <MenuItem onSelect={async () => { await logout(); hardNavigate("/auth/login"); }}>
              <LogOut size={16} /> Cerrar sesión
            </MenuItem>
          </MenuContent>
        </Menu>
      </div>
    </header>
  );
}
