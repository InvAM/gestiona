"use client";

import { AlertCircle, ChevronDown } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon, ProjectAvatar } from "@/components/icons";
import { Button, PageSpinner } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Checkbox, Lozenge, Modal } from "@/components/ui/primitives";
import { AiDraftButton } from "@/components/ai/ai";
import { scrumBoard } from "@/components/fields/field-input";
import { FieldShell, ScreenForm, requiredErrors } from "@/components/fields/screen-form";
import { useApp } from "@/components/shell/app-context";
import { errorMessage } from "@/lib/api/client";
import { useCreateIssue, useFieldRules, useIssue, useMeta, useProjectMeta, useProjects } from "@/lib/api/hooks";
import { fieldErrors, toCreate } from "@/lib/fields";
import { allKeys, fieldCatalog, fieldLabel, screenFor } from "@/lib/screens";
import { cn } from "@/lib/utils";

const selectCls = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

/*
 * «Crear incidencia» paints the create screen of the chosen issue type (Jira company-managed).
 * Values live in one map keyed by field, so switching type keeps whatever the new screen also
 * has. Required fields are checked here and, always, by the backend (422 shown per field).
 * `defaults` (openCreate): projectKey, issueTypeId, statusId, sprintId, parentId, summary,
 * dueDate and `values` ({key: value}, e.g. what a quick-create already had).
 */
export function CreateIssueDialog() {
  const { createState, closeCreate } = useApp();
  const [session, setSession] = useState(0);
  const [wasOpen, setWasOpen] = useState(false);
  // new form state each time the dialog opens (derived during render, no effect)
  if (createState.open !== wasOpen) {
    setWasOpen(createState.open);
    if (createState.open) setSession((n) => n + 1);
  }
  if (!createState.open) return null;
  return <CreateIssueForm key={session} defaults={createState.defaults} onClose={closeCreate} />;
}

function initialValues(defaults, me) {
  const v = { reporter: me.id, ...(defaults.values ?? {}) };
  if (defaults.summary) v.summary = defaults.summary;
  if (defaults.sprintId) v.sprint = defaults.sprintId;
  if (defaults.dueDate) v.due_date = defaults.dueDate;
  return v;
}

function CreateIssueForm({ defaults, onClose: closeCreate }) {
  const { me, setLastProjectKey } = useApp();
  const projects = useProjects({});
  const appMeta = useMeta();
  const [projectKeyState, setProjectKey] = useState(defaults.projectKey);
  const projectKey = projectKeyState ?? projects.data?.find((p) => !p.is_archived)?.key;
  const meta = useProjectMeta(projectKey);
  const rules = useFieldRules(projectKey);
  const create = useCreateIssue();

  const [typeIdState, setTypeId] = useState(defaults.issueTypeId);
  const [statusId, setStatusId] = useState(defaults.statusId);
  const [values, setValues] = useState(() => initialValues(defaults, me));
  const [remount, setRemount] = useState(0);
  const [another, setAnother] = useState(false);
  const [errors, setErrors] = useState({});
  const [general, setGeneral] = useState(null);
  const parentIssue = useIssue(defaults.parentId ? String(defaults.parentId) : null);

  const m = meta.data;
  const types = useMemo(() => {
    if (!m) return [];
    // subtasks only when a parent is preset
    return m.issue_types.filter((t) => (defaults.parentId ? t.level === -1 : t.level !== -1));
  }, [m, defaults.parentId]);
  const typeId = typeIdState && types.some((t) => t.id === typeIdState) ? typeIdState
    : types.find((t) => t.id === m?.default_issue_type_id)?.id ?? types.find((t) => t.level === 0)?.id ?? types[0]?.id;
  const type = m?.issue_types.find((t) => t.id === typeId);
  const statuses = m && typeId ? (m.statuses_by_type[String(typeId)] ?? []).map((id) => m.statuses.find((s) => s.id === id)).filter(Boolean) : [];
  const status = statuses.find((s) => s.id === statusId) ?? statuses[0];
  const board = scrumBoard(m);

  // derived defaults (no effect): preset parent and the project's default priority
  const presetParent = defaults.parentId && parentIssue.data
    ? { id: parentIssue.data.id, key: parentIssue.data.key, summary: parentIssue.data.summary, type: parentIssue.data.type } : null;
  const vals = {
    ...values,
    parent: values.parent !== undefined ? values.parent : presetParent,
    priority: values.priority ?? m?.priorities.find((p) => p.is_default)?.id ?? m?.priorities[0]?.id,
  };

  const fr = rules.data;
  const screen = m && typeId && !rules.isPending ? screenFor(fr, m, appMeta.data, typeId, "create") : null;
  // structural rules the form applies on top of the screen (the backend enforces them too)
  const exclude = new Set();
  if (type?.level === 1) exclude.add("parent");
  if (!board || type?.level !== 0) exclude.add("sprint");
  const keys = screen ? new Set([...allKeys(screen)].filter((k) => !exclude.has(k))) : new Set();
  const catalog = fieldCatalog(fr, m, appMeta.data);
  const ctx = { projectKey, meta: m, me, typeLevel: type?.level, sprintName: null };

  const setField = (k, v) => {
    setValues((s) => ({ ...s, [k]: v }));
    if (errors[k]) setErrors((e) => { const n = { ...e }; delete n[k]; return n; });
  };

  async function submit() {
    if (!projectKey || !typeId || !screen) return;
    const visible = { ...screen, tabs: screen.tabs.map((t) => ({ ...t, fields: t.fields.filter((f) => !exclude.has(f.key)) })) };
    const errs = requiredErrors(visible, vals);
    setErrors(errs);
    setGeneral(null);
    if (Object.keys(errs).length) return;
    const sent = Object.fromEntries([...keys].map((k) => [k, vals[k]]));
    // the backend always accepts the context of where it is created (parent and sprint)
    for (const k of ["parent", "sprint"]) if (!exclude.has(k) && vals[k]) sent[k] = vals[k];
    const body = {
      ...toCreate(sent),
      project: projectKey, issue_type_id: typeId, summary: String(vals.summary ?? "").trim(), status_id: status?.id,
    };
    try {
      const issue = await create.mutateAsync(body);
      setLastProjectKey(projectKey);
      toast.success(<span>Se creó <Link className="font-semibold underline" href={`/browse/${issue.key}`}>{issue.key}</Link></span>);
      if (another) {
        setValues((s) => ({ ...s, summary: "", description: null }));
        setRemount((n) => n + 1);
      } else closeCreate();
    } catch (e) {
      const fe = fieldErrors(e, new Set([...keys, ...catalog.keys()]));
      const onScreen = Object.fromEntries(Object.entries(fe).filter(([k]) => keys.has(k)));
      const off = Object.entries(fe).filter(([k]) => !keys.has(k));
      setErrors(onScreen);
      if (off.length || !Object.keys(onScreen).length) {
        setGeneral(off.length
          ? `${errorMessage(e)} (${off.map(([k]) => fieldLabel(catalog, k)).join(", ")} no está en la pantalla de crear de este tipo: avisa a un administrador)`
          : errorMessage(e));
      }
    }
  }

  return (
    <Modal open onOpenChange={(o) => !o && closeCreate()} title="Crear incidencia" width={720}
           footer={<>
             <div className="mr-auto"><Checkbox checked={another} onChange={setAnother} label="Crear otra" /></div>
             <Button variant="subtle" onClick={closeCreate}>Cancelar</Button>
             <Button variant="primary" loading={create.isPending} disabled={!screen} onClick={submit}>Crear</Button>
           </>}>
      <div onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } }}>
        <p className="mb-4 text-xs text-fg-subtle">Los campos obligatorios están marcados con un asterisco <span className="text-danger">*</span></p>
        {general && (
          <p role="alert" className="mb-4 flex items-start gap-2 rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger"><AlertCircle size={16} className="mt-0.5 shrink-0" />{general}</p>
        )}
        <div className="max-w-[420px] space-y-4 pb-4">
          <FieldShell label="Proyecto" required>
            {(a11y) => (
              <Picker trigger={<button type="button" className={selectCls} {...a11y}>
                        {m ? <><ProjectAvatar project={m.project} size={18} /><span className="truncate">{m.project.name} ({m.project.key})</span></> : <span className="text-fg-subtlest">Selecciona un proyecto</span>}
                        <ChevronDown size={16} className="ml-auto text-fg-subtle" /></button>}
                      value={projectKey} width={420}
                      options={(projects.data ?? []).filter((p) => !p.is_archived).map((p) => ({ value: p.key, label: `${p.name} (${p.key})`, icon: <ProjectAvatar project={p} size={18} /> }))}
                      onSelect={(k) => {
                        setProjectKey(k); setTypeId(undefined); setErrors({});
                        // project-scoped values do not travel to another project
                        setValues((s) => ({ summary: s.summary, description: s.description, reporter: s.reporter, labels: s.labels, due_date: s.due_date, start_date: s.start_date, story_points: s.story_points, original_estimate: s.original_estimate }));
                      }} />
            )}
          </FieldShell>
          <FieldShell label="Tipo de incidencia" required>
            {(a11y) => (
              <Picker trigger={<button type="button" className={selectCls} {...a11y}>
                        <IssueTypeIcon type={type} /><span>{type?.name ?? "—"}</span><ChevronDown size={16} className="ml-auto text-fg-subtle" /></button>}
                      value={typeId} width={420}
                      options={types.map((t) => ({ value: t.id, label: t.name, icon: <IssueTypeIcon type={t} /> }))}
                      onSelect={(t) => { setTypeId(t); setErrors({}); setGeneral(null); }} />
            )}
          </FieldShell>
          {statuses.length > 0 && (
            <FieldShell label="Estado" description="Este es el estado inicial al crear la incidencia">
              {(a11y) => (
                <Picker trigger={<button type="button" className={cn(selectCls, "w-auto")} {...a11y}><Lozenge category={status?.category ?? "todo"}>{status?.name}</Lozenge><ChevronDown size={16} className="text-fg-subtle" /></button>}
                        value={status?.id} width={240}
                        options={statuses.map((s) => ({ value: s.id, label: s.name, icon: <Lozenge category={s.category}>{s.name.slice(0, 1)}</Lozenge> }))}
                        onSelect={setStatusId} />
              )}
            </FieldShell>
          )}
        </div>
        <div className="border-t border-line pb-2 pt-4">
          {!screen ? (meta.error || rules.error ? <p role="alert" className="text-sm text-danger">{errorMessage(meta.error ?? rules.error)}</p> : <PageSpinner />) : (
            <ScreenForm key={`${projectKey}:${typeId}`} screen={screen} values={vals} onChange={setField} errors={errors} ctx={ctx} exclude={exclude}
                        autoFocusFirst remount={{ summary: remount, description: remount }}
                        extras={{
                          description: <AiDraftButton projectKey={projectKey} issueTypeId={typeId} summary={String(vals.summary ?? "")}
                                                      onDraft={(doc) => { setField("description", doc); setRemount((n) => n + 1); }} />,
                        }} />
          )}
        </div>
      </div>
    </Modal>
  );
}
