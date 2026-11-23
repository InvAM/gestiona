"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Flag, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { RichField, RichView } from "@/components/editor/rich-editor";
import { CustomFieldDisplay, CustomFieldInput, UserName } from "@/components/issue/custom-fields";
import { IssuePicker, LabelPicker, MultiNamedPicker, SprintPicker, UserPicker } from "@/components/issue/pickers";
import { Button } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Avatar, Checkbox, Input, Lozenge, Textarea } from "@/components/ui/primitives";
import { api, unwrap } from "@/lib/api/client";
import { cfIdOf } from "@/lib/fields";
import { cn, fmtDate, fmtDuration, fmtPoints, parseDuration } from "@/lib/utils";

/*
 * Generic renderer of an issue field by key (system field or `cf:<id>`).
 *   field = {key, label, required?, description?, custom?}   (custom = the project's custom field)
 *   ctx   = {projectKey, meta (project meta), me, typeLevel, issueKey?}
 * `a11y` ({id, aria-invalid, aria-describedby, aria-required}) goes on the focusable control.
 * `inline` renders picker triggers as the borderless value used in the issue's details panel.
 */

const SEL = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover aria-[invalid=true]:border-danger";
export const INLINE_BTN = "flex min-h-8 w-full items-center gap-2 rounded-[3px] px-1.5 py-1 text-left text-sm hover:bg-bg-hover disabled:cursor-default disabled:hover:bg-transparent";
const NONE = <span className="text-fg-subtlest">Ninguno</span>;

/** Keys edited with a single-choice picker: in the details panel they save on pick. */
export function isInstant(field) {
  const id = cfIdOf(field.key);
  if (id !== null) return ["select", "user"].includes(field.custom?.kind);
  return ["priority", "assignee", "reporter", "sprint", "team", "parent", "resolution"].includes(field.key);
}

export function scrumBoard(meta) {
  return meta?.boards?.find((b) => b.kind === "scrum") ?? null;
}

function useTeams(enabled = true) {
  return useQuery({ queryKey: ["teams", "picker"], queryFn: () => unwrap(api.GET("/api/v1/teams")), staleTime: 60_000, enabled });
}

function useOpenSprints(boardId) {
  return useQuery({
    queryKey: ["sprints", boardId],
    queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}/sprints", { params: { path: { board_id: boardId }, query: { state: "active,future" } } })),
    enabled: !!boardId,
    staleTime: 30_000,
  });
}

/** Id of the <label> FieldShell renders for a control (groups use aria-labelledby). */
export const labelIdOf = (a11y) => (a11y?.id?.endsWith("-control") ? a11y.id.replace(/-control$/, "-label") : undefined);

function Trigger({ inline, a11y, disabled, children, className }) {
  return (
    <button type="button" disabled={disabled} className={cn(inline ? INLINE_BTN : SEL, className)} {...a11y}>
      {children}
      {!inline && <ChevronDown size={16} className="ml-auto shrink-0 text-fg-subtle" />}
    </button>
  );
}

/** Text input for Jira durations ("1w 2d 3h"); the value is in seconds. */
function DurationInput({ value, onChange, a11y }) {
  const [text, setText] = useState(value ? fmtDuration(value) : "");
  const [bad, setBad] = useState(false);
  return (
    <div>
      <Input value={text} placeholder="ej. 3d 4h" className="w-40" invalid={bad || a11y["aria-invalid"]} {...a11y}
             aria-invalid={bad || !!a11y["aria-invalid"]}
             onChange={(e) => {
               setText(e.target.value);
               const s = e.target.value.trim() ? parseDuration(e.target.value) : null;
               const ok = !e.target.value.trim() || s !== null;
               setBad(!ok);
               if (ok) onChange(s);
             }} />
      {bad && <span className="mt-1 block text-xs text-danger">Usa el formato 1w 2d 3h 30m</span>}
    </div>
  );
}

export function FieldInput({ field, value, onChange, ctx, a11y = {}, inline = false, disabled = false, autoFocus }) {
  const { key } = field;
  const meta = ctx.meta;
  const required = !!field.required;
  const id = cfIdOf(key);
  const teams = useTeams(key === "team");
  const board = key === "sprint" ? scrumBoard(meta) : null;
  const sprints = useOpenSprints(board?.id);

  if (id !== null) {
    if (!field.custom) return <span className="text-sm text-fg-subtlest">Campo no disponible en este proyecto</span>;
    const cfTrigger = inline && isInstant(field)
      ? <button type="button" disabled={disabled} className={INLINE_BTN} {...a11y}><CustomFieldDisplay field={field.custom} value={value} /></button>
      : undefined;
    return <CustomFieldInput field={field.custom} value={value} onChange={onChange} projectKey={ctx.projectKey} a11y={a11y} required={required} trigger={cfTrigger} />;
  }

  switch (key) {
    case "summary":
      return <Input autoFocus={autoFocus} value={value ?? ""} maxLength={255} invalid={a11y["aria-invalid"]} {...a11y} onChange={(e) => onChange(e.target.value)} />;
    case "description":
      return (
        <div role="group" {...a11y} aria-labelledby={labelIdOf(a11y)}>
          <RichField value={value ?? null} onChange={onChange} projectKey={ctx.projectKey} placeholder="Agrega una descripción…" />
        </div>
      );
    case "comment":
      return <Textarea rows={4} value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...a11y} />;
    case "priority": {
      const list = meta?.priorities ?? [];
      const cur = list.find((p) => p.id === value);
      return (
        <Picker value={value} width={260} onSelect={(v) => onChange(v)} placeholder="Prioridad"
                options={list.map((p) => ({ value: p.id, label: p.name, icon: <PriorityIcon priority={p} /> }))}
                trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled}>{cur ? <><PriorityIcon priority={cur} />{cur.name}</> : NONE}</Trigger>} />
      );
    }
    case "resolution": {
      const list = meta?.resolutions ?? [];
      const cur = list.find((r) => r.id === value);
      return (
        <Picker value={value} width={320} onSelect={(v) => onChange(v === value && !required ? null : v)} placeholder="Resolución"
                options={list.map((r) => ({ value: r.id, label: r.name, description: r.description }))}
                trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled}>{cur?.name ?? <span className="text-fg-subtlest">Selecciona</span>}</Trigger>} />
      );
    }
    case "assignee":
    case "reporter": {
      const allowNone = key === "assignee" ? !required : false;
      return (
        <span className="block">
          <UserPicker projectKey={ctx.projectKey} assignable={key === "assignee"} meId={ctx.me?.id} value={value ?? null}
                      allowNone={allowNone} onSelect={(v) => { if (v || allowNone) onChange(v ?? null); }}
                      trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled}>
                        {value ? <UserName id={value} /> : <><Avatar user={null} size="xs" /><span className={inline ? "" : "text-fg-subtlest"}>{key === "assignee" ? (inline ? "Sin asignar" : "Automático") : "Ninguno"}</span></>}
                      </Trigger>} />
          {key === "assignee" && !disabled && ctx.me && value !== ctx.me.id && (
            <Button variant="link" size="sm" className={inline ? "ml-1.5 text-xs" : "mt-1"} onClick={() => onChange(ctx.me.id)}>Asignarme a mí</Button>
          )}
        </span>
      );
    }
    case "parent": {
      const level = ctx.typeLevel === -1 ? 0 : 1;
      return (
        <div className="flex items-center gap-2">
          <IssuePicker projectKey={ctx.projectKey} level={level} exclude={ctx.issueKey} onSelect={(p) => onChange(p)}
                       placeholder={level === 1 ? "Buscar épica" : "Buscar incidencia principal"}
                       trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled}>
                         {value ? <><IssueTypeIcon type={value.type} /><span className="truncate">{value.key} {value.summary}</span>{value.is_archived && <Lozenge category="todo">Archivada</Lozenge>}</>
                           : <span className="text-fg-subtlest">{inline ? "Ninguno" : "Seleccionar principal"}</span>}
                       </Trigger>} />
          {value && !required && !disabled && (inline
            ? <Button size="icon-sm" variant="subtle" aria-label="Quitar principal" onClick={() => onChange(null)}><X size={14} /></Button>
            : <Button variant="subtle" onClick={() => onChange(null)}>Quitar</Button>)}
        </div>
      );
    }
    case "labels": {
      const arr = value ?? [];
      return (
        <LabelPicker value={arr} onChange={onChange} projectKey={ctx.projectKey}
                     trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled} className="h-auto min-h-8 flex-wrap py-1">
                       {arr.length ? arr.map((l) => <span key={l} className="rounded-[3px] bg-bg-sunken px-1.5 text-xs">{l}</span>) : <span className="text-fg-subtlest">Selecciona etiquetas</span>}
                     </Trigger>} />
      );
    }
    case "components":
    case "fix_versions":
    case "affects_versions": {
      const arr = value ?? [];
      const all = key === "components" ? meta?.components ?? [] : meta?.versions ?? [];
      // archived versions are only offered for «Versión afectada» or while already selected
      const opts = key === "fix_versions" ? all.filter((v) => v.status !== "archived" || arr.includes(v.id)) : all;
      return (
        <MultiNamedPicker options={opts} value={arr} onChange={onChange}
                          trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled} className="h-auto min-h-8 py-1">
                            <span className={cn("truncate", !arr.length && "text-fg-subtlest")}>{arr.length ? all.filter((x) => arr.includes(x.id)).map((x) => x.name).join(", ") : "Ninguno"}</span>
                          </Trigger>} />
      );
    }
    case "sprint": {
      if (!board) return <span className="text-sm text-fg-subtlest">{ctx.sprintName ?? "Sin tablero scrum"}</span>;
      const name = sprints.data?.find((s) => s.id === value)?.name ?? (value ? ctx.sprintName ?? "Sprint" : null);
      return (
        <SprintPicker boardId={board.id} value={value ?? null} onSelect={(v) => onChange(v ?? null)}
                      trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled}>{name ? <span className={inline ? "text-link" : ""}>{name}</span> : <span className="text-fg-subtlest">Ninguno</span>}</Trigger>} />
      );
    }
    case "team": {
      const list = teams.data ?? [];
      const name = list.find((t) => t.id === value)?.name ?? (value ? ctx.teamName ?? "Equipo" : null);
      return (
        <Picker value={value ?? 0} width={240} placeholder="Equipo" onSelect={(v) => onChange(v || null)}
                options={[...(required ? [] : [{ value: 0, label: "Sin equipo" }]), ...list.map((t) => ({ value: t.id, label: t.name }))]}
                trigger={<Trigger inline={inline} a11y={a11y} disabled={disabled}>{name ?? <span className="text-fg-subtlest">Ninguno</span>}</Trigger>} />
      );
    }
    case "story_points":
      return <Input type="number" min={0} step={0.5} className="w-32" value={value ?? ""} invalid={a11y["aria-invalid"]} {...a11y}
                    onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
    case "original_estimate":
    case "remaining_estimate":
      return <DurationInput value={value} onChange={onChange} a11y={a11y} />;
    case "start_date":
    case "due_date":
      return <Input type="date" className="w-44" value={value ?? ""} invalid={a11y["aria-invalid"]} {...a11y} onChange={(e) => onChange(e.target.value || null)} />;
    case "flagged":
      return (
        <span role="group" {...a11y} aria-labelledby={labelIdOf(a11y)} className="inline-flex">
          <Checkbox checked={!!value} onChange={onChange} label="Marcada como impedimento" />
        </span>
      );
    default:
      return <span className="text-sm text-fg-subtlest">Este campo no se puede editar aquí</span>;
  }
}

/** Read-only value of a field (details panel, previews). `issue` is an IssueOut. */
export function FieldDisplay({ field, issue, ctx }) {
  const { key } = field;
  const id = cfIdOf(key);
  if (id !== null) {
    if (!field.custom) return NONE;
    return <CustomFieldDisplay field={field.custom} value={issue.custom_fields?.[String(id)]} />;
  }
  switch (key) {
    case "summary":
      return <span>{issue.summary}</span>;
    case "description":
      return issue.description ? <RichView doc={issue.description} meId={ctx.me?.id} /> : <span className="text-fg-subtlest">Sin descripción</span>;
    case "priority":
      return issue.priority ? <span className="flex items-center gap-2"><PriorityIcon priority={issue.priority} />{issue.priority.name}</span> : NONE;
    case "resolution":
      return issue.resolution ? <span>{issue.resolution.name}</span> : <span className="text-fg-subtlest">Sin resolver</span>;
    case "assignee":
    case "reporter":
      return <span className="flex items-center gap-2"><Avatar user={issue[key]} size="sm" />{issue[key]?.name ?? (key === "assignee" ? "Sin asignar" : "—")}</span>;
    case "parent":
      return issue.parent
        ? <span className="flex min-w-0 items-center gap-2"><IssueTypeIcon type={issue.parent.type} /><span className="truncate">{issue.parent.key} {issue.parent.summary}</span>{issue.parent.is_archived && <Lozenge category="todo">Archivada</Lozenge>}</span>
        : NONE;
    case "labels":
      return issue.labels?.length ? (
        <span className="flex flex-wrap gap-1">
          {issue.labels.map((l) => (
            <Link key={l} href={`/issues?jql=${encodeURIComponent(`labels = "${l}"`)}`} onClick={(e) => e.stopPropagation()}
                  className="rounded-[3px] border border-line px-1.5 text-xs hover:bg-bg-hover">{l}</Link>
          ))}
        </span>
      ) : <span className="text-fg-subtlest">Ninguna</span>;
    case "components":
    case "fix_versions":
    case "affects_versions":
      return issue[key]?.length ? <span>{issue[key].map((x) => x.name).join(", ")}</span> : NONE;
    case "sprint":
      return issue.sprint ? (
        <span className="flex items-center gap-2"><span className="text-link">{issue.sprint.name}</span>
          {issue.closed_sprints?.length > 0 && <span className="text-xs text-fg-subtlest">+{issue.closed_sprints.length} cerrados</span>}</span>
      ) : NONE;
    case "team":
      return issue.team ? <span>{issue.team.name}</span> : NONE;
    case "story_points":
      return fmtPoints(issue.story_points) ?? NONE;
    case "original_estimate":
    case "remaining_estimate":
      return issue[key] ? <span>{fmtDuration(issue[key])}</span> : <span className="text-fg-subtlest">0m</span>;
    case "start_date":
      return issue.start_date ? <span>{fmtDate(issue.start_date)}</span> : NONE;
    case "due_date": {
      const overdue = issue.due_date && issue.status?.category !== "done" && issue.due_date < new Date().toISOString().slice(0, 10);
      return issue.due_date ? <span className={cn(overdue && "font-semibold text-danger")}>{fmtDate(issue.due_date)}</span> : NONE;
    }
    case "flagged":
      return issue.flagged ? <span className="flex items-center gap-1 text-danger"><Flag size={14} className="fill-current" />Sí</span> : <span className="text-fg-subtlest">No</span>;
    default:
      return NONE;
  }
}
