"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";

export function useAiEnabled() {
  const q = useQuery({ queryKey: ["ai-status"], queryFn: () => unwrap(api.GET("/api/v1/ai/status")), staleTime: 10 * 60_000 });
  return !!q.data?.enabled;
}

const NOTE = "Generado con IA: revísalo antes de usarlo.";

/** "Resumir con IA" button + result panel on the issue view. */
export function AiSummary({ issueKey }) {
  const on = useAiEnabled();
  const [data, setData] = useState(null);
  const run = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/ai/issues/{key}/summary", { params: { path: { key: issueKey } } })),
    onSuccess: setData,
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!on) return null;
  if (!data) return <Button loading={run.isPending} onClick={() => run.mutate()}><Sparkles size={16} className="text-discovery" />Resumir con IA</Button>;
  const list = (title, items) => items.length > 0 && (
    <div className="mt-2"><div className="text-xs font-semibold text-fg-subtle">{title}</div>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-5">{items.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
  );
  return (
    <div className="w-full rounded-[3px] border border-discovery/40 bg-discovery-subtle p-3 text-sm">
      <div className="flex items-center gap-2"><Sparkles size={16} className="text-discovery" /><b>Resumen de IA</b>
        <Button size="sm" variant="subtle" className="ml-auto" loading={run.isPending} onClick={() => run.mutate()}>Regenerar</Button>
        <Button size="icon" variant="subtle" aria-label="Cerrar resumen" onClick={() => setData(null)}><X size={14} /></Button></div>
      <p className="mt-2">{data.summary}</p>
      {list("Puntos clave", data.key_points)}
      {list("Preguntas abiertas", data.open_questions)}
      {list("Próximos pasos", data.next_steps)}
      <p className="mt-2 text-[11px] text-fg-subtle">{NOTE}</p>
    </div>
  );
}

function para(text) {
  return text ? { type: "paragraph", content: [{ type: "text", text }] } : { type: "paragraph" };
}

export function draftToDoc(d) {
  const content = d.description.split(/\n+/).map((t) => para(t.trim())).filter((n) => n.content);
  if (d.acceptance_criteria.length) {
    content.push({ type: "heading", attrs: { level: 3 }, content: [{ type: "text", text: "Criterios de aceptación" }] });
    content.push({ type: "taskList", content: d.acceptance_criteria.map((t) => ({ type: "taskItem", attrs: { checked: false }, content: [para(t)] })) });
  }
  if (d.subtasks.length) {
    content.push({ type: "heading", attrs: { level: 3 }, content: [{ type: "text", text: "Subtareas sugeridas" }] });
    content.push({ type: "bulletList", content: d.subtasks.map((t) => ({ type: "listItem", content: [para(t)] })) });
  }
  return { type: "doc", content };
}

/** "Redactar con IA" in the create dialog: fills the description from the summary. */
export function AiDraftButton({ projectKey, issueTypeId, summary, onDraft }) {
  const on = useAiEnabled();
  const run = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/ai/draft", { body: { project: projectKey, issue_type_id: issueTypeId, summary } })),
    onSuccess: (d) => { onDraft(draftToDoc(d)); toast.success(NOTE); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!on || !projectKey || !issueTypeId) return null;
  return (
    <Button type="button" size="sm" variant="subtle" disabled={summary.trim().length < 4} loading={run.isPending} onClick={() => run.mutate()}>
      <Sparkles size={14} className="text-discovery" />Redactar con IA
    </Button>
  );
}

/** Natural-language search box that turns a question into JQL. */
export function AskJql({ projectKey, onJql }) {
  const on = useAiEnabled();
  const [q, setQ] = useState("");
  const [explanation, setExplanation] = useState(null);
  const run = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/ai/jql", { body: { question: q, project: projectKey } })),
    onSuccess: (r) => { setExplanation(r.explanation); onJql(r.jql); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!on) return null;
  return (
    <form className="mt-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) run.mutate(); }}>
      <div className="flex items-center gap-2">
        <Sparkles size={16} className="shrink-0 text-discovery" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Pregunta en lenguaje natural, p. ej. «errores críticos sin asignar de esta semana»" />
        <Button type="submit" size="sm" loading={run.isPending} disabled={!q.trim()}>Buscar con IA</Button>
      </div>
      {explanation && <p className="mt-1 pl-6 text-xs text-fg-subtle">{explanation}</p>}
    </form>
  );
}
