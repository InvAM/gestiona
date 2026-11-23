"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Copy, LayoutDashboard, MoreHorizontal, Pencil, Plus, RefreshCw, Settings2, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, Badge, EmptyState, Field, Input, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, Modal, Textarea } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { cn, fmtRelative } from "@/lib/utils";
import { GadgetBody, GadgetConfig, GadgetPreview, defaultConfig } from "./gadgets";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

/* ------------------------------------------------------------------ list */

export function DashboardList() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState("active");
  const meta = useMeta();
  const list = useQuery({ queryKey: ["dashboards", q], queryFn: () => unwrap(api.GET("/api/v1/dashboards", { params: { query: { q } } })) });
  const deleted = useDeletedList("/api/v1/dashboards", "dashboards", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/dashboards", queryKey: "dashboards" });
  return (
    <div className="mx-auto w-full max-w-[1100px] px-6 py-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-medium">Paneles</h1>
        <Button variant="primary" className="ml-auto" onClick={() => setCreating(true)}><Plus size={16} />Crear panel</Button>
      </div>
      <CatalogTabs value={view} onChange={setView} className="mt-4" />
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} allowPurge={false} empty="No hay paneles eliminados." />
      ) : <>
      <Input className="mt-4 w-72" placeholder="Buscar paneles" value={q} onChange={(e) => setQ(e.target.value)} />
      {list.isPending ? <PageSpinner /> : !list.data?.length ? (
        <EmptyState icon={<LayoutDashboard size={40} />} title="Todavía no hay paneles" body="Un panel reúne gadgets: tus incidencias, gráficos por estado, creadas vs. resueltas, burndown del sprint y más." action={<Button onClick={() => setCreating(true)}>Crear mi primer panel</Button>} />
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="w-8" /><th className="py-2">Nombre</th><th>Propietario</th><th>Visible para</th><th>Actualizado</th></tr></thead>
          <tbody>{list.data.map((d) => (
            <tr key={d.id} className="border-b border-line hover:bg-bg-hover">
              <td className="py-2"><Star size={14} className={cn(d.starred ? "fill-warning text-warning" : "text-fg-subtlest")} /></td>
              <td className="py-2"><Link className="font-medium text-link hover:underline" href={`/dashboards/${d.id}`}>{d.name}</Link>{d.description && <div className="text-xs text-fg-subtle">{d.description}</div>}</td>
              <td className="py-2"><span className="flex items-center gap-2"><Avatar user={d.owner} size="xs" />{d.owner?.name}</span></td>
              <td className="py-2">{choiceLabel(meta.data?.dashboard_visibility, d.visibility)}</td>
              <td className="py-2 text-fg-subtle">{fmtRelative(d.updated_at)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      </>}
      {actions.dialog}
      <DashboardForm open={creating} onOpenChange={setCreating} onSaved={(d) => router.push(`/dashboards/${d.id}`)} />
    </div>
  );
}

function DashboardForm({ open, onOpenChange, dashboard, onSaved }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={dashboard ? "Editar panel" : "Crear panel"} width={520}>
      {open && <DashboardFormBody dashboard={dashboard} onClose={() => onOpenChange(false)} onSaved={onSaved} />}
    </Modal>
  );
}

function DashboardFormBody({ dashboard, onClose, onSaved }) {
  const meta = useMeta();
  const qc = useQueryClient();
  const [name, setName] = useState(dashboard?.name ?? "");
  const [description, setDescription] = useState(dashboard?.description ?? "");
  const [visibility, setVisibility] = useState(dashboard?.visibility ?? "private");
  const [columns, setColumns] = useState(dashboard?.columns ?? 2);
  const [template, setTemplate] = useState("default");
  const save = useMutation({
    mutationFn: () => dashboard
      ? unwrap(api.PATCH("/api/v1/dashboards/{did}", { params: { path: { did: dashboard.id } }, body: { name, description, visibility, columns } }))
      : unwrap(api.POST("/api/v1/dashboards", { body: { name, description, visibility, columns, template } })),
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["dashboards"] }); qc.invalidateQueries({ queryKey: ["dashboard", d.id] }); onClose(); onSaved(d); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field label="Nombre" required><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Field>
      <Field label="Descripción"><Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Visible para">
          <select className={sel} value={visibility} onChange={(e) => setVisibility(e.target.value)}>{(meta.data?.dashboard_visibility ?? []).map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}</select>
        </Field>
        <Field label="Columnas">
          <select className={sel} value={columns} onChange={(e) => setColumns(Number(e.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option></select>
        </Field>
      </div>
      {!dashboard && (
        <Field label="Empezar con">
          <select className={sel} value={template} onChange={(e) => setTemplate(e.target.value)}><option value="default">Gadgets recomendados</option><option value="blank">Panel vacío</option></select>
        </Field>
      )}
      <div className="flex justify-end gap-2"><Button type="button" variant="subtle" onClick={onClose}>Cancelar</Button><Button type="submit" variant="primary" disabled={!name.trim()} loading={save.isPending}>Guardar</Button></div>
    </form>
  );
}

/* ------------------------------------------------------------------ view */

export function DashboardView({ id }) {
  const router = useRouter();
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["dashboard", id], queryFn: () => unwrap(api.GET("/api/v1/dashboards/{did}", { params: { path: { did: id } } })) });
  const [editMeta, setEditMeta] = useState(false);
  const [adding, setAdding] = useState(null);
  const [configuring, setConfiguring] = useState(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["dashboard", id] });
  const actions = useCatalogActions({ path: "/api/v1/dashboards", queryKey: "dashboards", softBody: "Sus gadgets se conservan; los filtros y las incidencias no se tocan.",
                                      onDeleted: () => router.push("/dashboards") });

  const star = useMutation({
    mutationFn: (on) => on ? unwrap(api.POST("/api/v1/dashboards/{did}/star", { params: { path: { did: id } } })) : unwrap(api.DELETE("/api/v1/dashboards/{did}/star", { params: { path: { did: id } } })),
    onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["dashboards"] }); },
  });
  const copy = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/dashboards/{did}/copy", { params: { path: { did: id } } })),
    onSuccess: (c) => { toast.success("Panel copiado"); router.push(`/dashboards/${c.id}`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const layout = useMutation({
    mutationFn: (gadgets) => unwrap(api.PUT("/api/v1/dashboards/{did}/layout", { params: { path: { did: id } }, body: { gadgets } })),
    onSuccess: (dash) => qc.setQueryData(["dashboard", id], dash),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const removeGadget = useMutation({
    mutationFn: (gid) => unwrap(api.DELETE("/api/v1/dashboards/{did}/gadgets/{gid}", { params: { path: { did: id, gid } } })),
    onSuccess: refresh,
  });

  if (d.isPending) return <PageSpinner />;
  if (!d.data) return <EmptyState title="Panel no encontrado" body="Puede que sea privado o que lo hayan eliminado." action={<Button asChild><Link href="/dashboards">Ver paneles</Link></Button>} />;
  const dash = { ...d.data, gadgets: d.data.gadgets ?? [] };
  const cols = Array.from({ length: dash.columns }, (_, c) => dash.gadgets.filter((g) => g.column === c).sort((a, b) => a.position - b.position));

  const move = (g, dc, dp) => {
    const next = cols.map((col) => col.filter((x) => x.id !== g.id));
    const target = Math.max(0, Math.min(dash.columns - 1, g.column + dc));
    const curIdx = cols[g.column].findIndex((x) => x.id === g.id);
    const idx = dc ? next[target].length : Math.max(0, Math.min(next[target].length, curIdx + dp));
    next[target].splice(idx, 0, g);
    layout.mutate(next.flatMap((col, c) => col.map((x, p) => ({ id: x.id, column: c, position: p }))));
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-5">
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/dashboards" className="text-sm text-link hover:underline">Paneles</Link>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <h1 className="text-2xl font-medium">{dash.name}</h1>
        <button aria-label={dash.starred ? "Quitar de destacados" : "Destacar"} onClick={() => star.mutate(!dash.starred)}>
          <Star size={18} className={cn(dash.starred ? "fill-warning text-warning" : "text-fg-subtlest")} />
        </button>
        {dash.visibility === "public" && <Badge>Compartido</Badge>}
        <div className="ml-auto flex gap-2">
          <Button variant="subtle" onClick={() => qc.invalidateQueries({ queryKey: ["gadget"] })}><RefreshCw size={16} />Actualizar</Button>
          {dash.can_edit && <Button onClick={() => setAdding(0)}><Plus size={16} />Agregar gadget</Button>}
          <Menu>
            <MenuTrigger asChild><Button variant="subtle" size="icon" aria-label="Más acciones"><MoreHorizontal size={18} /></Button></MenuTrigger>
            <MenuContent align="end">
              {dash.can_edit && <MenuItem onSelect={() => setEditMeta(true)}><Pencil size={16} />Editar y compartir</MenuItem>}
              <MenuItem onSelect={() => copy.mutate()}><Copy size={16} />Copiar panel</MenuItem>
              {dash.can_edit && (<><MenuSeparator /><MenuItem danger onSelect={() => actions.askDelete(dash)}><Trash2 size={16} />Eliminar</MenuItem></>)}
            </MenuContent>
          </Menu>
        </div>
      </div>
      {dash.description && <p className="mt-1 text-sm text-fg-subtle">{dash.description}</p>}
      {!dash.gadgets.length ? (
        <EmptyState icon={<LayoutDashboard size={40} />} title="Panel vacío" body="Agrega gadgets para ver tus incidencias, gráficos y la actividad del equipo." action={dash.can_edit ? <Button onClick={() => setAdding(0)}>Agregar gadget</Button> : undefined} />
      ) : (
        <div className={cn("mt-4 grid items-start gap-4", dash.columns === 1 ? "grid-cols-1" : dash.columns === 2 ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1 lg:grid-cols-3")}>
          {cols.map((col, c) => (
            <div key={c} className="flex min-w-0 flex-col gap-4">
              {col.map((g, i) => (
                <section key={g.id} className="min-w-0 rounded-[3px] border border-line bg-bg shadow-[var(--shadow-raised)]">
                  <header className="flex items-center gap-1 border-b border-line px-3 py-2">
                    <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{g.title || g.kind_display}</h2>
                    {dash.can_edit && (
                      <Menu>
                        <MenuTrigger asChild><Button size="icon" variant="subtle" aria-label="Opciones del gadget"><MoreHorizontal size={16} /></Button></MenuTrigger>
                        <MenuContent align="end">
                          <MenuItem onSelect={() => setConfiguring(g)}><Settings2 size={16} />Configurar</MenuItem>
                          <MenuItem disabled={i === 0} onSelect={() => move(g, 0, -1)}><ArrowUp size={16} />Subir</MenuItem>
                          <MenuItem disabled={i === col.length - 1} onSelect={() => move(g, 0, 1)}><ArrowDown size={16} />Bajar</MenuItem>
                          {c > 0 && <MenuItem onSelect={() => move(g, -1, 0)}><ArrowLeft size={16} />Columna izquierda</MenuItem>}
                          {c < dash.columns - 1 && <MenuItem onSelect={() => move(g, 1, 0)}><ArrowRight size={16} />Columna derecha</MenuItem>}
                          <MenuSeparator />
                          <MenuItem danger onSelect={() => removeGadget.mutate(g.id)}><Trash2 size={16} />Quitar</MenuItem>
                        </MenuContent>
                      </Menu>
                    )}
                  </header>
                  <div className="p-3"><GadgetBody dashboardId={dash.id} gadget={g} /></div>
                </section>
              ))}
              {dash.can_edit && <button className="rounded-[3px] border border-dashed border-line-strong py-3 text-sm text-fg-subtle hover:bg-bg-hover" onClick={() => setAdding(c)}><Plus size={14} className="mr-1 inline" />Agregar gadget</button>}
            </div>
          ))}
        </div>
      )}
      <DashboardForm open={editMeta} onOpenChange={setEditMeta} dashboard={dash} onSaved={() => undefined} />
      <Modal open={adding !== null || !!configuring} onOpenChange={(o) => { if (!o) { setAdding(null); setConfiguring(null); } }} title={configuring ? `Configurar «${configuring.title || configuring.kind_display}»` : "Agregar gadget"} width={820}>
        {(adding !== null || configuring) && <GadgetEditor key={configuring?.id ?? `new-${adding}`} dashboardId={dash.id} column={adding ?? 0} gadget={configuring ?? undefined} onDone={() => { setAdding(null); setConfiguring(null); refresh(); qc.invalidateQueries({ queryKey: ["gadget"] }); }} />}
      </Modal>
      {actions.dialog}
    </div>
  );
}

function GadgetEditor({ dashboardId, column, gadget, onDone }) {
  const meta = useMeta();
  const [kind, setKind] = useState(gadget?.kind ?? null);
  const [title, setTitle] = useState(gadget?.title ?? "");
  const [config, setConfig] = useState(gadget?.config ?? {});
  const [previewCfg, setPreviewCfg] = useState(gadget?.config ?? null);
  const save = useMutation({
    mutationFn: () => gadget
      ? unwrap(api.PATCH("/api/v1/dashboards/{did}/gadgets/{gid}", { params: { path: { did: dashboardId, gid: gadget.id } }, body: { title, config } }))
      : unwrap(api.POST("/api/v1/dashboards/{did}/gadgets", { params: { path: { did: dashboardId } }, body: { kind: kind, title, config, column } })),
    onSuccess: () => { toast.success("Gadget guardado"); onDone(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!kind) {
    return (
      <div className="grid gap-2 sm:grid-cols-2">
        {meta.isPending && <PageSpinner />}
        {(meta.data?.gadget_kinds ?? []).map((k) => (
          <button key={k.value} className="rounded-[3px] border border-line p-3 text-left hover:bg-bg-hover"
                  onClick={() => { setKind(k.value); setTitle(k.label); const c = defaultConfig(k.value); setConfig(c); setPreviewCfg(c); }}>
            <b className="text-sm">{k.label}</b><div className="text-xs text-fg-subtle">{k.description}</div>
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <Field label="Título"><Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} /></Field>
      <GadgetConfig kind={kind} config={config} onChange={setConfig} />
      <div className="flex justify-end"><Button size="sm" onClick={() => setPreviewCfg(config)}><RefreshCw size={14} />Actualizar vista previa</Button></div>
      {previewCfg && <GadgetPreview kind={kind} config={previewCfg} />}
      <div className="flex justify-end gap-2 border-t border-line pt-3">
        {!gadget && <Button variant="subtle" onClick={() => setKind(null)}>Atrás</Button>}
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{gadget ? "Guardar" : "Agregar al panel"}</Button>
      </div>
    </div>
  );
}
