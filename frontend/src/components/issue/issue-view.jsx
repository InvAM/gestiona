"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown, ChevronRight, Copy, Eye, EyeOff, Flag, Link2, MoreHorizontal, MoveRight, Zap, Archive, Paperclip, Plus,
  Share2, ThumbsUp, Trash2, X, Clock, ExternalLink, Download, FileText,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { BulkDialog } from "@/components/search/bulk-dialog";
import { AiSummary } from "@/components/ai/ai";
import { toast } from "sonner";
import { IssueTypeIcon, PriorityIcon, ProjectAvatar } from "@/components/icons";
import { RichEditor, RichView } from "@/components/editor/rich-editor";
import { Button, PageSpinner } from "@/components/ui/button";
import {
  Avatar, Confirm, Field, Input, Lozenge, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger,
  Modal, Tip,
} from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { useApp } from "@/components/shell/app-context";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import {
  invalidateIssueViews, qk, uploadAttachments, useDeleteIssue, useFieldRules, useIssue, useMeta, useProjectMeta,
  useTransitions, useUpdateIssue,
} from "@/lib/api/hooks";
import { useProjectChannel } from "@/lib/realtime";
import { cn, fmtBytes, fmtDate, fmtDateTime, fmtPoints, fmtRelative } from "@/lib/utils";
import { Activity, LogWorkDialog } from "./activity";
import { useTransitionRunner } from "@/components/fields/transition-dialog";
import { ScreenForm, requiredErrors } from "@/components/fields/screen-form";
import { fieldErrors, isEmptyValue, issueValue, toPatch } from "@/lib/fields";
import { screenFor } from "@/lib/screens";
import { ScreenDetails, issueScreens } from "./issue-details";
import { IssuePicker } from "./pickers";

/* ------------------------------------------------------------------ inline editing helpers */

function InlineText({ value, onSave, className, inputClass, multiline, disabled, placeholder }) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value);
  const commit = () => { setEditing(false); if (v.trim() && v !== value) onSave(v.trim()); else setV(value); };
  if (editing && !disabled) {
    return multiline ? (
      <textarea autoFocus value={v} rows={2} onChange={(e) => setV(e.target.value)} onBlur={commit}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); } if (e.key === "Escape") { setV(value); setEditing(false); } }}
                className={cn("w-full resize-none rounded-[3px] border-2 border-focus bg-bg px-1.5 outline-none", inputClass)} />
    ) : (
      <input autoFocus value={v} onChange={(e) => setV(e.target.value)} onBlur={commit}
             onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") { setV(value); setEditing(false); } }}
             className={cn("w-full rounded-[3px] border-2 border-focus bg-bg px-1.5 outline-none", inputClass)} />
    );
  }
  return (
    <div role={disabled ? undefined : "button"} tabIndex={disabled ? undefined : 0}
         onClick={() => !disabled && setEditing(true)} onKeyDown={(e) => e.key === "Enter" && setEditing(true)}
         className={cn("rounded-[3px] px-1.5", !disabled && "cursor-text hover:bg-bg-hover", className)}>
      {value || <span className="text-fg-subtlest">{placeholder}</span>}
    </div>
  );
}

/* ------------------------------------------------------------------ status button */

function StatusButton({ issue }) {
  const can = issue.permissions.includes("transition_issues") && !issue.is_archived;
  const transitions = useTransitions(issue.key, can);
  const runner = useTransitionRunner();
  const [running, setRunning] = useState(false);
  const cat = issue.status.category;
  const color = cat === "done" ? "bg-success text-white hover:opacity-90" : cat === "in_progress" ? "bg-brand text-white hover:bg-brand-hover" : "";
  const go = async (t) => {
    setRunning(true);
    try { await runner.run(issue.key, t); } catch (e) { toast.error(errorMessage(e)); } finally { setRunning(false); }
  };
  return (
    <>
      <Menu>
        <MenuTrigger asChild disabled={!can}>
          <Button className={cn("font-semibold", color)} loading={running && !runner.busy}>
            {issue.status.name}<ChevronDown size={16} />
          </Button>
        </MenuTrigger>
        <MenuContent className="w-64">
          {transitions.data?.map((t) => (
            <MenuItem key={t.id} onSelect={() => go(t)}>
              <span className="flex-1 truncate">{t.name}</span>
              <ChevronRight size={14} className="text-fg-subtlest" />
              <Lozenge category={t.to.category}>{t.to.name}</Lozenge>
            </MenuItem>
          ))}
          {transitions.data && !transitions.data.length && <div className="px-3 py-2 text-sm text-fg-subtlest">No hay transiciones disponibles</div>}
        </MenuContent>
      </Menu>
      {runner.dialog}
    </>
  );
}

/* ------------------------------------------------------------------ sections */

function ChildIssues({ issue, meta }) {
  const { openCreate } = useApp();
  if (!issue.children.length) return null;
  const done = issue.children.filter((c) => c.status.category === "done").length;
  const pct = Math.round((done / issue.children.length) * 100);
  const isEpic = issue.type.level === 1;
  return (
    <section className="mt-6">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-base font-semibold">{isEpic ? "Incidencias secundarias" : "Subtareas"}</h2>
        {issue.permissions.includes("create_issues") && (
          <Tip content={isEpic ? "Crear incidencia secundaria" : "Crear subtarea"}>
            <Button variant="subtle" size="icon" onClick={() => openCreate({
              projectKey: issue.project.key, parentId: issue.id,
              issueTypeId: isEpic ? meta?.issue_types.find((t) => t.level === 0)?.id : meta?.issue_types.find((t) => t.level === -1)?.id,
            })}><Plus size={16} /></Button>
          </Tip>
        )}
      </div>
      <div className="mb-2 flex items-center gap-3">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-bg-sunken">
          <div className="h-full rounded-full bg-success transition-all" style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs font-semibold text-fg-subtle">{pct}% Listo</span>
      </div>
      <div className="overflow-hidden rounded-[3px] border border-line">
        {issue.children.map((c) => (
          <Link key={c.id} href={`/browse/${c.key}`}
                className="flex items-center gap-2 border-b border-line px-3 py-2 last:border-b-0 hover:bg-bg-hover">
            <IssueTypeIcon type={c.type} />
            <span className={cn("shrink-0 text-sm text-link", c.status.category === "done" && "line-through")}>{c.key}</span>
            <span className="min-w-0 flex-1 truncate text-sm">{c.summary}</span>
            {c.story_points && <span className="rounded-full bg-bg-sunken px-1.5 text-xs">{fmtPoints(c.story_points)}</span>}
            <PriorityIcon priority={c.priority} />
            <Avatar user={c.assignee} size="xs" />
            <Lozenge category={c.status.category}>{c.status.name}</Lozenge>
          </Link>
        ))}
      </div>
    </section>
  );
}

function LinkedIssues({ issue, meta, adding, setAdding }) {
  const qc = useQueryClient();
  const [linkType, setLinkType] = useState("");
  const link = useMutation({
    mutationFn: ({ target, typeId, direction }) =>
      unwrap(api.POST("/api/v1/issues/{key}/links", { params: { path: { key: issue.key } }, body: { target, link_type_id: typeId, direction } })),
    onSuccess: (data) => { qc.setQueryData(qk.issue(issue.key), data); invalidateIssueViews(qc, issue.key); setAdding(false); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const unlink = useMutation({
    mutationFn: (id) => unwrap(api.DELETE("/api/v1/links/{lid}", { params: { path: { lid: id } } })),
    onSuccess: () => invalidateIssueViews(qc, issue.key),
  });
  const delWeb = useMutation({
    mutationFn: (id) => unwrap(api.DELETE("/api/v1/weblinks/{wid}", { params: { path: { wid: id } } })),
    onSuccess: () => invalidateIssueViews(qc, issue.key),
  });
  const options = (meta?.link_types ?? []).flatMap((lt) => {
    const out = [{ value: `${lt.id}:outward`, label: lt.outward }];
    if (lt.inward !== lt.outward) out.push({ value: `${lt.id}:inward`, label: lt.inward });
    return out;
  });
  const selected = linkType || options[0]?.value || "";
  const groups = new Map();
  issue.links.forEach((l) => groups.set(l.label, [...(groups.get(l.label) ?? []), l]));
  if (!issue.links.length && !issue.web_links.length && !adding) return null;
  // Archived issues are read-only (backend answers 422 `archived`).
  const canLink = issue.permissions.includes("link_issues") && !issue.is_archived;
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-base font-semibold">Incidencias vinculadas</h2>
      {adding && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-[3px] border border-line p-2">
          <Picker value={selected} options={options} onSelect={setLinkType} width={240}
                  trigger={<Button>{options.find((o) => o.value === selected)?.label}<ChevronDown size={14} /></Button>} />
          <IssuePicker exclude={issue.key} placeholder="Buscar incidencia por clave o resumen"
                       onSelect={(t) => { const [id, dir] = selected.split(":"); link.mutate({ target: t.key, typeId: Number(id), direction: dir }); }}
                       trigger={<Button variant="primary" loading={link.isPending}>Elegir incidencia…</Button>} />
          <Button variant="subtle" onClick={() => setAdding(false)}>Cancelar</Button>
        </div>
      )}
      {[...groups.entries()].map(([label, links]) => (
        <div key={label} className="mb-3">
          <div className="mb-1 text-xs font-semibold text-fg-subtle">{label}</div>
          <div className="overflow-hidden rounded-[3px] border border-line">
            {links.map((l) => (
              <div key={l.id} className="group flex items-center gap-2 border-b border-line px-3 py-2 last:border-b-0 hover:bg-bg-hover">
                <IssueTypeIcon type={l.issue.type} />
                <Link href={`/browse/${l.issue.key}`} className={cn("text-sm text-link hover:underline", l.issue.status.category === "done" && "line-through")}>{l.issue.key}</Link>
                <span className="min-w-0 flex-1 truncate text-sm">{l.issue.summary}</span>
                <PriorityIcon priority={l.issue.priority} />
                <Avatar user={l.issue.assignee} size="xs" />
                <Lozenge category={l.issue.status.category}>{l.issue.status.name}</Lozenge>
                {canLink && <button aria-label="Quitar vínculo" onClick={() => unlink.mutate(l.id)} className="invisible rounded p-0.5 hover:bg-bg-pressed group-hover:visible"><X size={14} /></button>}
              </div>
            ))}
          </div>
        </div>
      ))}
      {issue.web_links.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 text-xs font-semibold text-fg-subtle">Enlaces web</div>
          {issue.web_links.map((w) => (
            <div key={w.id} className="group flex items-center gap-2 py-1">
              <ExternalLink size={14} className="text-fg-subtlest" />
              <a href={w.url} target="_blank" rel="noopener noreferrer nofollow" className="truncate text-sm text-link hover:underline">{w.title || w.url}</a>
              {canLink && <button aria-label="Quitar enlace" onClick={() => delWeb.mutate(w.id)} className="invisible rounded p-0.5 hover:bg-bg-pressed group-hover:visible"><X size={14} /></button>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Attachments({ issue }) {
  const qc = useQueryClient();
  const [preview, setPreview] = useState(null);
  const del = useMutation({
    mutationFn: (id) => unwrap(api.DELETE("/api/v1/attachments/{aid}", { params: { path: { aid: id } } })),
    onSuccess: () => invalidateIssueViews(qc, issue.key),
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!issue.attachments.length) return null;
  return (
    <section className="mt-6">
      <h2 className="mb-2 text-base font-semibold">Adjuntos <span className="text-fg-subtlest">({issue.attachments.length})</span></h2>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
        {issue.attachments.map((a) => {
          const isImg = a.mime_type.startsWith("image/");
          return (
            <div key={a.id} className="group overflow-hidden rounded-[3px] border border-line">
              <button className="flex h-24 w-full items-center justify-center bg-bg-sunken" onClick={() => isImg ? setPreview(a.url) : window.open(a.url, "_blank", "noopener")}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {isImg ? <img src={a.url} alt={a.filename} className="h-full w-full object-cover" /> : <FileText size={32} className="text-fg-subtlest" />}
              </button>
              <div className="flex items-center gap-1 px-2 py-1.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium" title={a.filename}>{a.filename}</div>
                  <div className="text-[11px] text-fg-subtlest">{fmtBytes(a.size)} · {fmtDate(a.created_at)}</div>
                </div>
                <a href={`${a.url}?inline=false`} aria-label="Descargar" className="rounded p-0.5 hover:bg-bg-hover"><Download size={14} /></a>
                {!issue.is_archived && <button aria-label="Eliminar adjunto" onClick={() => del.mutate(a.id)} className="rounded p-0.5 hover:bg-bg-hover"><Trash2 size={14} /></button>}
              </div>
            </div>
          );
        })}
      </div>
      <Modal open={!!preview} onOpenChange={() => setPreview(null)} width={1100}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {preview && <img src={preview} alt="Vista previa" className="mx-auto max-h-[75vh] object-contain" />}
      </Modal>
    </section>
  );
}

/* ------------------------------------------------------------------ main */

export function IssueView({ issueKey, mode = "page", onClose }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { me, openCreate } = useApp();
  const q = useIssue(issueKey);
  const issue = q.data;
  const meta = useProjectMeta(issue?.project.key);
  const fieldRules = useFieldRules(issue?.project.key);
  const appMeta = useMeta();
  const [typeChange, setTypeChange] = useState(null);
  useProjectChannel(issue?.project.id);
  const updateM = useUpdateIssue(issueKey);
  const del = useDeleteIssue();
  const [editingDesc, setEditingDesc] = useState(false);
  const [descError, setDescError] = useState(null);
  const [logOpen, setLogOpen] = useState(false);
  const [addingLink, setAddingLink] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const manualRules = useQuery({
    queryKey: ["manual-rules", issueKey],
    queryFn: () => unwrap(api.GET("/api/v1/issues/{key}/automation", { params: { path: { key: issueKey } } })),
    staleTime: 60_000,
  });
  const archive = useMutation({
    mutationFn: (on) => on
      ? unwrap(api.POST("/api/v1/issues/{key}/archive", { params: { path: { key: issueKey } } }))
      : unwrap(api.POST("/api/v1/issues/{key}/restore", { params: { path: { key: issueKey } } })),
    onSuccess: (i) => { toast.success(i.is_archived ? "Incidencia archivada" : "Incidencia restaurada"); invalidateIssueViews(qc, issueKey); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const runRule = useMutation({
    mutationFn: (id) => unwrap(api.POST("/api/v1/issues/{key}/automation/{rule_id}", { params: { path: { key: issueKey, rule_id: id } } })),
    onSuccess: (r) => {
      if (r.status === "success") toast.success(`Regla «${r.rule_name}» ejecutada`);
      else if (r.status === "no_match") toast.info(r.message || "La incidencia no cumple las condiciones");
      else toast.error(r.message || "La regla falló");
      invalidateIssueViews(qc, issueKey);
      qc.invalidateQueries({ queryKey: ["comments"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const [webLinkOpen, setWebLinkOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);
  const update = (p) => updateM.mutate(p);

  const upload = useMutation({
    mutationFn: (files) => uploadAttachments(issueKey, files),
    onSuccess: () => invalidateIssueViews(qc, issueKey),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const watch = useMutation({
    mutationFn: (on) => on
      ? unwrap(api.POST("/api/v1/issues/{key}/watchers", { params: { path: { key: issueKey }, query: {} } }))
      : unwrap(api.DELETE("/api/v1/issues/{key}/watchers", { params: { path: { key: issueKey }, query: {} } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.issue(issueKey) }),
  });
  const vote = useMutation({
    mutationFn: (on) => on
      ? unwrap(api.POST("/api/v1/issues/{key}/votes", { params: { path: { key: issueKey } } }))
      : unwrap(api.DELETE("/api/v1/issues/{key}/votes", { params: { path: { key: issueKey } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.issue(issueKey) }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const clone = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/issues/{key}/clone", { params: { path: { key: issueKey } }, body: {} })),
    onSuccess: (c) => { toast.success(`Se creó ${c.key}`); invalidateIssueViews(qc); router.push(`/browse/${c.key}`); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  // keyboard: "m" to comment, "e" edit description (only when not typing)
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target;
      if (t.isContentEditable || ["INPUT", "TEXTAREA"].includes(t.tagName) || e.metaKey || e.ctrlKey) return;
      if (e.key === "m") { (document.querySelector("[data-comment-trigger]"))?.click(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (q.isPending) return <PageSpinner />;
  if (q.error || !issue) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div className="p-10 text-center">
        <h2 className="text-xl font-medium">{notFound ? "No encontramos la incidencia" : "No se pudo cargar la incidencia"}</h2>
        <p className="mt-2 text-fg-subtle">{notFound ? "Puede que se haya eliminado o que no tengas permiso para verla." : errorMessage(q.error)}</p>
      </div>
    );
  }

  const can = issue.permissions.includes("edit_issues") && !issue.is_archived;
  const screens = fieldRules.isPending ? null : issueScreens(issue, meta.data, appMeta.data, fieldRules.data);
  const lockOf = (key) => (screens ? screens.canEditKey(key) : can ? null : "No tienes permiso para editar");
  const canType = !lockOf("issue_type") && !!meta.data;
  const descShown = screens ? screens.shows("description") : true;
  const descLock = lockOf("description");
  const changeType = (t) => {
    if (t.id === issue.type.id) return;
    // the new type's required fields of its edit screen must have a value (same PATCH)
    const s = screenFor(fieldRules.data, meta.data, appMeta.data, t.id, "edit");
    const missing = s.tabs.map((tab) => ({ ...tab, fields: tab.fields.filter((f) => f.required && isEmptyValue(issueValue(issue, f.key))) }))
      .filter((tab) => tab.fields.length);
    if (missing.length) setTypeChange({ type: t, screen: { ...s, tabs: missing } });
    else update({ issue_type: t.id });
  };
  const isAdmin = issue.permissions.includes("administer");
  // Archived issues are read-only: only viewing, restoring, deleting and «Dejar de observar».
  const live = !issue.is_archived;
  const canAttach = live && issue.permissions.includes("create_attachments");
  // History items carry the status id in `from`/`to`; renamed statuses still match.
  const statusCategory = (id) => meta.data?.statuses.find((s) => s.id === id)?.category ?? "todo";
  const copyLink = async () => {
    await navigator.clipboard.writeText(`${window.location.origin}/browse/${issue.key}`);
    toast.success("Enlace copiado");
  };

  return (
    <div className={cn("relative flex min-h-0 flex-1 flex-col", dragOver && "outline-2 outline-dashed outline-brand")}
         onDragOver={(e) => { if (e.dataTransfer.types.includes("Files") && canAttach) { e.preventDefault(); setDragOver(true); } }}
         onDragLeave={() => setDragOver(false)}
         onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = Array.from(e.dataTransfer.files); if (f.length && canAttach) upload.mutate(f); }}>
      {/* header */}
      <div className="flex items-center gap-2 px-6 pb-2 pt-5">
        <nav className="flex min-w-0 flex-1 items-center gap-1 text-sm text-fg-subtle">
          <ProjectAvatar project={issue.project} size={16} />
          <Link href={`/projects/${issue.project.key}`} className="truncate hover:underline">{issue.project.name}</Link>
          {issue.parent && (<>
            <span>/</span><IssueTypeIcon type={issue.parent.type} size={14} />
            <Link href={`/browse/${issue.parent.key}`} className="hover:underline">{issue.parent.key}</Link>
            {issue.parent.is_archived && <Lozenge category="todo" className="ml-1">Archivada</Lozenge>}
          </>)}
          <span>/</span>
          <Menu>
            <MenuTrigger asChild disabled={!canType}>
              <button className="rounded-[3px] p-0.5 hover:bg-bg-hover" aria-label={`Tipo: ${issue.type.name}`} title={lockOf("issue_type") ?? undefined}><IssueTypeIcon type={issue.type} size={14} /></button>
            </MenuTrigger>
            <MenuContent>
              {meta.data?.issue_types.filter((t) => (issue.type.level === -1 ? t.level === -1 : t.level !== -1)).map((t) => (
                <MenuItem key={t.id} onSelect={() => changeType(t)}><IssueTypeIcon type={t} />{t.name}</MenuItem>
              ))}
            </MenuContent>
          </Menu>
          <Link href={`/browse/${issue.key}`} className="hover:underline">{issue.key}</Link>
        </nav>
        {(live || issue.watching) && (
          <Tip content={issue.watching ? "Dejar de observar" : "Observar"}>
            <Button variant="subtle" size="sm" onClick={() => watch.mutate(!issue.watching)}>
              {issue.watching ? <Eye size={16} className="text-brand" /> : <EyeOff size={16} />}{issue.watcher_count}
            </Button>
          </Tip>
        )}
        {live ? (
          <Tip content={issue.voted ? "Quitar voto" : "Votar"}>
            <Button variant="subtle" size="sm" onClick={() => vote.mutate(!issue.voted)}>
              <ThumbsUp size={16} className={cn(issue.voted && "fill-brand text-brand")} />{issue.vote_count}
            </Button>
          </Tip>
        ) : !!issue.vote_count && <span className="flex items-center gap-1 px-2 text-sm text-fg-subtle"><ThumbsUp size={16} />{issue.vote_count}</span>}
        <Tip content="Copiar enlace"><Button variant="subtle" size="icon" onClick={copyLink}><Share2 size={16} /></Button></Tip>
        <Menu>
          <MenuTrigger asChild><Button variant="subtle" size="icon" aria-label="Más acciones"><MoreHorizontal size={18} /></Button></MenuTrigger>
          <MenuContent align="end">
            {live && issue.permissions.includes("log_work") && <MenuItem onSelect={() => setLogOpen(true)}><Clock size={16} />Registrar trabajo</MenuItem>}
            {can && <MenuItem onSelect={() => update({ flagged: !issue.flagged })}><Flag size={16} />{issue.flagged ? "Quitar marca" : "Agregar marca"}</MenuItem>}
            {live && issue.permissions.includes("create_issues") && <MenuItem onSelect={() => clone.mutate()}><Copy size={16} />Clonar</MenuItem>}
            <MenuItem onSelect={copyLink}><Link2 size={16} />Copiar enlace</MenuItem>
            {live && !!manualRules.data?.length && (<><MenuSeparator />
              {manualRules.data.map((r) => <MenuItem key={r.id} onSelect={() => runRule.mutate(r.id)}><Zap size={16} />{r.name}</MenuItem>)}</>)}
            {issue.permissions.includes("delete_issues") && issue.type.level !== -1 && !issue.is_archived && <MenuItem onSelect={() => setMoveOpen(true)}><MoveRight size={16} />Mover a otro proyecto</MenuItem>}
            {isAdmin && <MenuItem onSelect={() => archive.mutate(!issue.is_archived)}><Archive size={16} />{issue.is_archived ? "Restaurar" : "Archivar"}</MenuItem>}
            {issue.permissions.includes("delete_issues") && (<><MenuSeparator />
              <MenuItem danger onSelect={() => setConfirmDelete(true)}><Trash2 size={16} />Eliminar</MenuItem></>)}
          </MenuContent>
        </Menu>
        {mode === "modal" && (
          <>
            <Tip content="Abrir en página completa"><Button variant="subtle" size="icon" asChild><Link href={`/browse/${issue.key}`}><ExternalLink size={16} /></Link></Button></Tip>
            <Button variant="subtle" size="icon" aria-label="Cerrar" onClick={onClose}><X size={18} /></Button>
          </>
        )}
      </div>

      {issue.is_archived && (
        <div className="mx-6 mb-3 flex items-center gap-3 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">
          <Archive size={16} /><span>Esta incidencia está <b>archivada</b>{issue.archived_at && ` desde ${fmtDate(issue.archived_at)}`}: es de solo lectura y no aparece en tableros ni búsquedas.</span>
          {isAdmin && <Button size="sm" className="ml-auto" loading={archive.isPending} onClick={() => archive.mutate(false)}>Restaurar</Button>}
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 pb-10 lg:flex-row lg:overflow-hidden">
        {/* main column */}
        <div className="min-w-0 flex-[1.6] lg:overflow-y-auto lg:pr-4">
          {issue.flagged && (
            <div className="mb-3 flex items-center gap-2 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm"><Flag size={16} className="fill-warning text-warning" />Marcada como impedimento</div>
          )}
          <InlineText key={`sum-${issue.summary}`} value={issue.summary} disabled={!!lockOf("summary")} multiline onSave={(summary) => update({ summary })}
                      className="-ml-1.5 py-1 text-2xl font-medium leading-8" inputClass="text-2xl font-medium leading-8" />
          <div className="mt-3 flex flex-wrap gap-2">
            <AiSummary key={issue.key} issueKey={issue.key} />
            {canAttach && (
              <Button onClick={() => fileRef.current?.click()} loading={upload.isPending}><Paperclip size={16} />Adjuntar</Button>
            )}
            {live && issue.type.level >= 0 && issue.permissions.includes("create_issues") && (
              <Button onClick={() => openCreate({
                projectKey: issue.project.key, parentId: issue.id,
                issueTypeId: issue.type.level === 1 ? meta.data?.issue_types.find((t) => t.level === 0)?.id : meta.data?.issue_types.find((t) => t.level === -1)?.id,
              })}><Plus size={16} />{issue.type.level === 1 ? "Agregar incidencia secundaria" : "Agregar subtarea"}</Button>
            )}
            {live && issue.permissions.includes("link_issues") && (
              <Menu>
                <MenuTrigger asChild><Button><Link2 size={16} />Vincular<ChevronDown size={14} /></Button></MenuTrigger>
                <MenuContent>
                  <MenuItem onSelect={() => setAddingLink(true)}>Vincular incidencia</MenuItem>
                  <MenuItem onSelect={() => setWebLinkOpen(true)}>Enlace web</MenuItem>
                </MenuContent>
              </Menu>
            )}
            <input ref={fileRef} type="file" multiple hidden onChange={(e) => { const f = Array.from(e.target.files ?? []); if (f.length) upload.mutate(f); e.target.value = ""; }} />
          </div>

          {descShown && (
            <section className="mt-6">
              <h2 className="mb-1 text-base font-semibold">
                {screens?.view.tabs.flatMap((t) => t.fields).find((f) => f.key === "description")?.label ?? "Descripción"}
                {screens?.required.has("description") && <span className="ml-0.5 text-danger" aria-label="obligatorio">*</span>}
              </h2>
              {editingDesc ? (
                <>
                  <RichEditor value={issue.description} projectKey={issue.project.key} saving={updateM.isPending}
                              placeholder="Agrega una descripción…"
                              onSave={(d) => {
                                if (!d && screens?.required.has("description")) { setDescError("La descripción es obligatoria y no se puede vaciar"); return; }
                                setDescError(null);
                                updateM.mutate({ description: d }, { onSuccess: () => setEditingDesc(false) });
                              }}
                              onCancel={() => { setEditingDesc(false); setDescError(null); }} minHeight={180} />
                  {descError && <p role="alert" className="mt-1 text-xs text-danger">{descError}</p>}
                </>
              ) : (
                <div role={!descLock ? "button" : undefined} tabIndex={!descLock ? 0 : undefined} title={descLock && can ? descLock : undefined}
                     onClick={(e) => { if (e.target.closest("a")) return; if (!descLock) setEditingDesc(true); }}
                     onKeyDown={(e) => { if (e.key === "Enter" && !descLock && e.target === e.currentTarget) setEditingDesc(true); }}
                     className={cn("-mx-2 rounded-[3px] px-2 py-1", !descLock && "cursor-text hover:bg-bg-hover")}>
                  {issue.description ? <RichView doc={issue.description} meId={me.id} /> : <span className="text-sm text-fg-subtlest">{descLock ? "Sin descripción" : "Agrega una descripción…"}</span>}
                </div>
              )}
            </section>
          )}

          <ChildIssues issue={issue} meta={meta.data} />
          <LinkedIssues issue={issue} meta={meta.data} adding={addingLink} setAdding={setAddingLink} />
          <Attachments issue={issue} />
          <Activity issue={issue} statusCategory={statusCategory} />
        </div>

        {/* side column */}
        <aside className="min-w-0 flex-1 lg:max-w-[420px] lg:overflow-y-auto">
          <div className="mb-4 flex items-center gap-2">
            <StatusButton issue={issue} />
            {issue.resolution && <span className="text-sm text-fg-subtle">✓ {issue.resolution.name}</span>}
          </div>
          <ScreenDetails issue={issue} meta={meta.data} rules={screens} update={update} />
          <div className="mt-3 space-y-0.5 px-1 text-xs text-fg-subtlest">
            <div title={fmtDateTime(issue.created_at)}>Creada {fmtRelative(issue.created_at)}</div>
            <div title={fmtDateTime(issue.updated_at)}>Actualizada {fmtRelative(issue.updated_at)}</div>
            {issue.resolved_at && <div title={fmtDateTime(issue.resolved_at)}>Resuelta {fmtRelative(issue.resolved_at)}</div>}
          </div>
        </aside>
      </div>

      {typeChange && (
        <TypeChangeDialog issue={issue} meta={meta.data} change={typeChange} onClose={() => setTypeChange(null)}
                          onSave={(patch) => updateM.mutate(patch, { onSuccess: () => setTypeChange(null) })} saving={updateM.isPending} error={updateM.error} />
      )}
      <LogWorkDialog issue={issue} open={logOpen} onOpenChange={setLogOpen} />
      <BulkDialog open={moveOpen} onOpenChange={setMoveOpen} only="move" title={`Mover ${issue.key}`}
                  rows={[{ ...issue, project_key: issue.project.key }]}
                  onDone={(r) => { const k = r?.updated[0]; if (k && k !== issue.key) { if (mode === "modal") onClose?.(); router.push(`/browse/${k}`); } }} />
      <Confirm open={confirmDelete} onOpenChange={setConfirmDelete} danger confirmLabel="Eliminar"
               title={`¿Eliminar ${issue.key}?`} loading={del.isPending}
               body={<>Se eliminará la incidencia junto con sus comentarios, adjuntos y {issue.type.level === 0 ? "subtareas" : "registros"}. <b>Esta acción no se puede deshacer.</b> Si solo quieres cerrarla, cambia su estado.</>}
               onConfirm={() => del.mutate(issue.key, { onSuccess: () => { setConfirmDelete(false); toast.success(`${issue.key} eliminada`); if (onClose) onClose(); else router.push(`/projects/${issue.project.key}`); } })} />
      <WebLinkDialog issueKey={issue.key} open={webLinkOpen} onOpenChange={setWebLinkOpen} />
    </div>
  );
}

function WebLinkDialog({ issueKey, open, onOpenChange }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("https://");
  const [title, setTitle] = useState("");
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/issues/{key}/weblinks", { params: { path: { key: issueKey } }, body: { url, title } })),
    onSuccess: () => { onOpenChange(false); setUrl("https://"); setTitle(""); invalidateIssueViews(qc, issueKey); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Agregar enlace web" width={480}
           footer={<><Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>Vincular</Button></>}>
      <div className="space-y-3">
        <Field label="URL" required><Input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="Texto del enlace"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** Issue view inside a dialog (board/backlog/search: ?selectedIssue=KEY). */
export function IssueModal({ issueKey, onClose }) {
  return (
    <Modal open={!!issueKey} onOpenChange={(o) => !o && onClose()} width={1180} className="top-[4vh] h-[92vh] max-h-[92vh] [&>div]:px-0 [&>div]:py-0">
      {issueKey && <IssueView issueKey={issueKey} mode="modal" onClose={onClose} />}
    </Modal>
  );
}

/** Changing the type asks for the new type's required fields that the issue doesn't have yet. */
function TypeChangeDialog({ issue, meta, change, onClose, onSave, saving, error }) {
  const { me } = useApp();
  const [values, setValues] = useState({});
  const [errors, setErrors] = useState({});
  const shown = error ? { ...fieldErrors(error), ...errors } : errors;
  const submit = () => {
    const errs = requiredErrors(change.screen, values);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    onSave({ issue_type: change.type.id, ...toPatch(values) });
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} width={560}
           title={<span className="flex items-center gap-2">Cambiar a <IssueTypeIcon type={change.type} />{change.type.name}</span>}
           footer={<><Button variant="subtle" onClick={onClose}>Cancelar</Button><Button variant="primary" loading={saving} onClick={submit}>Cambiar tipo</Button></>}>
      <p className="mb-4 text-sm text-fg-subtle">«{change.type.name}» exige estos campos, que {issue.key} todavía no tiene:</p>
      <ScreenForm screen={change.screen} values={values} errors={shown} autoFocusFirst
                  ctx={{ projectKey: issue.project.key, meta, me, typeLevel: change.type.level, issueKey: issue.key }}
                  onChange={(k, v) => setValues((s) => ({ ...s, [k]: v }))} />
    </Modal>
  );
}
