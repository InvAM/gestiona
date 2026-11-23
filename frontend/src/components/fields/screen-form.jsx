"use client";

import { AlertCircle } from "lucide-react";
import { useId, useState } from "react";
import { Tabs } from "@/components/ui/primitives";
import { isEmptyValue } from "@/lib/fields";
import { cn } from "@/lib/utils";
import { FieldInput } from "./field-input";

/**
 * Label + control + help/error of one field. The label is tied to the control through `id`
 * (htmlFor), and the error / description through `aria-describedby`. `children` is a render
 * function that receives the a11y props for the focusable control.
 */
export function FieldShell({ label, required, description, error, children, className, extra }) {
  const base = useId();
  const id = `${base}-control`;
  const hintId = `${base}-hint`;
  const errId = `${base}-error`;
  const describedBy = [error ? errId : null, description ? hintId : null].filter(Boolean).join(" ") || undefined;
  const a11y = {
    id, "aria-invalid": error ? true : undefined, "aria-describedby": describedBy,
    "aria-required": required ? true : undefined,
  };
  return (
    <div className={cn("block", className)}>
      <div className="mb-1 flex items-center gap-2">
        <label htmlFor={id} id={`${base}-label`} className="block text-xs font-semibold text-fg-subtle">
          {label}{required && <span className="ml-0.5 text-danger" aria-hidden="true">*</span>}
          {required && <span className="sr-only"> (obligatorio)</span>}
        </label>
        {extra}
      </div>
      {children(a11y)}
      {error && <span id={errId} role="alert" className="mt-1 flex items-center gap-1 text-xs text-danger"><AlertCircle size={12} aria-hidden="true" />{error}</span>}
      {description && <span id={hintId} className="mt-1 block text-xs text-fg-subtlest">{description}</span>}
    </div>
  );
}

/** Errors for the required fields of `screen` that are empty in `values`. */
export function requiredErrors(screen, values) {
  const out = {};
  for (const tab of screen?.tabs ?? []) {
    for (const f of tab.fields) {
      if (f.required && f.editable !== false && isEmptyValue(values[f.key])) out[f.key] = `«${f.label}» es obligatorio`;
    }
  }
  return out;
}

export function screenKeys(screen) {
  return new Set((screen?.tabs ?? []).flatMap((t) => t.fields.map((f) => f.key)));
}

/**
 * A resolved screen (tabs with ordered fields) as a form. Fields carry `{key, label, required,
 * description, custom?}`. Required fields get «*», the description is the help text, and
 * errors (client or 422) are shown next to each field. With several tabs, the tab that holds
 * the first error is selected whenever a new set of errors arrives.
 */
const NO_ERRORS = {};
const NO_EXTRAS = {};

export function ScreenForm({ screen, values, onChange, errors = NO_ERRORS, ctx, exclude, className, autoFocusFirst, extras = NO_EXTRAS, remount = NO_EXTRAS }) {
  const tabs = (screen?.tabs ?? []).map((t) => ({ ...t, fields: t.fields.filter((f) => !exclude?.has(f.key)) }))
    .filter((t) => t.fields.length);
  const [tab, setTab] = useState(0);
  // jump to the tab with the first error when a new set of errors arrives (derived, no effect);
  // compared by content so callers may build the errors object on every render
  const signature = JSON.stringify(errors);
  const [seenErrors, setSeenErrors] = useState(signature);
  if (seenErrors !== signature) {
    setSeenErrors(signature);
    const i = tabs.findIndex((t) => t.fields.some((f) => errors[f.key]));
    if (i >= 0 && i !== tab) setTab(i);
  }
  if (!tabs.length) return null;
  const current = tabs[Math.min(tab, tabs.length - 1)];
  const firstKey = tabs[0].fields[0]?.key;
  return (
    <div className={className}>
      {tabs.length > 1 && (
        <Tabs className="mb-4" value={Math.min(tab, tabs.length - 1)} onChange={setTab}
              tabs={tabs.map((t, i) => {
                const bad = t.fields.filter((f) => errors[f.key]).length;
                return {
                  value: i,
                  label: <span className="inline-flex items-center gap-1">{t.name}{bad > 0 && <span className="rounded-full bg-danger px-1.5 text-[10px] font-bold text-white" aria-label={`${bad} con error`}>{bad}</span>}</span>,
                };
              })} />
      )}
      <div className="grid gap-4">
        {current.fields.map((f) => (
          <FieldShell key={f.key} label={f.label} required={f.required} description={f.description} error={errors[f.key]}
                      extra={extras[f.key]} className={["description", "summary", "comment"].includes(f.key) ? undefined : "max-w-[420px]"}>
            {(a11y) => (
              <FieldInput key={remount[f.key] ?? 0} field={f} value={values[f.key]} ctx={ctx} a11y={a11y} autoFocus={autoFocusFirst && f.key === firstKey}
                          disabled={f.editable === false} onChange={(v) => onChange(f.key, v)} />
            )}
          </FieldShell>
        ))}
      </div>
    </div>
  );
}
