"use client";

import { ChevronDown, Lock } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { FieldDisplay, FieldInput, INLINE_BTN, isInstant, scrumBoard } from "@/components/fields/field-input";
import { FieldShell } from "@/components/fields/screen-form";
import { useApp } from "@/components/shell/app-context";
import { Button } from "@/components/ui/button";
import { Tabs, Tip } from "@/components/ui/primitives";
import { isEmptyValue, issueValue, toPatch } from "@/lib/fields";
import { editKeys, hiddenKeys, requiredKeys, screenFor } from "@/lib/screens";
import { cn } from "@/lib/utils";
import { LogWorkDialog, TimeBar } from "./activity";

/** Keys shown elsewhere in the issue view (title, description, status button). */
const OUTSIDE = new Set(["summary", "description", "comment", "resolution", "issue_type", "status"]);

/**
 * Field rules of an open issue: what the view screen shows (order, tabs), what the edit
 * screen lets you change and what can't be emptied. `edit === null` = the server sends no
 * screens (older backend): every field is editable as before.
 */
export function issueScreens(issue, meta, appMeta, fr) {
  if (!meta || !issue) return null;
  const typeId = issue.type.id;
  const view = screenFor(fr, meta, appMeta, typeId, "view");
  const edit = editKeys(fr, typeId);
  const hidden = hiddenKeys(fr, typeId);
  const required = requiredKeys(fr, meta, typeId);
  const viewKeys = new Set(view.tabs.flatMap((t) => t.fields.map((f) => f.key)));
  const can = issue.permissions.includes("edit_issues") && !issue.is_archived;
  const canEditKey = (key) => {
    if (issue.is_archived) return "Incidencia archivada (solo lectura)";
    if (key === "assignee") {
      // «Asignar» doesn't need the edit screen, only that the field is not hidden
      if (!(issue.permissions.includes("assign_issues") || can)) return "No tienes permiso para asignar";
      return hidden.has("assignee") ? "Campo oculto en la configuración de este tipo" : null;
    }
    if (!can) return "No tienes permiso para editar";
    if (edit && !edit.has(key)) return "Este campo no está en la pantalla de edición de este tipo";
    return null;
  };
  // summary/description: hidden only when a server view screen leaves them out
  const shows = (key) => !view.resolved || viewKeys.has(key) || key === "summary";
  const screenLock = (key) => !issue.is_archived && (key === "assignee" ? hidden.has(key) : !!edit && !edit.has(key));
  return { view, edit, required, canEditKey, shows, screenLock };
}

function Row({ label, required, children, lock }) {
  return (
    <div className="grid grid-cols-[minmax(110px,40%)_1fr] items-start gap-2 py-1.5">
      <div className="flex items-center gap-1 pt-1 text-sm font-semibold text-fg-subtle">
        <span>{label}{required && <span className="ml-0.5 text-danger" aria-label="obligatorio">*</span>}</span>
        {lock && <Tip content={lock}><span aria-label={lock} className="text-fg-subtlest"><Lock size={12} /></span></Tip>}
      </div>
      <div className="min-w-0 text-sm">{children}</div>
    </div>
  );
}

/** One field of the details panel: instant pickers save on pick, the rest edit with ✓ / ✗. */
function InlineField({ field, issue, ctx, lock, required, onSave }) {
  const [draft, setDraft] = useState(undefined);
  const [error, setError] = useState(null);
  const value = issueValue(issue, field.key);
  const editable = !lock;
  const save = (v) => {
    if (required && isEmptyValue(v)) {
      const msg = `«${field.label}» es obligatorio y no se puede vaciar`;
      setError(msg);
      toast.error(msg);
      return false;
    }
    setError(null);
    onSave(field.key, v);
    return true;
  };
  const f = { ...field, required };

  if (!editable) {
    return <div className="flex min-h-8 items-center px-1.5 py-1" title={lock}><FieldDisplay field={field} issue={issue} ctx={ctx} /></div>;
  }
  if (field.key === "flagged") {
    return <button type="button" className={INLINE_BTN} onClick={() => save(!value)}><FieldDisplay field={field} issue={issue} ctx={ctx} /></button>;
  }
  if (isInstant(field)) {
    return (
      <div>
        <FieldInput field={f} value={value} inline ctx={ctx} onChange={(v) => save(v)}
                    a11y={{ "aria-label": field.label, "aria-invalid": error ? true : undefined }} />
        {error && <span role="alert" className="block px-1.5 text-xs text-danger">{error}</span>}
      </div>
    );
  }
  if (draft === undefined) {
    return (
      <button type="button" className={INLINE_BTN} aria-label={`Editar ${field.label}`} onClick={() => { setDraft(value); setError(null); }}>
        <FieldDisplay field={field} issue={issue} ctx={ctx} />
      </button>
    );
  }
  const commit = () => { if (save(draft)) setDraft(undefined); };
  return (
    <div className="space-y-2" onKeyDown={(e) => {
      // pickers render in a portal: their keys bubble here through React but aren't ours
      if (!e.currentTarget.contains(e.target)) return;
      if (e.key === "Escape") { e.stopPropagation(); setDraft(undefined); setError(null); }
      if (e.key === "Enter" && e.target.tagName === "INPUT") { e.preventDefault(); commit(); }
    }}>
      <FieldShell label={<span className="sr-only">{field.label}</span>} required={required} error={error}>
        {(a11y) => <FieldInput field={f} value={draft} ctx={ctx} a11y={a11y} autoFocus onChange={(v) => { setDraft(v); setError(null); }} />}
      </FieldShell>
      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={commit}>Guardar</Button>
        <Button size="sm" variant="subtle" onClick={() => { setDraft(undefined); setError(null); }}>Cancelar</Button>
      </div>
    </div>
  );
}

/** «Detalles» panel: fields of the view screen, in order and by tab. */
export function ScreenDetails({ issue, meta, rules, update }) {
  const { me } = useApp();
  const [open, setOpen] = useState(true);
  const [tab, setTab] = useState(0);
  const [logOpen, setLogOpen] = useState(false);
  const board = scrumBoard(meta);
  const ctx = {
    projectKey: issue.project.key, meta, me, typeLevel: issue.type.level, issueKey: issue.key,
    sprintName: issue.sprint?.name, teamName: issue.team?.name,
  };
  // structural rules on top of the screens (the backend enforces them as well)
  const showsField = (f) => {
    if (OUTSIDE.has(f.key)) return false;
    if (f.key === "parent" && issue.type.level === 1) return false;
    if (f.key === "sprint" && !(board && issue.type.level === 0) && !issue.sprint) return false;
    if (f.key === "affects_versions" && !issue.type.has_affects_versions && !issue.affects_versions.length) return false;
    if (["components", "fix_versions", "affects_versions"].includes(f.key)) {
      const has = f.key === "components" ? meta?.components?.length : meta?.versions?.length;
      if (!has && !issue[f.key]?.length) return false;
    }
    return true;
  };
  const lockOf = (key) => {
    if (key === "sprint" && !(board && issue.type.level === 0)) return issue.type.level === -1 ? "Las subtareas siguen el sprint de su principal" : "Sin tablero scrum";
    return rules?.canEditKey(key) ?? null;
  };
  const tabs = (rules?.view.tabs ?? []).map((t) => ({ ...t, fields: t.fields.filter(showsField) })).filter((t) => t.fields.length);
  const current = tabs[Math.min(tab, Math.max(tabs.length - 1, 0))];
  const timeTracking = tabs.some((t) => t.fields.some((f) => f.key === "original_estimate" || f.key === "remaining_estimate"));
  const onSave = (key, v) => update(toPatch({ [key]: v }));

  return (
    <div className="rounded-[3px] border border-line">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
              className="flex w-full items-center justify-between border-b border-line px-3 py-2.5 text-left font-semibold">
        Detalles <ChevronDown size={16} className={cn("transition-transform", !open && "-rotate-90")} />
      </button>
      {open && (
        <div className="px-3 py-1">
          {tabs.length > 1 && (
            <Tabs className="mb-1 mt-1" value={Math.min(tab, tabs.length - 1)} onChange={setTab}
                  tabs={tabs.map((t, i) => ({ value: i, label: t.name || `Pestaña ${i + 1}` }))} />
          )}
          {!rules && <p className="py-3 text-sm text-fg-subtlest" aria-busy="true">Cargando campos…</p>}
          {rules && !current && <p className="py-3 text-sm text-fg-subtlest">La pantalla de este tipo no muestra más campos.</p>}
          {current?.fields.map((f) => {
            const lock = lockOf(f.key);
            const required = rules?.required.has(f.key) ?? false;
            return (
              <Row key={f.key} label={f.label} required={required && !lock} lock={lock && (rules?.screenLock(f.key) || f.key === "sprint") ? lock : null}>
                <InlineField field={f} issue={issue} ctx={ctx} lock={lock} required={required} onSave={onSave} />
              </Row>
            );
          })}
          {timeTracking && (tab === 0 || tabs.length < 2) && (
            <Row label="Registro de tiempo">
              <button type="button" data-log-work className={cn(INLINE_BTN, "block")} disabled={!issue.permissions.includes("log_work") || issue.is_archived} onClick={() => setLogOpen(true)}>
                <TimeBar spent={issue.time_spent} estimate={issue.original_estimate ?? 0} remaining={issue.remaining_estimate} />
              </button>
            </Row>
          )}
        </div>
      )}
      <LogWorkDialog issue={issue} open={logOpen} onOpenChange={setLogOpen} />
    </div>
  );
}
