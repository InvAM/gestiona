"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CheckCircle2, MinusCircle, Pencil, Plus, Trash2, XCircle, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { UserPicker } from "@/components/issue/pickers";
import { useApp } from "@/components/shell/app-context";
import { Button, PageSpinner } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Avatar, Badge, Checkbox, EmptyState, Field, Input, Lozenge, Modal, Tabs, Textarea, Toggle } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useFieldRules, useMeta, useProjectMeta } from "@/lib/api/hooks";
import { fieldCatalog, fieldLabel, hiddenKeys, quickCreateMissing, requiredKeys } from "@/lib/screens";
import { CatalogTabs, DeletedList, useCatalogActions, useDeletedList } from "@/components/settings/catalog";
import { cn, fmtRelative } from "@/lib/utils";

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

function useStatuses(projectKey) {
  const meta = useQuery({
    queryKey: ["project-meta", projectKey], enabled: !!projectKey,
    queryFn: () => unwrap(api.GET("/api/v1/projects/{key}/meta", { params: { path: { key: projectKey } } })),
  });
  const all = useQuery({ queryKey: ["statuses"], queryFn: () => unwrap(api.GET("/api/v1/statuses")), enabled: !projectKey });
  return projectKey ? meta.data?.statuses : all.data;
}

// Replace every `{{param.x}}` token of a template draft with the chosen values.
function fillTemplate(obj, values) {
  if (typeof obj === "string") return Object.entries(values).reduce((acc, [token, v]) => acc.split(token).join(v), obj);
  if (Array.isArray(obj)) return obj.map((x) => fillTemplate(x, values));
  if (obj && typeof obj === "object") return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, fillTemplate(v, values)]));
  return obj;
}

/* ------------------------------------------------------------------ list */

export function AutomationRules({ projectKey }) {
  const [tab, setTab] = useState("rules");
  return (
    <div className="max-w-[980px]">
      <p className="mb-4 text-sm text-fg-subtle">
        Las reglas hacen el trabajo repetitivo: <b>cuando</b> pasa algo, <b>si</b> se cumplen las condiciones, <b>entonces</b> ejecutan acciones como el usuario «Automatización».
        {!projectKey && " Las reglas globales aplican a todos los proyectos."}
      </p>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "rules", label: "Reglas" }, { value: "log", label: "Registro de auditoría" }]} />
      <div className="mt-4">{tab === "rules" ? <RuleList projectKey={projectKey} /> : <AuditLog projectKey={projectKey} />}</div>
    </div>
  );
}

function RuleList({ projectKey }) {
  const qc = useQueryClient();
  const meta = useMeta(projectKey);
  const rules = useQuery({ queryKey: ["automation", projectKey ?? ""], queryFn: () => unwrap(api.GET("/api/v1/automation/rules", { params: { query: { project: projectKey } } })) });
  const [editing, setEditing] = useState(null);
  const [picking, setPicking] = useState(false);
  const [view, setView] = useState("active");
  const scope = projectKey ? { project: projectKey } : {};
  const deleted = useDeletedList("/api/v1/automation/rules", "automation", view === "deleted", scope);
  const actions = useCatalogActions({ path: "/api/v1/automation/rules", queryKey: "automation", softBody: "Deja de ejecutarse; su registro de auditoría se conserva." });
  const refresh = () => qc.invalidateQueries({ queryKey: ["automation", projectKey ?? ""] });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }) => unwrap(api.POST("/api/v1/automation/rules/{rule_id}/enabled", { params: { path: { rule_id: id } }, body: { enabled } })),
    onSuccess: refresh, onError: (e) => toast.error(errorMessage(e)),
  });
  if (rules.isPending) return <PageSpinner />;
  return (
    <div>
      <div className="flex items-end justify-between gap-3">
        <CatalogTabs value={view} onChange={setView} className="flex-1" />
        {view === "active" && <Button variant="primary" onClick={() => setPicking(true)}><Plus size={16} />Crear regla</Button>}
      </div>
      {view === "deleted" ? (
        <DeletedList query={deleted} actions={actions} allowPurge={false} empty="No hay reglas eliminadas. Una regla eliminada deja de ejecutarse; su registro se conserva." />
      ) : !rules.data?.length ? (
        <EmptyState icon={<Zap size={40} />} title="Todavía no hay reglas" body="Empieza con una plantilla o crea una regla en blanco." action={<Button onClick={() => setPicking(true)}>Ver plantillas</Button>} />
      ) : (
        <table className="mt-3 w-full text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
            <th className="w-12 py-2">Activa</th><th className="py-2">Regla</th><th className="py-2">Disparador</th><th className="py-2">Última ejecución</th><th className="py-2 text-right">Ejecuciones</th><th className="w-20" /></tr></thead>
          <tbody>{rules.data.map((r) => (
            <tr key={r.id} className={cn("border-b border-line", !r.enabled && "opacity-60")}>
              <td className="py-2"><Toggle label="Activa" checked={r.enabled} onChange={(v) => toggle.mutate({ id: r.id, enabled: v })} /></td>
              <td className="py-2"><button className="text-left font-medium hover:underline" onClick={() => setEditing({ rule: r, draft: toDraft(r) })}>{r.name}</button>
                {r.description && <div className="text-xs text-fg-subtle">{r.description}</div>}</td>
              <td className="py-2 text-fg-subtle">{r.trigger_display}{r.next_run_at && <div className="text-xs">Próxima: {fmtRelative(r.next_run_at)}</div>}</td>
              <td className="py-2"><span className="flex items-center gap-1.5"><StatusIcon status={r.last_status} />{r.last_run_at ? fmtRelative(r.last_run_at) : <span className="text-fg-subtlest">Nunca</span>}</span></td>
              <td className="py-2 text-right">{r.run_count}</td>
              <td className="py-2 text-right">
                <Button size="icon" variant="subtle" aria-label="Editar" onClick={() => setEditing({ rule: r, draft: toDraft(r) })}><Pencil size={14} /></Button>
                <Button size="icon" variant="subtle" aria-label="Eliminar" onClick={() => actions.askDelete(r)}><Trash2 size={14} /></Button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <Modal open={picking} onOpenChange={setPicking} title="Crear regla" width={560}>
        {picking && <TemplatePicker templates={meta.data?.automation.templates} loading={meta.isPending}
                                    onPick={(draft) => { setPicking(false); setEditing({ draft }); }}
                                    onBlank={() => { setPicking(false); setEditing({ draft: { name: "", trigger: meta.data?.automation.triggers[0]?.value, actions: [] } }); }} />}
      </Modal>
      <Modal open={!!editing} onOpenChange={(o) => !o && setEditing(null)} title={editing?.rule ? `Editar regla` : "Nueva regla"} width={860}>
        {editing && <RuleEditor key={editing.rule?.id ?? "new"} projectKey={projectKey} rule={editing.rule} initial={editing.draft} onSaved={() => { refresh(); setEditing(null); }} onCancel={() => setEditing(null)} />}
      </Modal>
      {actions.dialog}
    </div>
  );
}

function TemplatePicker({ templates, loading, onPick, onBlank }) {
  const [chosen, setChosen] = useState(null);
  const [values, setValues] = useState({});
  if (loading) return <PageSpinner />;
  if (chosen) {
    const ready = chosen.params.every((p) => values[p.key] != null);
    const build = () => {
      const tokens = Object.fromEntries(chosen.params.map((p) => [p.token, p.options.find((o) => o.id === values[p.key])?.jql_value ?? ""]));
      onPick(fillTemplate(chosen.draft_template, tokens));
    };
    return (
      <div className="space-y-4">
        <p className="text-sm"><b>{chosen.name}</b><span className="block text-fg-subtle">{chosen.description}</span></p>
        {chosen.params.map((p) => (
          <Field key={p.key} label={p.label} required>
            {p.options.length ? (
              <Picker value={values[p.key] ?? null} width={300} options={p.options.map((o) => ({ value: o.id, label: o.name }))} onSelect={(v) => setValues({ ...values, [p.key]: v })}
                      trigger={<button className={sel}>{p.options.find((o) => o.id === values[p.key])?.name ?? <span className="text-fg-subtlest">Elegir…</span>}</button>} />
            ) : <p className="text-sm text-danger">No hay opciones disponibles en este proyecto.</p>}
          </Field>
        ))}
        <div className="flex justify-end gap-2">
          <Button variant="subtle" onClick={() => setChosen(null)}>Atrás</Button>
          <Button variant="primary" disabled={!ready} onClick={build}>Usar plantilla</Button>
        </div>
      </div>
    );
  }
  const pick = (t) => {
    // Parametrised templates (e.g. which issue type) let the user confirm the suggested value.
    if (t.params.length) {
      setValues(Object.fromEntries(t.params.map((p) => [p.key, p.value])));
      setChosen(t);
    } else {
      onPick(t.draft);
    }
  };
  return (
    <div className="space-y-2">
      {(templates ?? []).map((t) => {
        const usable = t.ready || t.params.every((p) => p.options.length);
        return (
          <button key={t.key} disabled={!usable} className="flex w-full items-start gap-3 rounded-[3px] border border-line p-3 text-left text-sm hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
                  onClick={() => pick(t)}>
            <Zap size={16} className="mt-0.5 shrink-0 text-discovery" />
            <span><span className="block">{t.name}</span>{t.description && <span className="block text-xs text-fg-subtle">{usable ? t.description : "No aplica: el proyecto no tiene un tipo compatible."}</span>}</span>
          </button>
        );
      })}
      <button className="flex w-full items-center gap-3 rounded-[3px] border border-dashed border-line-strong p-3 text-left text-sm hover:bg-bg-hover"
              onClick={onBlank}><Plus size={16} />Regla en blanco</button>
    </div>
  );
}

function toDraft(r) {
  return { name: r.name, description: r.description, enabled: r.enabled, trigger: r.trigger, trigger_config: r.trigger_config, conditions: r.conditions, actions: r.actions, allow_rule_triggers: r.allow_rule_triggers };
}

function StatusIcon({ status }) {
  if (status === "success") return <CheckCircle2 size={14} className="text-success" />;
  if (status === "failure") return <XCircle size={14} className="text-danger" />;
  if (status === "no_match") return <MinusCircle size={14} className="text-fg-subtlest" />;
  return null;
}

function AuditLog({ projectKey }) {
  const meta = useMeta();
  const logs = useQuery({ queryKey: ["automation-log", projectKey ?? ""], queryFn: () => unwrap(api.GET("/api/v1/automation/logs", { params: { query: { project: projectKey, limit: 200 } } })), refetchInterval: 15000 });
  if (logs.isPending) return <PageSpinner />;
  if (!logs.data?.length) return <EmptyState title="Sin ejecuciones todavía" body="Aquí verás cada vez que una regla se ejecute, con su resultado." />;
  return (
    <table className="w-full text-sm">
      <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Cuándo</th><th>Regla</th><th>Incidencia</th><th>Resultado</th><th>Detalle</th></tr></thead>
      <tbody>{logs.data.map((l) => (
        <tr key={l.id} className="border-b border-line align-top">
          <td className="whitespace-nowrap py-2 text-fg-subtle">{fmtRelative(l.created_at)}</td>
          <td className="py-2">{l.rule_name}</td>
          <td className="py-2">{l.issue_key ? <a className="text-link hover:underline" href={`/browse/${l.issue_key}`}>{l.issue_key}</a> : "—"}</td>
          <td className="py-2"><span className="flex items-center gap-1.5"><StatusIcon status={l.status} />{choiceLabel(meta.data?.automation.log_statuses, l.status)}</span></td>
          <td className="py-2 text-xs text-fg-subtle">{l.message || l.actions_done.join(" · ")}<span className="ml-1 text-fg-subtlest">({l.duration_ms} ms)</span></td>
        </tr>
      ))}</tbody>
    </table>
  );
}

/* ------------------------------------------------------------------ editor */

function RuleEditor(props) {
  const meta = useMeta();
  if (meta.error) return <p className="text-sm text-danger">No se pudo cargar la configuración: {errorMessage(meta.error)}</p>;
  if (!meta.data) return <PageSpinner />;
  return <RuleEditorBody {...props} auto={meta.data.automation} />;
}

function RuleEditorBody({ projectKey, rule, initial, onSaved, onCancel, auto }) {
  const { me } = useApp();
  const statuses = useStatuses(projectKey) ?? [];
  const priorities = useQuery({ queryKey: ["priorities"], queryFn: () => unwrap(api.GET("/api/v1/priorities")) });
  const [d, setD] = useState({ enabled: true, trigger_config: {}, conditions: [], allow_rule_triggers: false, description: "", ...initial });
  const cfg = d.trigger_config ?? {};
  const setCfg = (patch) => setD({ ...d, trigger_config: { ...cfg, ...patch } });
  const conditions = d.conditions ?? [];
  const actions = d.actions;
  const setActions = (a) => setD({ ...d, actions: a });
  const setConditions = (c) => setD({ ...d, conditions: c });

  const save = useMutation({
    mutationFn: () => rule
      ? unwrap(api.PUT("/api/v1/automation/rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body: d }))
      : unwrap(api.POST("/api/v1/automation/rules", { params: { query: { project: projectKey } }, body: d })),
    onSuccess: () => { toast.success("Regla guardada"); onSaved(); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const statusMulti = (key, empty) => {
    const val = cfg[key] ?? [];
    return (
      <Picker multiple value={val} width={260} options={statuses.map((s) => ({ value: s.id, label: s.name }))}
              onSelect={(v) => setCfg({ [key]: val.includes(v) ? val.filter((x) => x !== v) : [...val, v] })}
              trigger={<button className={cn(sel, "h-auto min-h-8 flex-wrap py-1")}>{val.length ? statuses.filter((s) => val.includes(s.id)).map((s) => <Lozenge key={s.id} category={s.category}>{s.name}</Lozenge>) : <span className="text-fg-subtlest">{empty}</span>}</button>} />
    );
  };
  const trig = auto.triggers.find((t) => t.value === d.trigger);
  const vars = auto.variables.map((v) => v.value).join(" ");

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
        <Field label="Nombre" required><Input autoFocus value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} maxLength={120} /></Field>
        <Field label="Activa"><div className="pt-1.5"><Toggle label="Activa" checked={d.enabled ?? true} onChange={(v) => setD({ ...d, enabled: v })} /></div></Field>
        <Field label="Descripción" className="sm:col-span-2"><Input value={d.description ?? ""} onChange={(e) => setD({ ...d, description: e.target.value })} /></Field>
      </div>

      <Step n={1} title="Cuando">
        <Picker value={d.trigger} width={360} options={auto.triggers} onSelect={(v) => setD({ ...d, trigger: v, trigger_config: v === "scheduled" ? { every: "day", time: "09:00", jql: "" } : {} })}
                trigger={<button className={cn(sel, "max-w-[360px]")}><Zap size={14} className="text-discovery" />{trig?.label}</button>} />
        <p className="mt-1 text-xs text-fg-subtle">{trig?.description}</p>
        {d.trigger === "issue_transitioned" && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field label="Desde (vacío = cualquiera)">{statusMulti("from_status_ids", "Cualquier estado")}</Field>
            <Field label="Hacia (vacío = cualquiera)">{statusMulti("to_status_ids", "Cualquier estado")}</Field>
          </div>
        )}
        {d.trigger === "issue_updated" && (
          <Field label="Campos (vacío = cualquiera)" className="mt-3">
            <div className="flex flex-wrap gap-x-4 gap-y-1">{auto.editable_fields.map(({ value: v, label: l }) => {
              const val = cfg.fields ?? [];
              return <Checkbox key={v} label={l} checked={val.includes(v)} onChange={(on) => setCfg({ fields: on ? [...val, v] : val.filter((x) => x !== v) })} />;
            })}</div>
          </Field>
        )}
        {d.trigger === "scheduled" && (
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Field label="Frecuencia">
              <select className={sel} value={String(cfg.every ?? "day")} onChange={(e) => setCfg({ every: e.target.value })}>
                {auto.schedule_every.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Field>
            {cfg.every === "week" && (
              <Field label="Día"><select className={sel} value={Number(cfg.weekday ?? 0)} onChange={(e) => setCfg({ weekday: Number(e.target.value) })}>{auto.weekdays.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}</select></Field>
            )}
            <Field label={cfg.every === "hour" ? "Minuto (HH:MM, se usa MM)" : "Hora"}><Input type="time" value={String(cfg.time ?? "09:00")} onChange={(e) => setCfg({ time: e.target.value })} /></Field>
            <Field label="Incidencias (JQL)" required className="sm:col-span-3" hint={projectKey ? `Solo se consideran incidencias de ${projectKey}. Máximo 500 por ejecución.` : "Máximo 500 por ejecución."}>
              <Input className="font-mono" value={String(cfg.jql ?? "")} onChange={(e) => setCfg({ jql: e.target.value })} placeholder="due < now() AND resolution = Unresolved" />
            </Field>
          </div>
        )}
      </Step>

      <Step n={2} title="Si (opcional)">
        {conditions.map((c, i) => (
          <div key={i} className="mb-2 flex items-start gap-2">
            {c.type === "jql" ? (
              <Field label={choiceLabel(auto.conditions, c.type)} className="flex-1"><Input className="font-mono" value={String(c.jql ?? "")} onChange={(e) => setConditions(conditions.map((x, j) => (j === i ? { ...x, jql: e.target.value } : x)))} placeholder="labels = cliente AND assignee is EMPTY" /></Field>
            ) : (
              <Field label={choiceLabel(auto.conditions, c.type)} className="flex-1">
                <select className={sel} value={String(c.of ?? "issue")} onChange={(e) => setConditions(conditions.map((x, j) => (j === i ? { ...x, of: e.target.value } : x)))}>
                  {auto.action_targets.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </Field>
            )}
            <Button size="icon" variant="subtle" className="mt-5" aria-label="Quitar condición" onClick={() => setConditions(conditions.filter((_, j) => j !== i))}><Trash2 size={14} /></Button>
          </div>
        ))}
        <div className="flex gap-2">
          {auto.conditions.map((c) => (
            <Button key={c.value} size="sm" onClick={() => setConditions([...conditions, defaultCondition(c.value)])}><Plus size={14} />{c.label}</Button>
          ))}
        </div>
      </Step>

      <Step n={3} title="Entonces">
        <div className="space-y-3">
          {actions.map((a, i) => (
            <div key={i} className="rounded-[3px] border border-line p-3">
              <div className="mb-2 flex items-center gap-2">
                <Badge>{i + 1}</Badge><b className="text-sm">{choiceLabel(auto.actions, a.type)}</b>
                {a.type !== "notify" && a.type !== "webhook" && (
                  <select className="ml-2 h-7 rounded-[3px] border border-line bg-bg-subtle px-1 text-xs" value={String(a.target ?? "issue")} onChange={(e) => setActions(actions.map((x, j) => (j === i ? { ...x, target: e.target.value } : x)))}>
                    {auto.action_targets.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                )}
                <div className="ml-auto flex">
                  <Button size="icon" variant="subtle" aria-label="Subir" disabled={i === 0} onClick={() => { const n = [...actions]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setActions(n); }}><ArrowUp size={14} /></Button>
                  <Button size="icon" variant="subtle" aria-label="Bajar" disabled={i === actions.length - 1} onClick={() => { const n = [...actions]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; setActions(n); }}><ArrowDown size={14} /></Button>
                  <Button size="icon" variant="subtle" aria-label="Quitar acción" onClick={() => setActions(actions.filter((_, j) => j !== i))}><Trash2 size={14} /></Button>
                </div>
              </div>
              <ActionFields a={a} onChange={(x) => setActions(actions.map((y, j) => (j === i ? x : y)))} statuses={statuses} priorities={priorities.data ?? []} projectKey={projectKey} isAdmin={!!me.is_admin} auto={auto} vars={vars} />
            </div>
          ))}
          <Picker value={null} width={240} options={auto.actions.filter((x) => !x.admin_only || me.is_admin)} onSelect={(v) => setActions([...actions, defaultAction(v, statuses)])}
                  trigger={<Button size="sm"><Plus size={14} />Agregar acción</Button>} />
        </div>
      </Step>

      <div className="flex items-center gap-3 border-t border-line pt-3">
        <Checkbox checked={!!d.allow_rule_triggers} onChange={(v) => setD({ ...d, allow_rule_triggers: v })} label="Permitir que otras reglas la disparen" />
        <div className="ml-auto flex gap-2">
          <Button variant="subtle" onClick={onCancel}>Cancelar</Button>
          <Button variant="primary" disabled={!d.name.trim() || !actions.length} loading={save.isPending} onClick={() => save.mutate()}>Guardar regla</Button>
        </div>
      </div>
    </div>
  );
}

function Step({ n, title, children }) {
  return (
    <section className="grid grid-cols-[28px_1fr] gap-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-discovery-subtle text-sm font-semibold text-discovery">{n}</span>
      <div><h3 className="mb-2 text-sm font-semibold">{title}</h3>{children}</div>
    </section>
  );
}

function defaultCondition(type) {
  if (type === "jql") return { type, jql: "" };
  if (type === "children_done") return { type, of: "issue" };
  return { type };
}

function defaultAction(type, statuses) {
  switch (type) {
    case "transition": return { type, status_id: statuses.find((s) => s.category === "done")?.id };
    case "assign": return { type, to: "reporter" };
    case "edit": return { type, fields: {} };
    case "comment": return { type, body: "" };
    case "create_subtasks": return { type, summaries: [] };
    case "notify": return { type, to: ["assignee"], subject: "[Gestiona] {{issue.key}}", body: "{{issue.summary}}\n{{issue.url}}" };
    case "webhook": return { type, url: "", body: "{{issue.key}}: {{issue.summary}}" };
    default: return { type };
  }
}

function UserLabel({ id }) {
  const u = useQuery({ queryKey: ["user", id], enabled: !!id, queryFn: () => unwrap(api.GET("/api/v1/users/{user_id}", { params: { path: { user_id: id } } })) });
  if (!id) return <span className="text-fg-subtlest">Elegir persona</span>;
  return <span className="flex items-center gap-1.5"><Avatar user={u.data ?? null} size="xs" />{u.data?.name ?? "…"}</span>;
}

/**
 * What the project's field configuration says about an «Editar» / «Crear subtareas» action:
 * subtasks are created with the sub-task type's create rules, and edits can't touch hidden
 * fields or empty required ones (the backend validates when the rule runs).
 */
function ScreenWarnings({ a, projectKey }) {
  const meta = useProjectMeta(projectKey);
  const rules = useFieldRules(projectKey);
  const appMeta = useMeta();
  if (!projectKey || !meta.data || rules.isPending) return null;
  const m = meta.data;
  const fr = rules.data;
  const catalog = fieldCatalog(fr, m, appMeta.data);
  const out = [];
  if (a.type === "create_subtasks") {
    const sub = m.issue_types.find((t) => t.level === -1);
    if (!sub) out.push("Este proyecto no tiene un tipo de subtarea: la acción fallará.");
    else {
      const missing = quickCreateMissing(fr, m, sub.id).filter((k) => k !== "parent");
      if (missing.length) out.push(`«${sub.name}» exige ${missing.map((k) => `«${fieldLabel(catalog, k)}»`).join(", ")} al crear: las subtareas no se podrán crear solo con el resumen.`);
    }
  }
  if (a.type === "edit") {
    const keys = [];
    const f = a.fields ?? {};
    if (f.priority != null) keys.push("priority");
    if (f.story_points != null) keys.push("story_points");
    if (f.flagged != null) keys.push("flagged");
    if (f.due_in_days != null) keys.push("due_date");
    if (a.add_labels?.length || a.remove_labels?.length) keys.push("labels");
    const types = m.issue_types;
    for (const k of keys) {
      const hiddenIn = types.filter((t) => hiddenKeys(fr, t.id).has(k)).map((t) => t.name);
      if (hiddenIn.length) out.push(`«${fieldLabel(catalog, k)}» está oculto en ${hiddenIn.join(", ")}: en esas incidencias la acción fallará.`);
    }
    if (a.remove_labels?.length) {
      const req = types.filter((t) => requiredKeys(fr, m, t.id).has("labels")).map((t) => t.name);
      if (req.length) out.push(`«${fieldLabel(catalog, "labels")}» es obligatorio en ${req.join(", ")}: si la acción las deja vacías, fallará.`);
    }
  }
  if (!out.length) return null;
  return <ul className="mt-2 space-y-1 rounded-[3px] bg-warning-subtle px-3 py-2 text-xs" role="note">{out.map((t) => <li key={t}>{t}</li>)}</ul>;
}

function ActionFields(props) {
  return (
    <>
      <ActionFieldsBody {...props} />
      {(props.a.type === "edit" || props.a.type === "create_subtasks") && <ScreenWarnings a={props.a} projectKey={props.projectKey} />}
    </>
  );
}

function ActionFieldsBody({ a, onChange, statuses, priorities, projectKey, isAdmin, auto, vars }) {
  const L = (k) => choiceLabel(auto.edit_action_fields, k);
  const set = (patch) => onChange({ ...a, ...patch });
  const fields = a.fields ?? {};
  const lines = (v) => (v ?? []).join("\n");
  const csv = (v) => (v ?? []).join(", ");
  const toList = (s, sep) => s.split(sep).map((x) => x.trim()).filter(Boolean);
  switch (a.type) {
    case "transition":
      return (
        <Picker value={a.status_id ?? null} width={260} options={statuses.map((s) => ({ value: s.id, label: s.name }))} onSelect={(v) => set({ status_id: v })}
                trigger={<button className={cn(sel, "max-w-[300px]")}>{statuses.find((s) => s.id === a.status_id)?.name ?? "Elegir estado"}</button>} />
      );
    case "assign":
      return (
        <div className="flex gap-2">
          <select className={cn(sel, "max-w-[260px]")} value={String(a.to)} onChange={(e) => set({ to: e.target.value })}>
            {auto.assign_to.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          {a.to === "user" && <UserPicker allowNone={false} projectKey={projectKey} assignable={!!projectKey} value={a.user_id ?? null} onSelect={(v) => set({ user_id: v })}
                                          trigger={<button className={cn(sel, "max-w-[260px]")}><UserLabel id={a.user_id} /></button>} />}
        </div>
      );
    case "edit":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={L("priority")}>
            <select className={sel} value={String(fields.priority ?? "")} onChange={(e) => { const f = { ...fields }; if (e.target.value) f.priority = Number(e.target.value); else delete f.priority; set({ fields: f }); }}>
              <option value="">Sin cambiar</option>{priorities.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          <Field label={L("due_in_days")}>
            <Input type="number" value={fields.due_in_days == null ? "" : String(fields.due_in_days)} placeholder="Sin cambiar"
                   onChange={(e) => { const f = { ...fields }; if (e.target.value === "") delete f.due_in_days; else f.due_in_days = Number(e.target.value); set({ fields: f }); }} />
          </Field>
          <Field label={L("flagged")}>
            <select className={sel} value={fields.flagged == null ? "" : String(fields.flagged)} onChange={(e) => { const f = { ...fields }; if (e.target.value === "") delete f.flagged; else f.flagged = e.target.value === "true"; set({ fields: f }); }}>
              <option value="">Sin cambiar</option><option value="true">Marcar</option><option value="false">Quitar</option>
            </select>
          </Field>
          <Field label={L("story_points")}>
            <Input type="number" min={0} step="any" value={fields.story_points == null ? "" : String(fields.story_points)} placeholder="Sin cambiar"
                   onChange={(e) => { const f = { ...fields }; if (e.target.value === "") delete f.story_points; else f.story_points = Number(e.target.value); set({ fields: f }); }} />
          </Field>
          <Field label={L("add_labels")} hint="Separadas por coma"><Input value={csv(a.add_labels)} onChange={(e) => set({ add_labels: toList(e.target.value, /,/) })} /></Field>
          <Field label={L("remove_labels")} hint="Separadas por coma"><Input value={csv(a.remove_labels)} onChange={(e) => set({ remove_labels: toList(e.target.value, /,/) })} /></Field>
        </div>
      );
    case "comment":
      return <Field label="Comentario" hint={`Variables: ${vars}`}><Textarea rows={3} value={String(a.body ?? "")} onChange={(e) => set({ body: e.target.value })} /></Field>;
    case "create_subtasks":
      return <Field label="Una subtarea por línea"><Textarea rows={3} value={lines(a.summaries)} onChange={(e) => set({ summaries: e.target.value.split("\n") })} /></Field>;
    case "add_watcher":
      // Only people who can see the project (global rules: anyone; filtered when running).
      return <UserPicker allowNone={false} projectKey={projectKey} value={a.user_id ?? null} onSelect={(v) => set({ user_id: v })} trigger={<button className={cn(sel, "max-w-[260px]")}><UserLabel id={a.user_id} /></button>} />;
    case "notify": {
      const to = a.to ?? [];
      const userIds = a.user_ids ?? [];
      return (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-4">{auto.notify_to.map(({ value: v, label: l }) => <Checkbox key={v} label={l} checked={to.includes(v)} onChange={(on) => set({ to: on ? [...to, v] : to.filter((x) => x !== v) })} />)}</div>
          <Field label="Otras personas" hint={projectKey ? "Solo personas con acceso al proyecto." : undefined}>
            <div className="flex flex-wrap items-center gap-2">
              {userIds.map((id) => (
                <span key={id} className="flex items-center gap-1 rounded-[3px] border border-line py-0.5 pl-1.5 pr-0.5 text-sm">
                  <UserLabel id={id} />
                  <button aria-label="Quitar persona" className="rounded p-0.5 hover:bg-bg-hover" onClick={() => set({ user_ids: userIds.filter((x) => x !== id) })}><Trash2 size={12} /></button>
                </span>
              ))}
              <UserPicker allowNone={false} projectKey={projectKey} value={null} onSelect={(v) => v && !userIds.includes(v) && set({ user_ids: [...userIds, v] })}
                          trigger={<Button size="sm"><Plus size={14} />Agregar persona</Button>} />
            </div>
          </Field>
          <Field label="Asunto"><Input value={String(a.subject ?? "")} onChange={(e) => set({ subject: e.target.value })} /></Field>
          <Field label="Mensaje" hint={`Variables: ${vars}`}><Textarea rows={3} value={String(a.body ?? "")} onChange={(e) => set({ body: e.target.value })} /></Field>
        </div>
      );
    }
    case "webhook":
      return (
        <div className="space-y-3">
          {!isAdmin && <p className="text-xs text-warning">Solo un administrador del sistema puede guardar webhooks.</p>}
          <Field label="URL (POST con JSON de la incidencia)" hint="Sirve para Slack, Teams, n8n o tu propio servicio. Las direcciones internas están bloqueadas."><Input value={String(a.url ?? "")} onChange={(e) => set({ url: e.target.value })} placeholder="https://hooks.slack.com/services/..." /></Field>
          <Field label="Texto (campo «text» del JSON)" hint={`Variables: ${vars}`}><Input value={String(a.body ?? "")} onChange={(e) => set({ body: e.target.value })} /></Field>
        </div>
      );
    default:
      return null;
  }
}
