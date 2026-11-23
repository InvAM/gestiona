"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CheckCircle2, ClipboardList, Copy, ExternalLink, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageSpinner } from "@/components/ui/button";
import { Badge, Checkbox, EmptyState, Field, Input, Modal, Textarea, Toggle } from "@/components/ui/primitives";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useFieldRules, useMeta } from "@/lib/api/hooks";
import { cfKey, fieldErrors, isEmptyValue } from "@/lib/fields";
import { allKeys, createRequired, fieldCatalog, fieldLabel, screenFor } from "@/lib/screens";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";
import { cn } from "@/lib/utils";

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

const formUrl = (slug) => `${typeof window !== "undefined" ? window.location.origin : ""}/f/${slug}`;

/* ------------------------------------------------------------------ management */

export function ProjectForms({ meta }) {
  const qc = useQueryClient();
  const key = meta.project.key;
  const appMeta = useMeta();
  const forms = useQuery({ queryKey: ["forms", key], queryFn: () => unwrap(api.GET("/api/v1/projects/{key}/forms", { params: { path: { key } } })) });
  const [editing, setEditing] = useState(null);
  const [view, setView] = useState("active");
  const deleted = useDeletedList(`/api/v1/projects/${key}/forms`, "forms", view === "deleted");
  const actions = useCatalogActions({ path: "/api/v1/forms", queryKey: "forms", softBody: "El enlace dejará de funcionar. Las incidencias creadas se conservan." });
  const refresh = () => qc.invalidateQueries({ queryKey: ["forms", key] });
  const copy = async (slug) => { await navigator.clipboard.writeText(formUrl(slug)); toast.success("Enlace copiado"); };
  if (forms.isPending) return <PageSpinner />;
  return (
    <div className="max-w-[920px]">
      <p className="mb-3 text-sm text-fg-subtle">Comparte un formulario para que cualquiera pida trabajo sin conocer el proyecto: cada envío crea una incidencia con los campos que elijas.</p>
      <div className="flex items-end justify-between gap-3">
        <CatalogTabs value={view} onChange={setView} className="flex-1" />
        {view === "active" && <Button variant="primary" onClick={() => setEditing("new")}><Plus size={16} />Crear formulario</Button>}
      </div>
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} allowPurge={false} empty="No hay formularios eliminados." />
      ) : !forms.data?.length ? (
        <EmptyState icon={<ClipboardList size={40} />} title="Sin formularios" body="Ejemplos: solicitudes de soporte, pedidos de diseño, reportes de errores de otras áreas." action={<Button onClick={() => setEditing("new")}>Crear formulario</Button>} />
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Formulario</th><th>Crea</th><th>Acceso</th><th className="text-right">Envíos</th><th className="w-40" /></tr></thead>
          <tbody>{forms.data.map((f) => (
            <tr key={f.id} className={cn("border-b border-line", !f.is_active && "opacity-60")}>
              <td className="py-2"><b>{f.name}</b>{!f.is_active && <Badge className="ml-2">Inactivo</Badge>}</td>
              <td className="py-2">{f.issue_type.name}</td>
              <td className="py-2 text-fg-subtle">{choiceLabel(appMeta.data?.form_access, f.access)}</td>
              <td className="py-2 text-right">{f.submission_count}</td>
              <td className="py-2 text-right">
                <Button size="icon" variant="subtle" aria-label="Copiar enlace" onClick={() => copy(f.slug)}><Copy size={14} /></Button>
                <Button size="icon" variant="subtle" aria-label="Abrir" asChild><Link href={`/f/${f.slug}`} target="_blank"><ExternalLink size={14} /></Link></Button>
                <Button size="icon" variant="subtle" aria-label="Editar" onClick={() => setEditing(f)}><Pencil size={14} /></Button>
                <Button size="icon" variant="subtle" aria-label="Eliminar" onClick={() => actions.askDelete(f)}><Trash2 size={14} /></Button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <Modal open={!!editing} onOpenChange={(o) => !o && setEditing(null)} title={editing === "new" ? "Nuevo formulario" : "Editar formulario"} width={760}>
        {editing && <FormEditor key={editing === "new" ? "new" : editing.id} meta={meta} form={editing === "new" ? undefined : editing} onDone={() => { setEditing(null); refresh(); }} />}
      </Modal>
      {actions.dialog}
    </div>
  );
}

function FormEditor(props) {
  const appMeta = useMeta();
  const rules = useFieldRules(props.meta.project.key);
  if (appMeta.error) return <p className="text-sm text-danger">No se pudo cargar la configuración: {errorMessage(appMeta.error)}</p>;
  if (!appMeta.data || rules.isPending) return <PageSpinner />;
  return <FormEditorBody {...props} appMeta={appMeta.data} fieldRules={rules.data} builtin={appMeta.data.form_builtin_fields} accessChoices={appMeta.data.form_access} />;
}

/*
 * The form creates issues of one type, so it follows that type's create screen: only fields of
 * the screen can be asked, and the type's required fields (field configuration) are forced
 * into the form as required. The backend rejects the same cases with 422 `fields`.
 */
function FormEditorBody({ meta, form, onDone, builtin, accessChoices, appMeta, fieldRules }) {
  const types = meta.issue_types.filter((t) => t.level !== -1);
  const [name, setName] = useState(form?.name ?? "");
  const [description, setDescription] = useState(form?.description ?? "");
  const [typeId, setTypeId] = useState(form?.issue_type.id ?? types.find((t) => t.id === meta.default_issue_type_id)?.id ?? types.find((t) => t.level === 0)?.id ?? types[0]?.id);
  const [fields, setFields] = useState(form?.fields ?? builtin.filter((b) => b.always_required || b.value === "description")
    .map((b) => ({ field: b.value, label: b.label, required: !!b.always_required, help: "" })));
  const [labels, setLabels] = useState((form?.default_labels ?? []).join(", "));
  const [access, setAccess] = useState(form?.access ?? "organization");
  const [active, setActive] = useState(form?.is_active ?? true);
  const [message, setMessage] = useState(form?.success_message ?? "");
  const [serverErrors, setServerErrors] = useState({});
  const [general, setGeneral] = useState(null);

  const type = meta.issue_types.find((t) => t.id === typeId);
  const catalog = fieldCatalog(fieldRules, meta, appMeta);
  const screen = screenFor(fieldRules, meta, appMeta, typeId, "create");
  const onScreen = allKeys(screen);
  onScreen.add("summary");
  const formable = new Map([...builtin.map((b) => [b.value, b.label]), ...meta.custom_fields.map((c) => [cfKey(c.id), c.name])]);
  const typeRequired = new Set(["summary", ...[...createRequired(fieldRules, meta, typeId)].filter((k) => k !== "issue_type")]);
  for (const b of builtin) if (b.always_required) typeRequired.add(b.value);
  const unformable = [...typeRequired].filter((k) => !formable.has(k));
  // the type's required fields are always in the form (appended if missing) and required
  const effective = [
    ...fields.map((f) => (typeRequired.has(f.field) ? { ...f, required: true, forced: true } : f)),
    ...[...typeRequired].filter((k) => formable.has(k) && !fields.some((f) => f.field === k))
      .map((k) => ({ field: k, label: formable.get(k), required: true, help: "", forced: true, added: true })),
  ];
  const rowError = (f) => serverErrors[f.field] ?? (screen.resolved && !onScreen.has(f.field)
    ? `No está en la pantalla de crear de «${type?.name ?? ""}»: quítalo o pide que lo añadan` : null);
  const labelsOff = screen.resolved && !!labels.trim() && !onScreen.has("labels")
    ? `«${fieldLabel(catalog, "labels")}» no está en la pantalla de crear de «${type?.name ?? ""}»: no se pueden poner etiquetas automáticas` : null;
  const blocking = effective.some((f) => rowError(f) && !serverErrors[f.field]) || unformable.length > 0 || !!labelsOff;
  const available = [...formable.entries()].filter(([v]) => !effective.some((f) => f.field === v) && (!screen.resolved || onScreen.has(v)));
  const body = () => ({
    name, description, issue_type_id: typeId,
    fields: effective.map(({ field, label, required, help }) => ({ field, label, required, help })),
    default_labels: labels.split(",").map((x) => x.trim()).filter(Boolean), access, is_active: active, success_message: message,
  });
  const save = useMutation({
    mutationFn: () => form
      ? unwrap(api.PUT("/api/v1/forms/{form_id}", { params: { path: { form_id: form.id } }, body: body() }))
      : unwrap(api.POST("/api/v1/projects/{key}/forms", { params: { path: { key: meta.project.key } }, body: body() })),
    onSuccess: () => { toast.success("Formulario guardado"); onDone(); },
    onError: (e) => {
      const fe = fieldErrors(e);
      setServerErrors(fe);
      const off = Object.keys(fe).filter((k) => !effective.some((f) => f.field === k));
      setGeneral(off.length ? `${errorMessage(e)} (${off.map((k) => fieldLabel(catalog, k)).join(", ")})` : Object.keys(fe).length ? null : errorMessage(e));
    },
  });
  const commit = (next) => { setFields(next); setServerErrors({}); setGeneral(null); };
  const idx = (f) => fields.findIndex((x) => x.field === f.field);
  const upd = (f, patch) => {
    const i = idx(f);
    if (i < 0) commit([...fields, { field: f.field, label: f.label, required: f.required, help: f.help, ...patch }]);
    else commit(fields.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  };
  const move = (from, to) => {
    const list = effective.map(({ field, label, required, help }) => ({ field, label, required, help }));
    [list[from], list[to]] = [list[to], list[from]];
    commit(list);
  };
  return (
    <div className="space-y-4">
      {general && <p role="alert" className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{general}</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nombre" required><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Crea una incidencia de tipo">
          <select className={sel} value={typeId} onChange={(e) => { setTypeId(Number(e.target.value)); setServerErrors({}); setGeneral(null); }}>{types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        </Field>
        <Field label="Instrucciones (se muestran arriba del formulario)" className="sm:col-span-2"><Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      </div>
      <div>
        <h3 className="mb-1 text-sm font-semibold">Campos</h3>
        <p className="mb-2 text-xs text-fg-subtle">Solo se pueden pedir campos de la pantalla de crear de «{type?.name}». Los obligatorios de ese tipo se incluyen siempre y no se pueden quitar.</p>
        {unformable.length > 0 && (
          <p role="alert" className="mb-2 rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">
            «{type?.name}» exige {unformable.map((k) => `«${fieldLabel(catalog, k)}»`).join(", ")}, que no se puede pedir en un formulario. Elige otro tipo o cambia su configuración de campos.
          </p>
        )}
        <div className="space-y-2">{effective.map((f, i) => {
          const err = rowError(f);
          const errId = `form-field-${f.field}-error`;
          return (
            <div key={f.field} className={cn("rounded-[3px] border p-2", err ? "border-danger" : "border-line")}>
              <div className="grid grid-cols-[1fr_1fr_auto_auto] items-center gap-2">
                <Input value={f.label} onChange={(e) => upd(f, { label: e.target.value })} aria-label={`Etiqueta de ${fieldLabel(catalog, f.field)}`}
                       aria-invalid={err ? true : undefined} aria-describedby={err ? errId : undefined} />
                <Input value={f.help} placeholder="Ayuda (opcional)" aria-label={`Ayuda de ${fieldLabel(catalog, f.field)}`} onChange={(e) => upd(f, { help: e.target.value })} />
                <Checkbox checked={f.required} disabled={!!f.forced} onChange={(v) => upd(f, { required: v })} label="Obligatorio" />
                <div className="flex">
                  <Button size="icon" variant="subtle" aria-label="Subir" disabled={i === 0} onClick={() => move(i, i - 1)}><ArrowUp size={14} /></Button>
                  <Button size="icon" variant="subtle" aria-label="Bajar" disabled={i === effective.length - 1} onClick={() => move(i, i + 1)}><ArrowDown size={14} /></Button>
                  <Button size="icon" variant="subtle" aria-label="Quitar" disabled={!!f.forced} onClick={() => commit(fields.filter((x) => x.field !== f.field))}><Trash2 size={14} /></Button>
                </div>
              </div>
              {(f.forced || err) && (
                <div className="mt-1 flex flex-wrap gap-2 text-xs">
                  {f.forced && <span className="text-fg-subtle">{f.added ? "Añadido: " : ""}obligatorio en «{type?.name}»</span>}
                  {err && <span id={errId} role="alert" className="text-danger">{err}</span>}
                </div>
              )}
            </div>
          );
        })}</div>
        {available.length > 0 && (
          <select className={cn(sel, "mt-2 w-64")} value="" aria-label="Agregar campo" onChange={(e) => { const opt = available.find(([v]) => v === e.target.value); if (opt) commit([...fields, { field: opt[0], label: opt[1], required: false, help: "" }]); }}>
            <option value="">+ Agregar campo…</option>{available.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Etiquetas automáticas (separadas por coma)" error={serverErrors.labels ?? labelsOff}><Input value={labels} onChange={(e) => setLabels(e.target.value)} placeholder="formulario, soporte" /></Field>
        <Field label="Quién puede enviarlo">
          <select className={sel} value={access} onChange={(e) => setAccess(e.target.value)}>
            {accessChoices.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
          </select>
        </Field>
        <Field label="Mensaje al enviar" className="sm:col-span-2"><Input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="¡Gracias! Recibimos tu solicitud." /></Field>
      </div>
      <div className="flex items-center gap-3 border-t border-line pt-3">
        <span className="flex items-center gap-2 text-sm"><Toggle label="Activo" checked={active} onChange={setActive} />Activo</span>
        {blocking && <span className="text-xs text-danger">Corrige los campos marcados para guardar.</span>}
        <div className="ml-auto flex gap-2"><Button variant="subtle" onClick={onDone}>Cancelar</Button><Button variant="primary" disabled={!name.trim() || blocking} loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button></div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ filling in */

export function PublicForm({ slug }) {
  const form = useQuery({ queryKey: ["public-form", slug], queryFn: () => unwrap(api.GET("/api/v1/f/{slug}", { params: { path: { slug } } })), retry: false });
  const [values, setValues] = useState({});
  const [done, setDone] = useState(null);
  const [errors, setErrors] = useState({});
  const [general, setGeneral] = useState(null);
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/f/{slug}", { params: { path: { slug } }, body: { values } })),
    onSuccess: (d) => { setDone(d); setErrors({}); setGeneral(null); },
    onError: (e) => {
      const fe = fieldErrors(e);
      setErrors(fe);
      // `form_outdated`: the project's configuration changed and the form can't be sent
      setGeneral(Object.keys(fe).length ? null : errorMessage(e));
    },
  });
  if (form.isPending) return <PageSpinner />;
  if (form.error) return <EmptyState title="Formulario no disponible" body={form.error instanceof ApiError ? form.error.message : "No se pudo cargar"} />;
  const f = form.data;
  const set = (k, v) => {
    setValues({ ...values, [k]: v });
    if (errors[k]) { const n = { ...errors }; delete n[k]; setErrors(n); }
  };
  const send = () => {
    const errs = {};
    for (const fd of f.fields) if (fd.required && isEmptyValue(values[fd.field])) errs[fd.field] = `«${fd.label}» es obligatorio`;
    setErrors(errs);
    setGeneral(null);
    if (Object.keys(errs).length) {
      document.getElementById(`pf-${Object.keys(errs)[0]}`)?.focus();
      return;
    }
    submit.mutate();
  };
  if (done) {
    return (
      <div className="mx-auto mt-16 max-w-[560px] rounded-[3px] border border-line p-8 text-center">
        <CheckCircle2 size={40} className="mx-auto text-success" />
        <h1 className="mt-3 text-xl font-medium">{done.message}</h1>
        {done.key && <p className="mt-2 text-sm">Creamos <Link className="text-link hover:underline" href={`/browse/${done.key}`}>{done.key}</Link>. Te avisaremos de los cambios.</p>}
        {!done.key && <p className="mt-2 text-sm text-fg-subtle">Te avisaremos por correo cuando haya novedades.</p>}
        <Button className="mt-6" onClick={() => { setDone(null); setValues({}); }}>Enviar otra solicitud</Button>
      </div>
    );
  }
  return (
    <form noValidate className="mx-auto my-10 w-full max-w-[640px] space-y-5 rounded-[3px] border border-line p-8" onSubmit={(e) => { e.preventDefault(); send(); }}>
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">{f.project_name}</div>
        <h1 className="mt-1 text-2xl font-medium">{f.name}</h1>
        {f.description && <p className="mt-2 whitespace-pre-wrap text-sm text-fg-subtle">{f.description}</p>}
        <p className="mt-3 text-xs text-fg-subtle">Los campos obligatorios están marcados con un asterisco <span className="text-danger">*</span></p>
      </div>
      {general && <p role="alert" className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{general}</p>}
      {f.fields.map((fd) => {
        const v = values[fd.field];
        const err = errors[fd.field];
        const id = `pf-${fd.field}`;
        const a11y = {
          id, "aria-invalid": err ? true : undefined, "aria-required": fd.required ? true : undefined,
          "aria-describedby": [err ? `${id}-error` : null, fd.help ? `${id}-help` : null].filter(Boolean).join(" ") || undefined,
        };
        let control;
        if (fd.kind === "description" || fd.kind === "cf:textarea") control = <Textarea rows={5} value={String(v ?? "")} onChange={(e) => set(fd.field, e.target.value)} {...a11y} />;
        else if (fd.kind === "due_date" || fd.kind === "cf:date") control = <Input type="date" className="w-48" value={String(v ?? "")} invalid={!!err} onChange={(e) => set(fd.field, e.target.value)} {...a11y} />;
        else if (fd.kind === "cf:number") control = <Input type="number" className="w-48" value={String(v ?? "")} invalid={!!err} onChange={(e) => set(fd.field, e.target.value === "" ? null : Number(e.target.value))} {...a11y} />;
        else if (fd.kind === "priority" || fd.kind === "cf:select") control = (
          <select className={cn(sel, "w-64", err && "border-danger")} value={String(v ?? "")} onChange={(e) => set(fd.field, e.target.value || null)} {...a11y}>
            <option value="">Elegir…</option>{(fd.options ?? []).filter((o) => !o.deleted).map((o) => <option key={String(o.id)} value={String(o.id)}>{String(o.value)}</option>)}
          </select>
        );
        else if (fd.kind === "components" || fd.kind === "cf:multiselect" || fd.kind === "cf:checkbox") {
          const arr = v ?? [];
          control = <div role="group" aria-labelledby={`${id}-label`} {...a11y} className="flex flex-wrap gap-x-4 gap-y-1">{(fd.options ?? []).filter((o) => !o.deleted).map((o) => {
            const oid = fd.kind === "components" ? Number(o.id) : String(o.id);
            return <Checkbox key={String(o.id)} label={String(o.value)} checked={arr.includes(oid)} onChange={(on) => set(fd.field, on ? [...arr, oid] : arr.filter((x) => x !== oid))} />;
          })}</div>;
        } else if (fd.kind === "labels" || fd.kind === "cf:labels") control = <Input value={(v ?? []).join(", ")} placeholder="separadas por coma" invalid={!!err} onChange={(e) => set(fd.field, e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} {...a11y} />;
        else control = <Input value={String(v ?? "")} maxLength={fd.kind === "summary" ? 255 : undefined} invalid={!!err} onChange={(e) => set(fd.field, e.target.value)} {...a11y} />;
        return (
          <div key={fd.field}>
            <label htmlFor={id} id={`${id}-label`} className="mb-1 block text-xs font-semibold text-fg-subtle">
              {fd.label}{fd.required && <><span className="ml-0.5 text-danger" aria-hidden="true">*</span><span className="sr-only"> (obligatorio)</span></>}
            </label>
            {control}
            {err && <span id={`${id}-error`} role="alert" className="mt-1 block text-xs text-danger">{err}</span>}
            {fd.help && <span id={`${id}-help`} className="mt-1 block text-xs text-fg-subtlest">{fd.help}</span>}
          </div>
        );
      })}
      <div className="flex justify-end"><Button type="submit" variant="primary" loading={submit.isPending}>Enviar</Button></div>
    </form>
  );
}
