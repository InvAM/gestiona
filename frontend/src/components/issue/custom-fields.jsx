"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Checkbox, Input, Textarea, Avatar } from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { api, unwrap } from "@/lib/api/client";
import { fmtDate, fmtDateTime } from "@/lib/utils";
import { LabelPicker, UserPicker } from "./pickers";

const SEL = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover aria-[invalid=true]:border-danger";

/**
 * Editor of a custom field value. `a11y` = {id, "aria-invalid", "aria-describedby",
 * "aria-required"} is put on the focusable control so the field's <label> and error are tied
 * to it. `trigger` (optional) replaces the button that opens pickers (inline editing).
 */
export function CustomFieldInput({ field, value, onChange, projectKey, a11y = {}, required, trigger }) {
  // Deleted options are only offered while the issue still has them selected.
  const selected = (id) => (Array.isArray(value) ? value.includes(id) : value === id);
  const options = (field.options ?? []).filter((o) => !o.deleted || selected(o.id));
  const btn = (children) => trigger ?? <button type="button" className={SEL} {...a11y}>{children}</button>;
  switch (field.kind) {
    case "textarea":
      return <Textarea rows={3} value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...a11y} />;
    case "number":
      return <Input type="number" className="w-40" value={value ?? ""} invalid={a11y["aria-invalid"]} {...a11y}
                    onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
    case "date":
      return <Input type="date" className="w-44" value={value ?? ""} invalid={a11y["aria-invalid"]} {...a11y} onChange={(e) => onChange(e.target.value || null)} />;
    case "datetime":
      return <Input type="datetime-local" className="w-56" value={value ?? ""} invalid={a11y["aria-invalid"]} {...a11y} onChange={(e) => onChange(e.target.value || null)} />;
    case "url":
      return <Input type="url" placeholder="https://" value={value ?? ""} invalid={a11y["aria-invalid"]} {...a11y} onChange={(e) => onChange(e.target.value)} />;
    case "select":
      return (
        <Picker value={value} options={options.map((o) => ({ value: o.id, label: o.value }))}
                onSelect={(v) => onChange(v === value && !required ? null : v)}
                trigger={btn(options.find((o) => o.id === value)?.value ?? <span className="text-fg-subtlest">Ninguno</span>)} />
      );
    case "multiselect":
    case "checkbox": {
      const arr = value ?? [];
      if (field.kind === "checkbox" && !trigger) {
        return (
          <div role="group" className="flex flex-col gap-1" {...a11y} aria-labelledby={a11y.id?.endsWith("-control") ? a11y.id.replace(/-control$/, "-label") : undefined}>
            {options.map((o) => (
              <Checkbox key={o.id} label={o.value} checked={arr.includes(o.id)}
                        onChange={(c) => onChange(c ? [...arr, o.id] : arr.filter((x) => x !== o.id))} />
            ))}
          </div>
        );
      }
      return (
        <Picker multiple value={arr} options={options.map((o) => ({ value: o.id, label: o.value }))}
                onSelect={(v) => onChange(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])}
                trigger={btn(<span className="truncate">{arr.length ? options.filter((o) => arr.includes(o.id)).map((o) => o.value).join(", ") : <span className="text-fg-subtlest">Ninguno</span>}</span>)} />
      );
    }
    case "user":
      return (
        <UserPicker projectKey={projectKey} value={value} onSelect={onChange} noneLabel="Ninguno" allowNone={!required}
                    trigger={btn(value ? <UserName id={value} /> : <><Avatar user={null} size="xs" /><span className="text-fg-subtlest">Ninguno</span></>)} />
      );
    case "multiuser": {
      const arr = value ?? [];
      return (
        <div className="space-y-1">
          {arr.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {arr.map((id) => (
                <span key={id} className="flex items-center gap-1 rounded-[3px] border border-line py-0.5 pl-1.5 pr-0.5 text-sm">
                  <UserName id={id} />
                  <button type="button" aria-label="Quitar persona" className="rounded p-0.5 hover:bg-bg-hover" onClick={() => onChange(arr.filter((x) => x !== id))}><X size={12} /></button>
                </span>
              ))}
            </div>
          )}
          <UserPicker projectKey={projectKey} value={null} allowNone={false} onSelect={(id) => id && !arr.includes(id) && onChange([...arr, id])}
                      trigger={<button type="button" className={SEL} {...a11y}><span className="text-fg-subtlest">Agregar persona…</span></button>} />
        </div>
      );
    }
    case "labels":
      return (
        <LabelPicker value={value ?? []} onChange={onChange} projectKey={projectKey}
                     trigger={btn((value ?? []).join(", ") || <span className="text-fg-subtlest">Ninguna</span>)} />
      );
    default:
      return <Input value={value ?? ""} maxLength={255} invalid={a11y["aria-invalid"]} {...a11y} onChange={(e) => onChange(e.target.value)} />;
  }
}

export function CustomFieldDisplay({ field, value }) {
  const options = field.options ?? [];
  const empty = <span className="text-fg-subtlest">Ninguno</span>;
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return empty;
  switch (field.kind) {
    case "select":
      return <>{options.find((o) => o.id === value)?.value ?? empty}</>;
    case "multiselect":
    case "checkbox":
      return <>{options.filter((o) => value.includes(o.id)).map((o) => o.value).join(", ")}</>;
    case "date":
      return <>{fmtDate(value)}</>;
    case "datetime":
      return <>{fmtDateTime(value)}</>;
    case "url":
      return /^https?:\/\//i.test(String(value))
        ? <a href={String(value)} target="_blank" rel="noopener noreferrer nofollow" className="text-link hover:underline" onClick={(e) => e.stopPropagation()}>{String(value)}</a>
        : <>{String(value)}</>;
    case "labels":
      return <>{value.join(", ")}</>;
    case "user":
      return <UserName id={value} />;
    case "multiuser":
      return <span className="flex flex-wrap gap-2">{value.map((id) => <UserName key={id} id={id} />)}</span>;
    default:
      return <span className="whitespace-pre-wrap">{String(value)}</span>;
  }
}

/** Avatar + name of a user id (cached per id; shared with the rest of the app). */
export function UserName({ id }) {
  const u = useQuery({
    queryKey: ["user", id], enabled: !!id, staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/users/{user_id}", { params: { path: { user_id: id } } })),
  });
  return <span className="inline-flex min-w-0 items-center gap-2"><Avatar user={u.data ?? null} size="xs" /><span className="truncate">{u.data?.name ?? (u.isPending ? "…" : `Usuario ${id}`)}</span></span>;
}
