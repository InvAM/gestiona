"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field, Input, Modal, Textarea } from "@/components/ui/primitives";
import { Picker } from "@/components/ui/picker";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { invalidateIssueViews } from "@/lib/api/hooks";
import { pluralize } from "@/lib/utils";

const toLocal = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
const DURATIONS = [
  { value: 7, label: "1 semana" }, { value: 14, label: "2 semanas" }, { value: 21, label: "3 semanas" },
  { value: 28, label: "4 semanas" }, { value: 0, label: "Personalizado" },
];

export function SprintFormDialog(props) {
  if (!props.open) return null;
  return <SprintForm key={props.sprint.id} {...props} />;
}

function SprintForm({ sprint, mode, issueCount, open, onOpenChange }) {
  const qc = useQueryClient();
  const [name, setName] = useState(sprint.name);
  const [goal, setGoal] = useState(sprint.goal);
  const [duration, setDuration] = useState(14);
  const [start, setStart] = useState(() => toLocal(sprint.start_date ? new Date(sprint.start_date) : new Date()));
  const [end, setEnd] = useState(() => toLocal(sprint.end_date ? new Date(sprint.end_date) : new Date(Date.now() + 14 * 864e5)));
  const [error, setError] = useState(null);
  const recompute = (s, d) => { if (d) setEnd(toLocal(new Date(new Date(s).getTime() + d * 864e5))); };

  const save = useMutation({
    mutationFn: () => {
      const body = { name, goal, start_date: new Date(start).toISOString(), end_date: new Date(end).toISOString() };
      return mode === "start"
        ? unwrap(api.POST("/api/v1/sprints/{sid}/start", { params: { path: { sid: sprint.id } }, body }))
        : unwrap(api.PATCH("/api/v1/sprints/{sid}", { params: { path: { sid: sprint.id } }, body }));
    },
    onSuccess: () => { onOpenChange(false); invalidateIssueViews(qc); toast.success(mode === "start" ? "Sprint iniciado" : "Sprint actualizado"); },
    onError: (e) => setError(errorMessage(e)),
  });

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={mode === "start" ? "Iniciar sprint" : `Editar sprint: ${sprint.name}`} width={560}
           footer={<><Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{mode === "start" ? "Iniciar" : "Actualizar"}</Button></>}>
      <div className="space-y-4">
        {mode === "start" && <p className="text-sm text-fg-subtle"><b>{pluralize(issueCount ?? 0, "incidencia", "incidencias")}</b> se incluirán en este sprint.</p>}
        {error && <div className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</div>}
        <Field label="Nombre del sprint" required><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></Field>
        {mode === "start" && (
          <Field label="Duración" required>
            <Picker value={duration} options={DURATIONS} onSelect={(d) => { setDuration(d); recompute(start, d); }} width={200}
                    trigger={<button className="flex h-8 w-48 items-center rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm">{DURATIONS.find((d) => d.value === duration)?.label}</button>} />
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Fecha de inicio" required><Input type="datetime-local" value={start} onChange={(e) => { setStart(e.target.value); if (mode === "start") recompute(e.target.value, duration); }} /></Field>
          <Field label="Fecha de fin" required><Input type="datetime-local" value={end} disabled={mode === "start" && duration !== 0} onChange={(e) => setEnd(e.target.value)} /></Field>
        </div>
        <Field label="Objetivo del sprint"><Textarea rows={3} value={goal} onChange={(e) => setGoal(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

export function CompleteSprintDialog({ sprint, issues, futureSprints, boardId, open, onOpenChange }) {
  const qc = useQueryClient();
  // counts come from the server so board filters don't skew them
  const report = useQuery({
    queryKey: ["sprint-report", sprint.id],
    queryFn: () => unwrap(api.GET("/api/v1/sprints/{sid}/report", { params: { path: { sid: sprint.id } } })),
    enabled: open,
  });
  const done = report.data?.completed.length ?? issues.filter((i) => i.status.category === "done").length;
  const open_ = report.data?.incomplete.length ?? issues.length - done;
  const [target, setTarget] = useState(0); // 0 backlog, -1 new sprint
  const complete = useMutation({
    mutationFn: async () => {
      let moveTo = target > 0 ? target : null;
      if (target === -1) {
        const s = await unwrap(api.POST("/api/v1/boards/{board_id}/sprints", { params: { path: { board_id: boardId } }, body: {} }));
        moveTo = s.id;
      }
      return unwrap(api.POST("/api/v1/sprints/{sid}/complete", { params: { path: { sid: sprint.id } }, body: { move_to_sprint_id: moveTo } }));
    },
    onSuccess: () => { onOpenChange(false); invalidateIssueViews(qc); toast.success(`${sprint.name} completado`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const opts = [{ value: 0, label: "Backlog" }, ...futureSprints.map((s) => ({ value: s.id, label: s.name })), { value: -1, label: "Nuevo sprint" }];
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={`Completar ${sprint.name}`} width={520}
           footer={<><Button variant="subtle" onClick={() => onOpenChange(false)}>Cancelar</Button>
             <Button variant="primary" loading={complete.isPending} onClick={() => complete.mutate()}>Completar sprint</Button></>}>
      <div className="space-y-4 text-sm">
        <p>Este sprint contiene:</p>
        <ul className="list-disc space-y-1 pl-5">
          <li><b>{pluralize(done, "incidencia completada", "incidencias completadas")}</b></li>
          <li><b>{pluralize(open_, "incidencia abierta", "incidencias abiertas")}</b></li>
        </ul>
        {open_ > 0 && (
          <Field label="Mover las incidencias abiertas a">
            <Picker value={target} options={opts} onSelect={setTarget} width={300}
                    trigger={<button className="flex h-8 w-72 items-center rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm">{opts.find((o) => o.value === target)?.label}</button>} />
          </Field>
        )}
        <p className="text-xs text-fg-subtlest">Las subtareas siguen a su incidencia principal. Las incidencias listas quedan registradas en el informe del sprint.</p>
      </div>
    </Modal>
  );
}
