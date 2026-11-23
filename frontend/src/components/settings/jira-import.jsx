"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Download, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageSpinner } from "@/components/ui/button";
import { Avatar, Badge, Checkbox, EmptyState, Field, Input } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { cn, fmtRelative } from "@/lib/utils";

const RUNNING = new Set(["pending", "running"]);
const KEY_RE = /^[A-Z][A-Z0-9]{1,9}$/;

export function JiraImport() {
  const meta = useMeta();
  const [creds, setCreds] = useState({ base_url: "", email: "", token: "" });
  const [preview, setPreview] = useState(null);
  const [rows, setRows] = useState({});
  const [opts, setOpts] = useState({ attachments: true, history: true, create_users: true, web_links: false });
  const qc = useQueryClient();

  const connect = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/imports/jira/preview", { body: creds })),
    onSuccess: (p) => {
      setPreview(p);
      setRows(Object.fromEntries(p.projects.map((pr) => [pr.key, { selected: false, target_key: pr.exists ? "" : pr.key, target_name: pr.name, access: "limited" }])));
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const start = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/imports/jira", { body: {
      ...creds, options: { ...opts, max_attachment_mb: 200 },
      projects: Object.entries(rows).filter(([, r]) => r.selected).map(([key, r]) => ({ key, target_key: r.target_key, target_name: r.target_name, access: r.access })),
    } })),
    onSuccess: () => {
      toast.success("Importación iniciada");
      setPreview(null); setRows({}); setCreds((c) => ({ ...c, token: "" }));
      qc.invalidateQueries({ queryKey: ["imports"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const selected = Object.entries(rows).filter(([, r]) => r.selected);
  const invalid = selected.some(([, r]) => !KEY_RE.test(r.target_key));
  const upd = (key, patch) => setRows((r) => ({ ...r, [key]: { ...r[key], ...patch } }));

  return (
    <div className="max-w-[920px] space-y-8">
      <section className="rounded-[3px] border border-line p-5">
        <h2 className="text-lg font-medium">1. Conectar con Jira</h2>
        <p className="mt-1 text-sm text-fg-subtle">
          Jira Cloud: usa tu email y un <a className="text-link hover:underline" target="_blank" rel="noreferrer" href="https://id.atlassian.com/manage-profile/security/api-tokens">token de API de Atlassian</a>.
          Jira Server / Data Center: deja el email vacío y usa un token de acceso personal. El token solo se guarda mientras dura la importación.
        </p>
        <form className="mt-4 grid gap-4 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); connect.mutate(); }}>
          <Field label="URL del sitio" required><Input placeholder="https://empresa.atlassian.net" value={creds.base_url} onChange={(e) => setCreds({ ...creds, base_url: e.target.value })} /></Field>
          <Field label="Email (Cloud)"><Input type="email" autoComplete="off" value={creds.email} onChange={(e) => setCreds({ ...creds, email: e.target.value })} /></Field>
          <Field label="Token" required><Input type="password" autoComplete="new-password" value={creds.token} onChange={(e) => setCreds({ ...creds, token: e.target.value })} /></Field>
          <div className="sm:col-span-3"><Button type="submit" variant="primary" loading={connect.isPending} disabled={!creds.base_url || !creds.token}>Conectar</Button></div>
        </form>
      </section>

      {preview && (
        <section className="rounded-[3px] border border-line p-5">
          <h2 className="text-lg font-medium">2. Elegir proyectos</h2>
          <p className="mt-1 text-sm text-fg-subtle">Conectado como <b>{preview.account}</b> ({preview.deployment === "cloud" ? "Jira Cloud" : "Jira Server / Data Center"}). {preview.projects.length} proyectos visibles.</p>
          {preview.projects.length === 0 ? <p className="mt-4 text-sm">La cuenta no ve ningún proyecto.</p> : (
            <table className="mt-4 w-full text-sm">
              <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle">
                <th className="w-8 py-2" /><th className="py-2">Proyecto en Jira</th><th className="py-2">Clave en Gestiona</th><th className="py-2">Nombre en Gestiona</th><th className="py-2">Acceso</th></tr></thead>
              <tbody>
                {preview.projects.map((p) => {
                  const r = rows[p.key];
                  const bad = r.selected && !KEY_RE.test(r.target_key);
                  return (
                    <tr key={p.key} className="border-b border-line align-top">
                      <td className="py-2"><Checkbox checked={r.selected} onChange={(v) => upd(p.key, { selected: v })} /></td>
                      <td className="py-2"><b>{p.key}</b> · {p.name}{p.exists && <div className="text-xs text-warning">La clave {p.key} ya existe en Gestiona: elige otra</div>}</td>
                      <td className="py-2"><Input className={cn("h-8 w-28 uppercase", bad && "border-danger")} value={r.target_key} onChange={(e) => upd(p.key, { target_key: e.target.value.toUpperCase(), selected: true })} /></td>
                      <td className="py-2"><Input className="h-8" value={r.target_name} onChange={(e) => upd(p.key, { target_name: e.target.value })} /></td>
                      <td className="py-2">
                        <select className="h-8 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-sm" value={r.access} onChange={(e) => upd(p.key, { access: e.target.value })}>
                          {(meta.data?.project_access ?? []).map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <div className="mt-5 grid gap-2 sm:grid-cols-2">
            <Checkbox checked={opts.attachments} onChange={(v) => setOpts({ ...opts, attachments: v })} label="Descargar adjuntos (hasta 200 MB por archivo)" />
            <Checkbox checked={opts.history} onChange={(v) => setOpts({ ...opts, history: v })} label="Importar historial de cambios" />
            <Checkbox checked={opts.create_users} onChange={(v) => setOpts({ ...opts, create_users: v })} label="Crear usuarios inactivos para quienes no existan" />
            <Checkbox checked={opts.web_links} onChange={(v) => setOpts({ ...opts, web_links: v })} label="Importar enlaces web (más lento)" />
          </div>
          <p className="mt-3 text-xs text-fg-subtle">Las personas se emparejan por email (o por nombre si Jira oculta el email). Los usuarios creados quedan inactivos: actívalos o invítalos desde Usuarios.</p>
          <div className="mt-4 flex items-center gap-3">
            <Button variant="primary" disabled={!selected.length || invalid} loading={start.isPending} onClick={() => start.mutate()}>
              <Download size={16} />Importar {selected.length || ""} {selected.length === 1 ? "proyecto" : "proyectos"}
            </Button>
            {invalid && <span className="text-xs text-danger">Clave inválida: 2 a 10 caracteres A-Z/0-9, empezando con letra.</span>}
          </div>
        </section>
      )}

      <ImportHistory />
    </div>
  );
}

function ImportHistory() {
  const jobs = useQuery({
    queryKey: ["imports"],
    queryFn: () => unwrap(api.GET("/api/v1/imports")),
    refetchInterval: (q) => (q.state.data?.some((j) => RUNNING.has(j.state)) ? 2000 : false),
  });
  if (jobs.isPending) return <PageSpinner />;
  return (
    <section>
      <h2 className="text-lg font-medium">Importaciones</h2>
      {!jobs.data?.length ? <EmptyState title="Sin importaciones todavía" body="Conecta tu Jira para traer proyectos, incidencias, sprints, comentarios y adjuntos." /> : (
        <div className="mt-3 space-y-3">{jobs.data.map((j) => <JobCard key={j.id} job={j} />)}</div>
      )}
    </section>
  );
}

const STAGE = {
  queued: "En cola", project: "Preparando proyecto", issues: "Importando incidencias",
  links: "Creando vínculos", finished: "Terminado",
};

function JobCard({ job }) {
  const [open, setOpen] = useState(RUNNING.has(job.state));
  const p = job.progress;
  const pct = p.total ? Math.min(100, Math.round(((p.done ?? 0) / p.total) * 100)) : 0;
  const icon = job.state === "done" ? <CheckCircle2 size={18} className="text-success" />
    : job.state === "failed" ? <XCircle size={18} className="text-danger" />
    : job.state === "partial" ? <AlertTriangle size={18} className="text-warning" /> : null;
  const results = job.result;
  const logs = job.log;
  return (
    <div className="rounded-[3px] border border-line">
      <button className="flex w-full items-center gap-3 p-3 text-left hover:bg-bg-hover" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {icon}
        <span className="font-medium">{job.projects.map((x) => x.key).join(", ")}</span>
        <span className="text-xs text-fg-subtle">{job.base_url.replace(/^https?:\/\//, "")}</span>
        <Badge className="ml-auto">{job.state_display}</Badge>
        {job.created_by && <Avatar user={job.created_by} />}
        <span className="text-xs text-fg-subtle">{fmtRelative(job.created_at)}</span>
      </button>
      {RUNNING.has(job.state) && (
        <div className="px-3 pb-3">
          <div className="mb-1 text-xs text-fg-subtle">{STAGE[p.stage ?? "queued"] ?? p.stage} {p.project && `· ${p.project}`} {p.total ? `· ${p.done ?? 0} de ${p.total}` : ""}</div>
          <div className="h-2 overflow-hidden rounded-full bg-bg-sunken"><div className="h-full bg-brand transition-all" style={{ width: `${pct}%` }} /></div>
        </div>
      )}
      {open && (
        <div className="space-y-3 border-t border-line p-3 text-sm">
          {job.error && <div className="rounded-[3px] bg-danger-subtle px-3 py-2">{job.error}</div>}
          {results.length > 0 && (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-fg-subtle"><th className="py-1">Proyecto</th><th>Incidencias</th><th>Comentarios</th><th>Registros de trabajo</th><th>Adjuntos</th><th>Sprints</th><th /></tr></thead>
              <tbody>{results.map((r) => (
                <tr key={r.key} className="border-t border-line">
                  <td className="py-1.5">{r.ok ? <Link className="text-link hover:underline" href={`/projects/${r.target_key}`}>{r.key} → {r.target_key}</Link> : <span>{r.key}</span>}</td>
                  <td>{r.issues}</td><td>{r.comments}</td><td>{r.worklogs}</td><td>{r.attachments}</td><td>{r.sprints}</td>
                  <td className="text-xs text-danger">{r.error}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
          {p.users_created ? <p className="text-xs text-fg-subtle">{p.users_created} usuarios creados como inactivos. <Link className="text-link hover:underline" href="/settings/users">Revisar usuarios</Link></p> : null}
          {logs.length > 0 && (
            <ul className="max-h-60 space-y-0.5 overflow-auto rounded-[3px] bg-bg-subtle p-2 font-mono text-xs">
              {logs.map((l, i) => <li key={i} className={cn(l.level === "error" && "text-danger", l.level === "warning" && "text-warning")}>{l.message}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
