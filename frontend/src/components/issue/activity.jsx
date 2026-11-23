"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { RichEditor, RichView } from "@/components/editor/rich-editor";
import { Button } from "@/components/ui/button";
import { Avatar, Confirm, Input, Lozenge, Modal, Field, Textarea } from "@/components/ui/primitives";
import { useApp } from "@/components/shell/app-context";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, invalidateIssueViews, qk, useComments, useHistory, useMeta, useWorklogs } from "@/lib/api/hooks";
import { cn, fmtDateTime, fmtDuration, fmtRelative, parseDuration } from "@/lib/utils";


function HistoryItem({ h, statusCategory }) {
  const meta = useMeta();
  const items = h.items;
  if (items.length === 1 && items[0].field === "created") {
    return (
      <div className="flex gap-3 py-2">
        <Avatar user={h.actor} size="md" />
        <div className="text-sm"><b>{h.actor?.name ?? "Sistema"}</b> creó la incidencia
          <div className="text-xs text-fg-subtlest">{fmtRelative(h.created_at)}</div></div>
      </div>
    );
  }
  return (
    <div className="flex gap-3 py-2">
      <Avatar user={h.actor} size="md" />
      <div className="min-w-0 flex-1 text-sm">
        {items.map((it, i) => {
          const name = it.field_name ?? choiceLabel(meta.data?.issue_fields, it.field);
          const time = fmtTime(it);
          return (
            <div key={i} className={cn(i > 0 && "mt-2")}>
              <b>{h.actor?.name ?? "Sistema"}</b> {verb(it)} <b>{name}</b>
              {i === 0 && <span className="ml-2 text-xs text-fg-subtlest">{fmtRelative(h.created_at)}</span>}
              {it.field !== "description" && (it.from_display || it.to_display) && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-fg-subtle">
                  {it.field === "status" ? (
                    <>
                      <Lozenge category={statusCategory(it.from)}>{it.from_display}</Lozenge>
                      <ArrowRight size={14} />
                      <Lozenge category={statusCategory(it.to)}>{it.to_display}</Lozenge>
                    </>
                  ) : (
                    <>
                      <span className={cn(!it.from_display && "italic text-fg-subtlest")}>{time?.from ?? it.from_display ?? "Ninguno"}</span>
                      <ArrowRight size={14} />
                      <span className={cn(!it.to_display && "italic text-fg-subtlest")}>{time?.to ?? it.to_display ?? "Ninguno"}</span>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function verb(it) {
  if (it.field === "attachment") return it.to_display ? "adjuntó un archivo" : "eliminó un adjunto";
  if (it.field === "link") return it.to_display ? "agregó un" : "quitó un";
  return "actualizó";
}

function fmtTime(it) {
  if (!["original_estimate", "remaining_estimate", "time_spent"].includes(it.field ?? "")) return null;
  const f = (v) => (v ? fmtDuration(Number(v)) : null);
  return { from: f(it.from), to: f(it.to) };
}

function CommentItem({ c, issueKey, projectKey, archived }) {
  const { me } = useApp();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const edit = useMutation({
    mutationFn: (body) => unwrap(api.PATCH("/api/v1/comments/{cid}", { params: { path: { cid: c.id } }, body: { body } })),
    onSuccess: () => { setEditing(false); qc.invalidateQueries({ queryKey: qk.comments(issueKey) }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const del = useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/comments/{cid}", { params: { path: { cid: c.id } } })),
    onSuccess: () => { setConfirm(false); qc.invalidateQueries({ queryKey: qk.comments(issueKey) }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="group flex gap-3 py-3">
      <Avatar user={c.author} size="md" />
      <div className="min-w-0 flex-1">
        <div className="text-sm"><b>{c.author?.name ?? "Usuario eliminado"}</b>
          <span className="ml-2 text-xs text-fg-subtlest" title={fmtDateTime(c.created_at)}>{fmtRelative(c.created_at)}</span>
          {c.edited && <span className="ml-1 text-xs text-fg-subtlest">· Editado</span>}</div>
        {editing ? (
          <div className="mt-1"><RichEditor value={c.body} projectKey={projectKey} saving={edit.isPending}
                                            onSave={(d) => d && edit.mutate(d)} onCancel={() => setEditing(false)} /></div>
        ) : (
          <>
            <div className="mt-1"><RichView doc={c.body} meId={me.id} /></div>
            <div className="mt-1 flex gap-3 text-xs font-medium text-fg-subtle">
              {c.can_edit && !archived && <button className="hover:underline" onClick={() => setEditing(true)}>Editar</button>}
              {c.can_delete && !archived && <button className="hover:underline" onClick={() => setConfirm(true)}>Eliminar</button>}
            </div>
          </>
        )}
      </div>
      <Confirm open={confirm} onOpenChange={setConfirm} danger title="¿Eliminar este comentario?"
               body="Una vez eliminado, desaparecerá para siempre." confirmLabel="Eliminar"
               loading={del.isPending} onConfirm={() => del.mutate()} />
    </div>
  );
}

function CommentBox({ issue }) {
  const { me } = useApp();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const add = useMutation({
    mutationFn: (body) => unwrap(api.POST("/api/v1/issues/{key}/comments", { params: { path: { key: issue.key } }, body: { body } })),
    onSuccess: () => {
      setOpen(false);
      qc.invalidateQueries({ queryKey: qk.comments(issue.key) });
      qc.invalidateQueries({ queryKey: qk.issue(issue.key) });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!issue.permissions.includes("add_comments") || issue.is_archived) return null;
  return (
    <div className="flex gap-3 py-3">
      <Avatar user={me} size="md" />
      <div className="min-w-0 flex-1">
        {open ? (
          <RichEditor projectKey={issue.project.key} placeholder="Agrega un comentario…" saving={add.isPending}
                      onSave={(d) => d && add.mutate(d)} onCancel={() => setOpen(false)} />
        ) : (
          <>
            <button data-comment-trigger onClick={() => setOpen(true)}
                    className="h-10 w-full rounded-[3px] border border-line px-3 text-left text-sm text-fg-subtlest hover:bg-bg-hover">
              Agrega un comentario…
            </button>
            <p className="mt-1.5 text-xs text-fg-subtlest"><b>Consejo:</b> pulsa <kbd className="rounded border border-line px-1">M</kbd> para comentar</p>
          </>
        )}
      </div>
    </div>
  );
}

function WorkLog({ issue }) {
  const qc = useQueryClient();
  const logs = useWorklogs(issue.key);
  const del = useMutation({
    mutationFn: (id) => unwrap(api.DELETE("/api/v1/worklogs/{wid}", { params: { path: { wid: id } } })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.worklogs(issue.key) }); invalidateIssueViews(qc, issue.key); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!logs.data?.length) return <p className="py-4 text-sm text-fg-subtlest">Aún no se registró trabajo.</p>;
  return (
    <div>
      {logs.data.map((w) => (
        <div key={w.id} className="flex gap-3 py-2">
          <Avatar user={w.author} size="md" />
          <div className="flex-1 text-sm">
            <b>{w.author?.name}</b> registró <b>{fmtDuration(w.time_spent)}</b>
            <span className="ml-2 text-xs text-fg-subtlest">{fmtDateTime(w.started_at)}</span>
            {w.comment && <p className="mt-1 whitespace-pre-wrap text-fg-subtle">{w.comment}</p>}
          </div>
          {!issue.is_archived && <button className="self-start text-xs text-fg-subtle hover:underline" onClick={() => del.mutate(w.id)}>Eliminar</button>}
        </div>
      ))}
    </div>
  );
}

export function LogWorkDialog({ issue, open, onOpenChange }) {
  const qc = useQueryClient();
  const [spent, setSpent] = useState("");
  const [remaining, setRemaining] = useState("");
  const [when, setWhen] = useState(() => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16));
  const [comment, setComment] = useState("");
  const [err, setErr] = useState(null);
  const save = useMutation({
    mutationFn: () => {
      const s = parseDuration(spent);
      if (!s) throw new Error("Formato inválido. Usa por ejemplo 2h 30m, 1d o 45m");
      const r = remaining ? parseDuration(remaining) : null;
      if (remaining && r === null) throw new Error("Estimación restante inválida");
      return unwrap(api.POST("/api/v1/issues/{key}/worklogs", { params: { path: { key: issue.key } },
        body: { time_spent: s, started_at: new Date(when).toISOString(), comment, remaining_estimate: r } }));
    },
    onSuccess: () => {
      onOpenChange(false); setSpent(""); setRemaining(""); setComment(""); setErr(null);
      qc.invalidateQueries({ queryKey: qk.worklogs(issue.key) });
      invalidateIssueViews(qc, issue.key);
    },
    onError: (e) => setErr(errorMessage(e)),
  });
  const spentNow = issue.time_spent + (parseDuration(spent) ?? 0);
  const est = issue.original_estimate ?? 0;
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Registro de tiempo" width={480}
           footer={<><Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button></>}>
      <div className="space-y-4">
        <TimeBar spent={spentNow} estimate={est} remaining={issue.remaining_estimate} />
        {err && <div className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tiempo empleado" hint="ej. 2w 4d 6h 45m"><Input autoFocus value={spent} onChange={(e) => setSpent(e.target.value)} /></Field>
          <Field label="Tiempo restante" hint="Vacío = se resta automáticamente"><Input value={remaining} onChange={(e) => setRemaining(e.target.value)} /></Field>
        </div>
        <Field label="Fecha de inicio"><Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
        <Field label="Descripción del trabajo"><Textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

export function TimeBar({ spent, estimate, remaining }) {
  const rem = remaining ?? Math.max(estimate - spent, 0);
  const total = Math.max(spent + rem, estimate, 1);
  return (
    <div>
      <div className="h-1.5 overflow-hidden rounded-full bg-bg-sunken">
        <div className={cn("h-full rounded-full", spent > estimate && estimate ? "bg-warning" : "bg-brand")}
             style={{ width: `${Math.min(100, (spent / total) * 100)}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-xs text-fg-subtle">
        <span>{spent ? `${fmtDuration(spent)} registrado` : "Sin tiempo registrado"}</span>
        <span>{rem ? `${fmtDuration(rem)} restante` : estimate ? "" : "Sin estimar"}</span>
      </div>
    </div>
  );
}

export function Activity({ issue, statusCategory }) {
  const [tab, setTab] = useState("comments");
  const comments = useComments(issue.key);
  const history = useHistory(issue.key, tab === "history" || tab === "all");
  const tabs = [["all", "Todo"], ["comments", "Comentarios"], ["history", "Historial"], ["worklog", "Registro de trabajo"]];

  const rows = [];
  if (tab === "all" || tab === "comments") comments.data?.forEach((c) => rows.push({ kind: "c", at: c.created_at, c }));
  if (tab === "all" || tab === "history") history.data?.forEach((h) => rows.push({ kind: "h", at: h.created_at, h }));
  rows.sort((a, b) => b.at.localeCompare(a.at));

  return (
    <section className="mt-8">
      <h2 className="mb-2 text-base font-semibold">Actividad</h2>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm text-fg-subtle">Mostrar:</span>
        {tabs.map(([v, l]) => (
          <Button key={v} size="sm" variant={tab === v ? "selected" : "default"} onClick={() => setTab(v)}>{l}</Button>
        ))}
      </div>
      {(tab === "comments" || tab === "all") && <CommentBox issue={issue} />}
      {tab === "worklog" ? <WorkLog issue={issue} /> : (
        <div className="divide-y divide-transparent">
          {rows.map((r) => r.kind === "c"
            ? <CommentItem key={`c${r.c.id}`} c={r.c} issueKey={issue.key} projectKey={issue.project.key} archived={issue.is_archived} />
            : <HistoryItem key={`h${r.h.id}`} h={r.h} statusCategory={statusCategory} />)}
          {!rows.length && !comments.isLoading && tab === "comments" && <p className="py-2 text-sm text-fg-subtlest">Aún no hay comentarios.</p>}
        </div>
      )}
    </section>
  );
}
