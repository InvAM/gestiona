"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowRight } from "lucide-react";
import { useRef, useState } from "react";
import { Button, PageSpinner } from "@/components/ui/button";
import { Lozenge, Modal } from "@/components/ui/primitives";
import { useApp } from "@/components/shell/app-context";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { invalidateIssueViews, qk, useFieldRules, useIssue, useMeta, useProjectMeta } from "@/lib/api/hooks";
import { fieldErrors, isEmptyValue, issueValue, toPatch } from "@/lib/fields";
import { allKeys, fieldLabel, fieldCatalog, transitionNeedsInput, transitionScreen } from "@/lib/screens";
import { ScreenForm, requiredErrors } from "./screen-form";

/** POST /issues/{key}/transitions body with the values of the transition screen. */
export function transitionBody(transition, values, issue) {
  const body = { transition_id: transition.id };
  if (values.resolution) body.resolution_id = values.resolution;
  if (!isEmptyValue(values.comment)) body.comment = values.comment;
  const changed = {};
  for (const [k, v] of Object.entries(values)) {
    if (k === "resolution" || k === "comment") continue;
    if (JSON.stringify(v ?? null) !== JSON.stringify(issueValue(issue, k) ?? null)) changed[k] = v;
  }
  if (Object.keys(changed).length) body.fields = toPatch(changed);
  return body;
}

/**
 * Jira-like transition dialog: shows the transition screen (+ required fields, resolution and
 * comment) for `issueKey` and runs the transition with those values. `onDone(issue)` after a
 * successful transition, `onCancel()` if closed without running it.
 */
export function TransitionDialog({ issueKey, transition, onDone, onCancel }) {
  const issue = useIssue(issueKey);
  const meta = useProjectMeta(issue.data?.project.key);
  const rules = useFieldRules(issue.data?.project.key);
  const appMeta = useMeta();
  const { me } = useApp();
  const qc = useQueryClient();
  const [values, setValues] = useState(null);
  const [errors, setErrors] = useState({});
  const [general, setGeneral] = useState(null);
  const [busy, setBusy] = useState(false);
  const finished = useRef(false);

  const ready = issue.data && meta.data && appMeta.data && !rules.isPending;
  const screen = ready ? transitionScreen(rules.data, meta.data, appMeta.data, issue.data.type.id, transition) : null;
  const keys = screen ? allKeys(screen) : new Set();
  // validator fields outside the screen can't be filled in here: the issue must have them
  const blocked = ready ? screen.blocked.filter((b) => isEmptyValue(issueValue(issue.data, b.key))) : [];
  // initial values come from the issue (derived once the data is there)
  let vals = values;
  if (!vals && ready) {
    vals = {};
    for (const k of keys) vals[k] = issueValue(issue.data, k);
    if (keys.has("resolution") && !vals.resolution) vals.resolution = meta.data.resolutions.find((r) => r.is_default)?.id ?? null;
    vals.comment = "";
  }
  const ctx = ready ? { projectKey: issue.data.project.key, meta: meta.data, me, typeLevel: issue.data.type.level, issueKey } : null;

  const close = () => { if (!finished.current) { finished.current = true; onCancel?.(); } };
  const submit = async () => {
    if (!ready || busy) return;
    const errs = requiredErrors(screen, vals);
    setErrors(errs);
    setGeneral(null);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const data = await unwrap(api.POST("/api/v1/issues/{key}/transitions", { params: { path: { key: issueKey } }, body: transitionBody(transition, vals, issue.data) }));
      qc.setQueryData(qk.issue(issueKey), data);
      invalidateIssueViews(qc, issueKey);
      finished.current = true;
      onDone?.(data);
    } catch (e) {
      const catalog = fieldCatalog(rules.data, meta.data, appMeta.data);
      const fe = fieldErrors(e, new Set([...keys, ...catalog.keys()]));
      const on = Object.fromEntries(Object.entries(fe).filter(([k]) => keys.has(k)));
      const off = Object.keys(fe).filter((k) => !keys.has(k));
      setErrors(on);
      if (!Object.keys(on).length || off.length) {
        setGeneral(off.length ? `${errorMessage(e)} (${off.map((k) => fieldLabel(catalog, k)).join(", ")})` : errorMessage(e));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onOpenChange={(o) => !o && close()} width={640}
           title={<span className="flex flex-wrap items-center gap-2">{transition.name}<ArrowRight size={16} className="text-fg-subtlest" aria-hidden="true" /><Lozenge category={transition.to.category}>{transition.to.name}</Lozenge></span>}
           footer={<>
             <Button variant="subtle" onClick={close}>Cancelar</Button>
             <Button variant="primary" loading={busy} disabled={!ready || blocked.length > 0} onClick={submit}>{transition.name}</Button>
           </>}>
      <div onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit(); } }}>
        {issue.data && <p className="mb-3 text-sm text-fg-subtle">{issue.data.key} · {issue.data.summary}</p>}
        {general && <p role="alert" className="mb-3 flex items-start gap-2 rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger"><AlertCircle size={16} className="mt-0.5 shrink-0" />{general}</p>}
        {blocked.length > 0 && (
          <p role="alert" className="mb-3 flex items-start gap-2 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">
            <AlertCircle size={16} className="mt-0.5 shrink-0 text-warning" />
            <span>«{transition.name}» exige {blocked.map((b) => `«${b.label}»`).join(", ")}, que {blocked.length === 1 ? "no tiene valor y no está" : "no tienen valor y no están"} en esta pantalla. Complétalo en la incidencia y vuelve a intentarlo.</span>
          </p>
        )}
        {issue.error ? <p role="alert" className="text-sm text-danger">{errorMessage(issue.error)}</p>
          : !ready ? <PageSpinner />
          : <ScreenForm screen={screen} values={vals} ctx={ctx} errors={errors} autoFocusFirst
                        onChange={(k, v) => { setValues({ ...vals, [k]: v }); if (errors[k]) setErrors((e) => { const n = { ...e }; delete n[k]; return n; }); }} />}
      </div>
    </Modal>
  );
}

/**
 * Run a transition from anywhere (status button, board drag, Lista): without input it posts
 * right away; otherwise it opens the transition dialog. `run(key, transition)` resolves to the
 * updated issue, or null if the user cancelled. Render `dialog` once in the caller.
 */
export function useTransitionRunner() {
  const qc = useQueryClient();
  const [pending, setPending] = useState(null);
  const run = (issueKey, transition) => {
    if (!transitionNeedsInput(transition)) {
      return unwrap(api.POST("/api/v1/issues/{key}/transitions", { params: { path: { key: issueKey } }, body: { transition_id: transition.id } }))
        .then((data) => { qc.setQueryData(qk.issue(issueKey), data); invalidateIssueViews(qc, issueKey); return data; })
        .catch((e) => {
          if (!(e instanceof ApiError && e.code === "fields")) throw e;
          return new Promise((resolve) => setPending({ issueKey, transition, resolve }));
        });
    }
    return new Promise((resolve) => setPending({ issueKey, transition, resolve }));
  };
  const dialog = pending ? (
    <TransitionDialog key={`${pending.issueKey}:${pending.transition.id}`} issueKey={pending.issueKey} transition={pending.transition}
                      onDone={(d) => { pending.resolve(d); setPending(null); }}
                      onCancel={() => { pending.resolve(null); setPending(null); }} />
  ) : null;
  return { run, dialog, busy: !!pending };
}
