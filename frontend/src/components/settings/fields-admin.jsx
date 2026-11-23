"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { draggable, dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { attachClosestEdge } from "@atlaskit/pragmatic-drag-and-drop-hitbox/closest-edge/attach-closest-edge";
import { AlertTriangle, ArrowDown, ArrowUp, GripVertical, Lock, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon } from "@/components/icons";
import { FieldShell } from "@/components/fields/screen-form";
import { Button, PageSpinner } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Badge, EmptyState, Input, Modal, Textarea, Toggle } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { combine, extractClosestEdge, monitorForElements } from "@/lib/dnd";
import { cn } from "@/lib/utils";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "./catalog";

/*
 * Administration of screens and field configuration (Jira company-managed), contract
 * [S 17:45] in FASE4. Every collection follows the common soft-delete contract (papelera,
 * restaurar, borrado definitivo) and only system admins reach these pages.
 */

const SEL = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";
// Everything that depends on the resolved rules (issue forms, Lista, project settings).
const RELATED = ["field-rules", "project-meta", "field-schemes"];

export const COLLECTIONS = {
  fc: { path: "/api/v1/field-configurations", key: "field-configurations" },
  fcs: { path: "/api/v1/field-configuration-schemes", key: "field-configuration-schemes" },
  screens: { path: "/api/v1/screens", key: "screens" },
  ss: { path: "/api/v1/screen-schemes", key: "screen-schemes" },
  itss: { path: "/api/v1/issue-type-screen-schemes", key: "issue-type-screen-schemes" },
};

export function useCollection(c, enabled = true) {
  return useQuery({ queryKey: [c.key], queryFn: () => unwrap(api.GET(c.path)), enabled, staleTime: 30_000 });
}

/** Field catalogue (system + live custom fields): GET /fields. */
export function useFieldCatalog() {
  return useQuery({ queryKey: ["fields-catalog"], queryFn: () => unwrap(api.GET("/api/v1/fields")), staleTime: 60_000 });
}

function useIssueTypes() {
  return useQuery({ queryKey: ["issue-types"], queryFn: () => unwrap(api.GET("/api/v1/issue-types")) });
}

/** Save (POST or PUT) a row of a collection; errors stay in the editor. */
function useSave(c, onDone) {
  const qc = useQueryClient();
  const [error, setError] = useState(null);
  const m = useMutation({
    mutationFn: ({ id, body }) => (id
      ? unwrap(api.PUT(`${c.path}/${id}`, { body }))
      : unwrap(api.POST(c.path, { body }))),
    onSuccess: (row) => {
      for (const k of [c.key, ...RELATED, ...Object.values(COLLECTIONS).map((x) => x.key)]) qc.invalidateQueries({ queryKey: [k] });
      toast.success(`«${row?.name ?? ""}» guardado`);
      setError(null);
      onDone?.(row);
    },
    onError: (e) => setError(errorMessage(e)),
  });
  return { ...m, error, setError };
}

function Usage({ items, empty = "Sin usar", label }) {
  if (!items?.length) return <span className="text-fg-subtlest">{empty}</span>;
  return <span title={items.map((x) => x.name ?? x.key).join(", ")}>{label}: {items.map((x) => x.key ?? x.name).join(", ")}</span>;
}

function DefaultBadge({ row }) {
  return row.is_default ? <Badge className="ml-2 bg-brand text-fg-inverse">Predeterminado</Badge> : null;
}

function ErrorBox({ error }) {
  if (!error) return null;
  return <p role="alert" className="flex items-start gap-2 rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger"><AlertTriangle size={16} className="mt-0.5 shrink-0" />{error}</p>;
}

/** Name, description and «Predeterminado» shared by every editor. */
function BasicsFields({ value, onChange, defaultHint }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FieldShell label="Nombre" required>
        {(a11y) => <Input autoFocus value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} {...a11y} />}
      </FieldShell>
      <div className="flex items-end gap-2 pb-1.5 text-sm">
        <Toggle label="Predeterminado" checked={!!value.is_default} onChange={(v) => onChange({ ...value, is_default: v })} />
        <span>Predeterminado <span className="block text-xs text-fg-subtle">{defaultHint}</span></span>
      </div>
      <FieldShell label="Descripción" className="sm:col-span-2">
        {(a11y) => <Textarea rows={2} value={value.description ?? ""} onChange={(e) => onChange({ ...value, description: e.target.value })} {...a11y} />}
      </FieldShell>
    </div>
  );
}

/**
 * List + papelera + editor in a modal, the same layout for the five collections.
 * `columns`: [{label, render(row)}]; `Editor`: ({row, onClose}) => form.
 */
function CollectionPage({ c, intro, columns, Editor, createLabel, emptyTitle, emptyBody, softBody, width = 760 }) {
  const list = useCollection(c);
  const [view, setView] = useState("active");
  const [edit, setEdit] = useState(null);
  const deleted = useDeletedList(c.path, c.key, view === "deleted");
  const actions = useCatalogActions({ path: c.path, queryKey: c.key, related: RELATED, softBody });
  return (
    <div className="max-w-[1000px]">
      <p className="mb-4 max-w-[760px] text-sm text-fg-subtle">{intro}</p>
      <div className="flex items-end justify-between gap-3">
        <CatalogTabs value={view} onChange={setView} className="flex-1" />
        {view === "active" && <Button variant="primary" onClick={() => setEdit("new")}><Plus size={16} />{createLabel}</Button>}
      </div>
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} empty="La papelera está vacía." />
      ) : list.isPending ? <PageSpinner /> : list.error ? <p role="alert" className="mt-4 text-sm text-danger">{errorMessage(list.error)}</p> : !list.data.length ? (
        <EmptyState title={emptyTitle} body={emptyBody} action={<Button onClick={() => setEdit("new")}>{createLabel}</Button>} />
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
              <th className="py-2">Nombre</th>{columns.map((col) => <th key={col.label} className="py-2 pr-3">{col.label}</th>)}<th className="w-24" />
            </tr></thead>
            <tbody>{list.data.map((r) => (
              <tr key={r.id} className="border-b border-line align-top">
                <td className="py-2 pr-3">
                  <button type="button" className="text-left font-medium text-link hover:underline" onClick={() => setEdit(r)}>{r.name}</button><DefaultBadge row={r} />
                  {r.description && <span className="block text-xs text-fg-subtle">{r.description}</span>}
                </td>
                {columns.map((col) => <td key={col.label} className="py-2 pr-3 text-fg-subtle">{col.render(r)}</td>)}
                <td className="py-2 text-right">
                  <Button variant="subtle" size="icon-sm" aria-label={`Editar ${r.name}`} onClick={() => setEdit(r)}><Pencil size={14} /></Button>
                  <Button variant="subtle" size="icon-sm" aria-label={`Eliminar ${r.name}`} onClick={() => actions.askDelete(r)}><Trash2 size={14} /></Button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {actions.dialog}
      {edit && (
        <Modal open onOpenChange={(o) => !o && setEdit(null)} width={width}
               title={edit === "new" ? createLabel : `Editar «${edit.name}»`}>
          <Editor key={edit === "new" ? "new" : edit.id} row={edit === "new" ? null : edit} onClose={() => setEdit(null)} />
        </Modal>
      )}
    </div>
  );
}

function EditorFooter({ onClose, onSave, saving, disabled, extra }) {
  return (
    <div className="sticky bottom-0 -mx-6 mt-4 flex items-center gap-2 border-t border-line bg-bg-overlay px-6 py-3">
      {extra}
      <div className="ml-auto flex gap-2">
        <Button variant="subtle" onClick={onClose}>Cancelar</Button>
        <Button variant="primary" loading={saving} disabled={disabled} onClick={onSave}>Guardar</Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ field configurations */

export function FieldConfigurations() {
  return (
    <CollectionPage c={COLLECTIONS.fc} createLabel="Crear configuración" width={960}
                    intro="Una configuración de campos decide, para cada campo, si es obligatorio, si está oculto y qué texto de ayuda muestra. Se asigna a los tipos de incidencia con un esquema de configuración."
                    emptyTitle="Sin configuraciones" emptyBody="Crea una configuración para marcar campos obligatorios u ocultos."
                    softBody="Deja de estar disponible para los esquemas."
                    columns={[
                      { label: "Obligatorios", render: (r) => r.fields?.filter((f) => f.required && !f.locked).length ?? 0 },
                      { label: "Ocultos", render: (r) => r.fields?.filter((f) => f.hidden).length ?? 0 },
                      { label: "Esquemas", render: (r) => <Usage items={r.schemes} label="Usada en" /> },
                      { label: "Avisos", render: (r) => (r.warnings?.length ? <span className="flex items-center gap-1 text-warning"><AlertTriangle size={14} />{r.warnings.length}</span> : "—") },
                    ]}
                    Editor={FieldConfigurationEditor} />
  );
}

function FieldConfigurationEditor({ row, onClose }) {
  const catalog = useFieldCatalog();
  const [basics, setBasics] = useState({ name: row?.name ?? "", description: row?.description ?? "", is_default: !!row?.is_default });
  const [rules, setRules] = useState(() => new Map((row?.fields ?? []).map((f) => [f.key, { required: !!f.required, hidden: !!f.hidden, description: f.description ?? "" }])));
  const [q, setQ] = useState("");
  const save = useSave(COLLECTIONS.fc, onClose);
  if (catalog.isPending) return <PageSpinner />;
  if (catalog.error) return <ErrorBox error={errorMessage(catalog.error)} />;
  // every key of the catalogue, with what this configuration says (row fields carry all keys)
  const fields = (row?.fields?.length ? row.fields : catalog.data).map((f) => {
    const cat = catalog.data.find((c) => c.key === f.key) ?? f;
    return { key: f.key, label: cat.label, kind: cat.kind, system: cat.system, locked: !!cat.locked };
  });
  for (const c of catalog.data) if (!fields.some((f) => f.key === c.key)) fields.push({ key: c.key, label: c.label, kind: c.kind, system: c.system, locked: !!c.locked });
  const ruleOf = (f) => (f.locked ? { required: true, hidden: false, description: rules.get(f.key)?.description ?? "" } : rules.get(f.key) ?? { required: false, hidden: false, description: "" });
  const set = (key, patch) => setRules((m) => { const n = new Map(m); n.set(key, { ...(n.get(key) ?? { required: false, hidden: false, description: "" }), ...patch }); return n; });
  const shown = fields.filter((f) => !q || f.label.toLowerCase().includes(q.toLowerCase()));
  const submit = () => {
    // sparse: only what differs from optional/visible/no description
    const out = fields.map((f) => ({ key: f.key, ...ruleOf(f) }))
      .filter((f) => f.required || f.hidden || f.description.trim())
      .map((f) => ({ ...f, description: f.description.trim() }));
    save.mutate({ id: row?.id, body: { ...basics, fields: out } });
  };
  return (
    <div className="space-y-4">
      <ErrorBox error={save.error} />
      <BasicsFields value={basics} onChange={setBasics} defaultHint="La reciben los esquemas nuevos." />
      {row?.warnings?.length > 0 && (
        <ul className="space-y-1 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm" role="note">
          {row.warnings.map((w) => <li key={w.field} className="flex gap-2"><AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" />{w.message}</li>)}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold">Campos</h3>
        <label className="relative ml-auto">
          <span className="sr-only">Buscar campo</span>
          <Search size={14} className="absolute left-2 top-2 text-fg-subtlest" aria-hidden="true" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar campo" className="w-56 pl-7" />
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
            <th className="py-2">Campo</th><th className="w-28 py-2">Obligatorio</th><th className="w-24 py-2">Oculto</th><th className="py-2">Descripción (texto de ayuda)</th>
          </tr></thead>
          <tbody>{shown.map((f) => {
            const r = ruleOf(f);
            return (
              <tr key={f.key} className="border-b border-line">
                <td className="py-1.5 pr-3">
                  <span className="flex items-center gap-1.5 font-medium">{f.label}{f.locked && <Lock size={12} className="text-fg-subtlest" aria-label="Bloqueado" />}</span>
                  <span className="text-xs text-fg-subtlest">{f.system ? "Sistema" : "Personalizado"}</span>
                </td>
                <td className="py-1.5">
                  <Toggle label={`${f.label}: obligatorio`} checked={r.required} disabled={f.locked || r.hidden}
                          title={f.locked ? "Siempre obligatorio" : r.hidden ? "Un campo oculto no puede ser obligatorio" : undefined}
                          onChange={(v) => set(f.key, { required: v, hidden: v ? false : r.hidden })} />
                </td>
                <td className="py-1.5">
                  <Toggle label={`${f.label}: oculto`} checked={r.hidden} disabled={f.locked} title={f.locked ? "No se puede ocultar" : undefined}
                          onChange={(v) => set(f.key, { hidden: v, required: v ? false : r.required })} />
                </td>
                <td className="py-1.5">
                  <Input value={r.description} maxLength={500} aria-label={`Descripción de ${f.label}`} placeholder="Sin descripción" disabled={r.hidden}
                         onChange={(e) => set(f.key, { description: e.target.value })} />
                </td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      <EditorFooter onClose={onClose} onSave={submit} saving={save.isPending} disabled={!basics.name.trim()} />
    </div>
  );
}

/* ------------------------------------------------------------------ type → X mapping (schemes) */

function TypeMapping({ entries, onChange, options, defaultLabel, defaultValue, onDefault, emptyOption }) {
  const types = useIssueTypes();
  const used = new Set(entries.map((e) => e.issue_type_id));
  const free = (types.data ?? []).filter((t) => !used.has(t.id));
  const name = (id) => options.find((o) => o.value === id)?.label;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[minmax(160px,1fr)_minmax(200px,1.4fr)_auto] items-center gap-2 rounded-[3px] bg-bg-subtle px-2 py-1.5 text-sm">
        <span className="font-semibold">Predeterminado <span className="block text-xs font-normal text-fg-subtle">Tipos sin asociación</span></span>
        <Picker value={defaultValue} width={300} onSelect={onDefault} options={options}
                trigger={<button type="button" className={SEL} aria-label={defaultLabel}>{name(defaultValue) ?? <span className="text-fg-subtlest">{emptyOption}</span>}</button>} />
        <span className="w-8" />
      </div>
      {entries.map((e, i) => {
        const t = types.data?.find((x) => x.id === e.issue_type_id);
        return (
          <div key={e.issue_type_id} className="grid grid-cols-[minmax(160px,1fr)_minmax(200px,1.4fr)_auto] items-center gap-2 px-2 text-sm">
            <span className="flex items-center gap-2"><IssueTypeIcon type={t} />{t?.name ?? `Tipo ${e.issue_type_id}`}</span>
            <Picker value={e.value} width={300} onSelect={(v) => onChange(entries.map((x, j) => (j === i ? { ...x, value: v } : x)))} options={options}
                    trigger={<button type="button" className={SEL} aria-label={`${defaultLabel} de ${t?.name ?? ""}`}>{name(e.value) ?? <span className="text-fg-subtlest">{emptyOption}</span>}</button>} />
            <Button variant="subtle" size="icon-sm" aria-label={`Quitar ${t?.name ?? ""}`} onClick={() => onChange(entries.filter((_, j) => j !== i))}><X size={14} /></Button>
          </div>
        );
      })}
      {free.length > 0 && (
        <Picker width={260} placeholder="Tipo de incidencia" onSelect={(id) => onChange([...entries, { issue_type_id: id, value: defaultValue ?? options[0]?.value ?? null }])}
                options={free.map((t) => ({ value: t.id, label: t.name, icon: <IssueTypeIcon type={t} /> }))}
                trigger={<Button size="sm"><Plus size={14} />Asociar un tipo</Button>} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ field configuration schemes */

export function FieldConfigurationSchemes() {
  return (
    <CollectionPage c={COLLECTIONS.fcs} createLabel="Crear esquema" width={760}
                    intro="Un esquema de configuración de campos asocia cada tipo de incidencia con una configuración de campos. Los proyectos usan un esquema (Configuración del proyecto › Campos)."
                    emptyTitle="Sin esquemas" emptyBody="Crea un esquema para usar configuraciones distintas por tipo."
                    softBody="Deja de estar disponible para los proyectos."
                    columns={[
                      { label: "Configuración", render: (r) => r.default_configuration?.name ?? "—" },
                      { label: "Por tipo", render: (r) => (r.entries?.length ? r.entries.map((e) => `${e.issue_type.name} → ${e.configuration.name}`).join(" · ") : "—") },
                      { label: "Proyectos", render: (r) => <Usage items={r.projects} label="Usado en" /> },
                    ]}
                    Editor={FieldConfigurationSchemeEditor} />
  );
}

function FieldConfigurationSchemeEditor({ row, onClose }) {
  const configs = useCollection(COLLECTIONS.fc);
  const [basics, setBasics] = useState({ name: row?.name ?? "", description: row?.description ?? "", is_default: !!row?.is_default });
  const [def, setDef] = useState(row?.default_configuration?.id ?? null);
  const [entries, setEntries] = useState((row?.entries ?? []).map((e) => ({ issue_type_id: e.issue_type.id, value: e.configuration.id })));
  const save = useSave(COLLECTIONS.fcs, onClose);
  if (configs.isPending) return <PageSpinner />;
  const options = (configs.data ?? []).map((c) => ({ value: c.id, label: c.name, description: c.is_default ? "Predeterminada" : c.description }));
  const defaultId = def ?? configs.data?.find((c) => c.is_default)?.id ?? null;
  return (
    <div className="space-y-4">
      <ErrorBox error={save.error} />
      <BasicsFields value={basics} onChange={setBasics} defaultHint="Lo reciben los proyectos nuevos." />
      <div>
        <h3 className="mb-2 text-sm font-semibold">Tipo de incidencia → configuración de campos</h3>
        <TypeMapping entries={entries} onChange={setEntries} options={options} defaultLabel="Configuración" emptyOption="Elegir configuración"
                     defaultValue={defaultId} onDefault={setDef} />
      </div>
      {row?.projects?.length > 0 && <p className="text-xs text-fg-subtle">Lo usan: {row.projects.map((p) => p.key).join(", ")}. Los cambios se aplican al momento.</p>}
      <EditorFooter onClose={onClose} saving={save.isPending} disabled={!basics.name.trim() || !defaultId || entries.some((e) => !e.value)}
                    onSave={() => save.mutate({ id: row?.id, body: { ...basics, default_configuration_id: defaultId, entries: entries.map((e) => ({ issue_type_id: e.issue_type_id, configuration_id: e.value })) } })} />
    </div>
  );
}

/* ------------------------------------------------------------------ screens */

export function Screens() {
  return (
    <CollectionPage c={COLLECTIONS.screens} createLabel="Crear pantalla" width={980}
                    intro="Una pantalla ordena los campos en pestañas. Los esquemas de pantalla deciden qué pantalla se usa para crear, editar y ver; las transiciones de los flujos también pueden mostrar una."
                    emptyTitle="Sin pantallas" emptyBody="Crea una pantalla y arrastra los campos en el orden que quieras."
                    softBody="Deja de estar disponible para esquemas y transiciones."
                    columns={[
                      { label: "Campos", render: (r) => `${r.tabs?.reduce((n, t) => n + t.fields.length, 0) ?? 0} en ${r.tabs?.length ?? 0} ${r.tabs?.length === 1 ? "pestaña" : "pestañas"}` },
                      { label: "Esquemas", render: (r) => <Usage items={r.screen_schemes} label="Usada en" /> },
                      { label: "Transiciones", render: (r) => (r.transitions?.length ? r.transitions.map((t) => `${t.workflow_name} › ${t.transition_name}`).join(" · ") : "—") },
                    ]}
                    Editor={ScreenEditor} />
  );
}

let tabSeq = 0;
const newTabId = () => `new-${++tabSeq}`;

/** Drag a field: item of the screen editor (pragmatic-drag-and-drop). */
function DraggableField({ field, tabId, index, count, tabs, onMove, onMoveTab, onRemove }) {
  const ref = useRef(null);
  const handle = useRef(null);
  const [edge, setEdge] = useState(null);
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    return combine(
      draggable({
        element: el, dragHandle: handle.current ?? undefined,
        getInitialData: () => ({ type: "screen-field", key: field.key, tabId }),
        onDragStart: () => setDragging(true), onDrop: () => setDragging(false),
      }),
      dropTargetForElements({
        element: el,
        canDrop: ({ source }) => source.data.type === "screen-field" && source.data.key !== field.key,
        getData: ({ input, element }) => attachClosestEdge({ type: "screen-field-target", key: field.key, tabId }, { input, element, allowedEdges: ["top", "bottom"] }),
        onDrag: ({ self }) => setEdge(extractClosestEdge(self.data)),
        onDragLeave: () => setEdge(null), onDrop: () => setEdge(null),
      }),
    );
  }, [field.key, tabId]);
  return (
    <li ref={ref} className={cn("relative flex items-center gap-2 rounded-[3px] border border-line bg-bg px-2 py-1.5 text-sm", dragging && "opacity-40")}>
      {edge && <span aria-hidden="true" className={cn("absolute left-0 right-0 h-0.5 bg-brand", edge === "top" ? "-top-1" : "-bottom-1")} />}
      <span ref={handle} className="cursor-grab text-fg-subtlest" aria-hidden="true"><GripVertical size={14} /></span>
      <span className="min-w-0 flex-1 truncate">{field.label}{field.locked && <Lock size={12} className="ml-1 inline text-fg-subtlest" aria-label="Bloqueado" />}</span>
      <span className="text-xs text-fg-subtlest">{field.system ? "Sistema" : "Personalizado"}</span>
      {tabs.length > 1 && (
        <select aria-label={`Mover «${field.label}» a otra pestaña`} value={String(tabId)} onChange={(e) => onMoveTab(e.target.value)}
                className="h-6 rounded-[3px] border border-line bg-bg-subtle px-1 text-xs">
          {tabs.map((t) => <option key={t.id} value={String(t.id)}>{t.name || "Sin nombre"}</option>)}
        </select>
      )}
      <Button variant="subtle" size="icon-sm" aria-label={`Subir «${field.label}»`} disabled={index === 0} onClick={() => onMove(index - 1)}><ArrowUp size={12} /></Button>
      <Button variant="subtle" size="icon-sm" aria-label={`Bajar «${field.label}»`} disabled={index === count - 1} onClick={() => onMove(index + 1)}><ArrowDown size={12} /></Button>
      <Button variant="subtle" size="icon-sm" aria-label={`Quitar «${field.label}»`} onClick={onRemove}><X size={12} /></Button>
    </li>
  );
}

function TabDropZone({ tabId, children, className }) {
  const ref = useRef(null);
  const [over, setOver] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    return dropTargetForElements({
      element: el,
      canDrop: ({ source }) => source.data.type === "screen-field",
      getData: () => ({ type: "screen-tab-target", tabId }),
      onDragEnter: () => setOver(true), onDragLeave: () => setOver(false), onDrop: () => setOver(false),
    });
  }, [tabId]);
  return <div ref={ref} className={cn(className, over && "outline-2 outline-dashed outline-brand")}>{children}</div>;
}

/**
 * Required fields (of the field configurations in use) missing from this screen where some
 * project creates issues with it: screen scheme (create, or default without create) → issue
 * type screen scheme → project ↔ field configuration scheme → configuration of that type.
 */
function useCreateWarnings(screenId, keys) {
  const ss = useCollection(COLLECTIONS.ss, !!screenId);
  const itss = useCollection(COLLECTIONS.itss, !!screenId);
  const fcs = useCollection(COLLECTIONS.fcs, !!screenId);
  const fc = useCollection(COLLECTIONS.fc, !!screenId);
  const out = new Map();
  if (!screenId || !ss.data || !itss.data || !fcs.data || !fc.data) return out;
  const createOf = (schemeId) => {
    const s = ss.data.find((x) => x.id === schemeId);
    return s ? (s.create_screen?.id ?? s.default_screen?.id) : null;
  };
  const configById = new Map(fc.data.map((c) => [c.id, c]));
  for (const it of itss.data) {
    for (const project of it.projects ?? []) {
      const f = fcs.data.find((x) => x.projects?.some((p) => p.id === project.id));
      if (!f) continue;
      const typeIds = new Set([...(it.entries ?? []).map((e) => e.issue_type.id), ...(f.entries ?? []).map((e) => e.issue_type.id), null]);
      for (const tid of typeIds) {
        const schemeId = (it.entries ?? []).find((e) => e.issue_type.id === tid)?.screen_scheme.id ?? it.default_screen_scheme?.id;
        if (createOf(schemeId) !== screenId) continue;
        const confId = (f.entries ?? []).find((e) => e.issue_type.id === tid)?.configuration.id ?? f.default_configuration?.id;
        const conf = configById.get(confId);
        for (const fld of conf?.fields ?? []) {
          if (!fld.required || fld.hidden || fld.locked || keys.has(fld.key)) continue;
          const typeName = tid === null ? "los demás tipos" : (it.entries.find((e) => e.issue_type.id === tid)?.issue_type.name ?? f.entries.find((e) => e.issue_type.id === tid)?.issue_type.name);
          const list = out.get(fld.key) ?? { label: fld.label, where: new Set() };
          list.where.add(`${project.key} (${typeName}, «${conf.name}»)`);
          out.set(fld.key, list);
        }
      }
    }
  }
  return out;
}

function ScreenEditor({ row, onClose }) {
  const catalog = useFieldCatalog();
  const [basics, setBasics] = useState({ name: row?.name ?? "", description: row?.description ?? "", is_default: !!row?.is_default });
  const [tabs, setTabs] = useState(() => (row?.tabs?.length
    ? row.tabs.map((t) => ({ id: t.id ?? newTabId(), name: t.name, fields: t.fields.map((f) => f.key) }))
    : [{ id: newTabId(), name: "Campos", fields: ["summary", "issue_type", "description"] }]));
  const [active, setActive] = useState(0);
  const save = useSave(COLLECTIONS.screens, onClose);
  const keys = new Set(tabs.flatMap((t) => t.fields));
  const warnings = useCreateWarnings(row?.id ?? null, keys);

  const moveField = (key, toTab, toIndex) => setTabs((ts) => {
    const fromTab = ts.find((t) => t.fields.includes(key));
    if (!fromTab) return ts;
    const without = ts.map((t) => ({ ...t, fields: t.fields.filter((k) => k !== key) }));
    return without.map((t) => {
      if (String(t.id) !== String(toTab)) return t;
      const f = [...t.fields];
      f.splice(Math.max(0, Math.min(toIndex, f.length)), 0, key);
      return { ...t, fields: f };
    });
  });

  // drag & drop: drop on a field (before/after it) or on a tab (at its end)
  useEffect(() => monitorForElements({
    canMonitor: ({ source }) => source.data.type === "screen-field",
    onDrop: ({ source, location }) => {
      const targets = location.current.dropTargets;
      const onField = targets.find((t) => t.data.type === "screen-field-target");
      const onTab = targets.find((t) => t.data.type === "screen-tab-target");
      const key = source.data.key;
      setTabs((ts) => {
        if (onField) {
          const tab = ts.find((t) => String(t.id) === String(onField.data.tabId));
          if (!tab) return ts;
          const rest = tab.fields.filter((k) => k !== key);
          let i = rest.indexOf(onField.data.key);
          if (extractClosestEdge(onField.data) === "bottom") i += 1;
          const without = ts.map((t) => ({ ...t, fields: t.fields.filter((k) => k !== key) }));
          return without.map((t) => (t.id === tab.id ? { ...t, fields: [...rest.slice(0, i), key, ...rest.slice(i)] } : t));
        }
        if (onTab) {
          const without = ts.map((t) => ({ ...t, fields: t.fields.filter((k) => k !== key) }));
          return without.map((t) => (String(t.id) === String(onTab.data.tabId) ? { ...t, fields: [...t.fields, key] } : t));
        }
        return ts;
      });
    },
  }), []);

  if (catalog.isPending) return <PageSpinner />;
  if (catalog.error) return <ErrorBox error={errorMessage(catalog.error)} />;
  const byKey = new Map(catalog.data.map((f) => [f.key, f]));
  const cur = tabs[Math.min(active, tabs.length - 1)];
  const free = catalog.data.filter((f) => !keys.has(f.key));
  const submit = () => save.mutate({
    id: row?.id,
    body: { ...basics, tabs: tabs.map((t) => ({ name: t.name.trim() || "Campos", fields: t.fields })) },
  });
  return (
    <div className="space-y-4">
      <ErrorBox error={save.error} />
      <BasicsFields value={basics} onChange={setBasics} defaultHint="Los campos personalizados nuevos se añaden a esta pantalla." />
      {warnings.size > 0 && (
        <div role="note" className="rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">
          <p className="mb-1 flex items-center gap-2 font-semibold"><AlertTriangle size={14} className="text-warning" />Faltan campos obligatorios en esta pantalla de crear</p>
          <ul className="ml-6 list-disc space-y-0.5">
            {[...warnings.entries()].map(([k, w]) => <li key={k}>«{w.label}» es obligatorio en {[...w.where].join(", ")}: no se exigirá al crear.</li>)}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-1 border-b-2 border-line" role="tablist" aria-label="Pestañas de la pantalla">
        {tabs.map((t, i) => (
          <TabDropZone key={t.id} tabId={t.id}>
            <button type="button" role="tab" aria-selected={i === active} onClick={() => setActive(i)}
                    className={cn("-mb-0.5 border-b-2 px-2 pb-1.5 pt-1 text-sm font-medium", i === active ? "border-brand text-brand" : "border-transparent text-fg-subtle hover:text-fg")}>
              {t.name || "Sin nombre"} <span className="text-xs text-fg-subtlest">({t.fields.length})</span>
            </button>
          </TabDropZone>
        ))}
        <Button size="sm" variant="subtle" className="mb-1" onClick={() => { setTabs([...tabs, { id: newTabId(), name: `Pestaña ${tabs.length + 1}`, fields: [] }]); setActive(tabs.length); }}><Plus size={14} />Pestaña</Button>
      </div>
      {cur && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <FieldShell label="Nombre de la pestaña" className="w-64">
              {(a11y) => <Input value={cur.name} onChange={(e) => setTabs(tabs.map((t) => (t.id === cur.id ? { ...t, name: e.target.value } : t)))} {...a11y} />}
            </FieldShell>
            {tabs.length > 1 && (
              <>
                <Button size="sm" variant="subtle" aria-label="Mover pestaña a la izquierda" disabled={active === 0} onClick={() => { const n = [...tabs]; [n[active - 1], n[active]] = [n[active], n[active - 1]]; setTabs(n); setActive(active - 1); }}><ArrowUp size={14} className="-rotate-90" /></Button>
                <Button size="sm" variant="subtle" aria-label="Mover pestaña a la derecha" disabled={active === tabs.length - 1} onClick={() => { const n = [...tabs]; [n[active + 1], n[active]] = [n[active], n[active + 1]]; setTabs(n); setActive(active + 1); }}><ArrowDown size={14} className="-rotate-90" /></Button>
                <Button size="sm" variant="subtle" onClick={() => {
                  // its fields go to the first remaining tab, nothing is lost
                  const rest = tabs.filter((t) => t.id !== cur.id);
                  rest[0] = { ...rest[0], fields: [...rest[0].fields, ...cur.fields] };
                  setTabs(rest); setActive(0);
                }}><Trash2 size={14} />Quitar pestaña</Button>
              </>
            )}
          </div>
          <TabDropZone tabId={cur.id} className="rounded-[3px] border border-dashed border-line p-2">
            {cur.fields.length ? (
              <ul className="space-y-1.5" aria-label={`Campos de «${cur.name}»`}>
                {cur.fields.map((k, i) => {
                  const f = byKey.get(k) ?? { key: k, label: k, system: true };
                  return (
                    <DraggableField key={k} field={f} tabId={cur.id} index={i} count={cur.fields.length} tabs={tabs}
                                    onMove={(to) => moveField(k, cur.id, to)}
                                    onMoveTab={(tid) => moveField(k, tid, Number.MAX_SAFE_INTEGER)}
                                    onRemove={() => setTabs(tabs.map((t) => ({ ...t, fields: t.fields.filter((x) => x !== k) })))} />
                  );
                })}
              </ul>
            ) : <p className="px-2 py-4 text-center text-sm text-fg-subtlest">Arrastra campos aquí o añádelos abajo.</p>}
          </TabDropZone>
          <div className="flex flex-wrap items-center gap-2">
            {free.length > 0 && (
              <Picker width={300} placeholder="Buscar campo" onSelect={(k) => setTabs(tabs.map((t) => (t.id === cur.id ? { ...t, fields: [...t.fields, k] } : t)))}
                      options={free.map((f) => ({ value: f.key, label: f.label, description: f.system ? "Sistema" : "Personalizado" }))}
                      trigger={<Button size="sm"><Plus size={14} />Añadir campo</Button>} />
            )}
            <span className="text-xs text-fg-subtle">«Resumen» y «Tipo» siempre aparecen al principio de las pantallas de crear y editar, aunque no estén aquí.</span>
          </div>
        </div>
      )}
      <EditorFooter onClose={onClose} onSave={submit} saving={save.isPending} disabled={!basics.name.trim() || !tabs.length} />
    </div>
  );
}

/* ------------------------------------------------------------------ screen schemes */

export function ScreenSchemes() {
  const appMeta = useMeta();
  const ops = appMeta.data?.screen_operations ?? [];
  return (
    <CollectionPage c={COLLECTIONS.ss} createLabel="Crear esquema de pantalla" width={720}
                    intro="Un esquema de pantalla elige la pantalla de cada operación: crear, editar y ver incidencias. Las que no se elijan usan la pantalla predeterminada del esquema."
                    emptyTitle="Sin esquemas de pantalla" emptyBody="Crea un esquema para usar pantallas distintas al crear, editar o ver."
                    softBody="Deja de estar disponible para los esquemas por tipo."
                    columns={[
                      { label: "Predeterminada", render: (r) => r.default_screen?.name ?? "—" },
                      ...ops.map((o) => ({ label: o.label, render: (r) => r[`${o.value}_screen`]?.name ?? <span className="text-fg-subtlest">La predeterminada</span> })),
                      { label: "Esquemas por tipo", render: (r) => <Usage items={r.issue_type_screen_schemes} label="Usado en" /> },
                    ]}
                    Editor={ScreenSchemeEditor} />
  );
}

function ScreenSchemeEditor({ row, onClose }) {
  const screens = useCollection(COLLECTIONS.screens);
  const appMeta = useMeta();
  const ops = appMeta.data?.screen_operations ?? [];
  const [basics, setBasics] = useState({ name: row?.name ?? "", description: row?.description ?? "", is_default: !!row?.is_default });
  const [def, setDef] = useState(row?.default_screen?.id ?? null);
  const [byOp, setByOp] = useState(() => Object.fromEntries(["create", "edit", "view"].map((o) => [o, row?.[`${o}_screen`]?.id ?? null])));
  const save = useSave(COLLECTIONS.ss, onClose);
  if (screens.isPending || appMeta.isPending) return <PageSpinner />;
  const options = (screens.data ?? []).map((s) => ({ value: s.id, label: s.name, description: s.is_default ? "Predeterminada" : s.description }));
  const defaultId = def ?? screens.data?.find((s) => s.is_default)?.id ?? null;
  const name = (id) => options.find((o) => o.value === id)?.label;
  return (
    <div className="space-y-4">
      <ErrorBox error={save.error} />
      <BasicsFields value={basics} onChange={setBasics} defaultHint="Lo reciben los esquemas por tipo nuevos." />
      <FieldShell label="Pantalla predeterminada" required description="Se usa en las operaciones sin pantalla propia.">
        {(a11y) => <Picker value={defaultId} width={320} onSelect={setDef} options={options}
                           trigger={<button type="button" className={SEL} {...a11y}>{name(defaultId) ?? <span className="text-fg-subtlest">Elegir pantalla</span>}</button>} />}
      </FieldShell>
      <div className="grid gap-4 sm:grid-cols-3">
        {ops.map((o) => (
          <FieldShell key={o.value} label={o.label} description={o.description || undefined}>
            {(a11y) => <Picker value={byOp[o.value] ?? 0} width={300} onSelect={(v) => setByOp({ ...byOp, [o.value]: v || null })}
                               options={[{ value: 0, label: "La predeterminada" }, ...options]}
                               trigger={<button type="button" className={SEL} {...a11y}>{name(byOp[o.value]) ?? <span className="text-fg-subtlest">La predeterminada</span>}</button>} />}
          </FieldShell>
        ))}
      </div>
      <EditorFooter onClose={onClose} saving={save.isPending} disabled={!basics.name.trim() || !defaultId}
                    onSave={() => save.mutate({ id: row?.id, body: { ...basics, default_screen_id: defaultId, create_screen_id: byOp.create, edit_screen_id: byOp.edit, view_screen_id: byOp.view } })} />
    </div>
  );
}

/* ------------------------------------------------------------------ issue type screen schemes */

export function IssueTypeScreenSchemes() {
  return (
    <CollectionPage c={COLLECTIONS.itss} createLabel="Crear esquema por tipo" width={760}
                    intro="Un esquema de pantalla por tipo asocia cada tipo de incidencia con un esquema de pantalla. Los proyectos usan uno (Configuración del proyecto › Campos)."
                    emptyTitle="Sin esquemas por tipo" emptyBody="Crea uno para que cada tipo use sus propias pantallas."
                    softBody="Deja de estar disponible para los proyectos."
                    columns={[
                      { label: "Esquema de pantalla", render: (r) => r.default_screen_scheme?.name ?? "—" },
                      { label: "Por tipo", render: (r) => (r.entries?.length ? r.entries.map((e) => `${e.issue_type.name} → ${e.screen_scheme.name}`).join(" · ") : "—") },
                      { label: "Proyectos", render: (r) => <Usage items={r.projects} label="Usado en" /> },
                    ]}
                    Editor={IssueTypeScreenSchemeEditor} />
  );
}

function IssueTypeScreenSchemeEditor({ row, onClose }) {
  const schemes = useCollection(COLLECTIONS.ss);
  const [basics, setBasics] = useState({ name: row?.name ?? "", description: row?.description ?? "", is_default: !!row?.is_default });
  const [def, setDef] = useState(row?.default_screen_scheme?.id ?? null);
  const [entries, setEntries] = useState((row?.entries ?? []).map((e) => ({ issue_type_id: e.issue_type.id, value: e.screen_scheme.id })));
  const save = useSave(COLLECTIONS.itss, onClose);
  if (schemes.isPending) return <PageSpinner />;
  const options = (schemes.data ?? []).map((s) => ({ value: s.id, label: s.name, description: s.is_default ? "Predeterminado" : s.description }));
  const defaultId = def ?? schemes.data?.find((s) => s.is_default)?.id ?? null;
  return (
    <div className="space-y-4">
      <ErrorBox error={save.error} />
      <BasicsFields value={basics} onChange={setBasics} defaultHint="Lo reciben los proyectos nuevos." />
      <div>
        <h3 className="mb-2 text-sm font-semibold">Tipo de incidencia → esquema de pantalla</h3>
        <TypeMapping entries={entries} onChange={setEntries} options={options} defaultLabel="Esquema de pantalla" emptyOption="Elegir esquema"
                     defaultValue={defaultId} onDefault={setDef} />
      </div>
      {row?.projects?.length > 0 && <p className="text-xs text-fg-subtle">Lo usan: {row.projects.map((p) => p.key).join(", ")}. Los cambios se aplican al momento.</p>}
      <EditorFooter onClose={onClose} saving={save.isPending} disabled={!basics.name.trim() || !defaultId || entries.some((e) => !e.value)}
                    onSave={() => save.mutate({ id: row?.id, body: { ...basics, default_screen_scheme_id: defaultId, entries: entries.map((e) => ({ issue_type_id: e.issue_type_id, screen_scheme_id: e.value })) } })} />
    </div>
  );
}

