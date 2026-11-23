"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon, PriorityIcon } from "@/components/icons";
import { LabelPicker, UserPicker } from "@/components/issue/pickers";
import { Button } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Avatar, Checkbox, Field, Input, Lozenge, Modal, Tabs } from "@/components/ui/primitives";
import { ScreenForm, requiredErrors } from "@/components/fields/screen-form";
import { useApp } from "@/components/shell/app-context";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, invalidateIssueViews, useFieldRules, useMe, useMeta, useProjectMeta, useProjects } from "@/lib/api/hooks";
import { cfIdOf, fieldErrors, isEmptyValue, issueValue, toPatch } from "@/lib/fields";
import { editKeys, fieldCatalog, fieldLabel, quickCreateMissing, requiredKeys, screenFor } from "@/lib/screens";
import { cn } from "@/lib/utils";

const sel = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

export function BulkDialog({ open, onOpenChange, rows, onDone, only, title }) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={title ?? `Cambio masivo · ${rows.length} incidencias`} width={720}>
      {open && <BulkForm rows={rows} only={only} onClose={() => onOpenChange(false)} onDone={onDone} />}
    </Modal>
  );
}

function BulkForm({ rows, onClose, onDone, only }) {
  const qc = useQueryClient();
  const me = useMe();
  const appMeta = useMeta();
  const projectKeys = Array.from(new Set(rows.map((r) => r.project_key)));
  const single = projectKeys.length === 1 ? projectKeys[0] : undefined;
  const meta = useProjectMeta(single ?? projectKeys[0]);
  const [mode, setMode] = useState(only ?? "edit");
  const [notify, setNotify] = useState(true);
  const [result, setResult] = useState(null);

  // edit
  const [on, setOn] = useState({});
  const [assignee, setAssignee] = useState(null);
  const [assigneeUser, setAssigneeUser] = useState(null);
  const [priority, setPriority] = useState(null);
  const [addLabels, setAddLabels] = useState([]);
  const [removeLabels, setRemoveLabels] = useState([]);
  const [due, setDue] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [sprint, setSprint] = useState(null);
  // transition
  const [toStatus, setToStatus] = useState(null);
  const [resolution, setResolution] = useState(null);
  // move
  const [target, setTarget] = useState("");
  const [typeMap, setTypeMap] = useState({});
  const [statusMap, setStatusMap] = useState({});
  const [watch, setWatch] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState("");
  const [moveValues, setMoveValues] = useState({});
  const [moveErrors, setMoveErrors] = useState({});
  const [retryIds, setRetryIds] = useState(null);
  const moveRows = retryIds ? rows.filter((r) => retryIds.includes(r.id)) : rows;
  const moveScreen = useMoveRequired(moveRows, target, typeMap, moveErrors);
  const rules = useFieldRules(single);
  const catalog = fieldCatalog(rules.data, meta.data, appMeta.data);

  const statuses = useQuery({ queryKey: ["statuses"], queryFn: () => unwrap(api.GET("/api/v1/statuses")) });
  const resolutions = useQuery({ queryKey: ["resolutions"], queryFn: () => unwrap(api.GET("/api/v1/resolutions")) });
  const board = meta.data?.boards[0];
  const sprints = useQuery({
    queryKey: ["sprints", board?.id],
    queryFn: () => unwrap(api.GET("/api/v1/boards/{board_id}/sprints", { params: { path: { board_id: board.id } } })),
    enabled: !!single && !!board,
  });

  const run = useMutation({
    mutationFn: () => {
      const body = { issue_ids: retryIds ?? rows.map((r) => r.id), notify };
      if (mode === "edit") {
        const changes = {};
        if (on.assignee) changes.assignee = assignee;
        if (on.priority && priority) changes.priority = priority;
        if (on.due) changes.due_date = due || null;
        if (on.flagged) changes.flagged = flagged;
        if (on.sprint) changes.sprint = sprint;
        body.changes = changes;
        if (on.labels) { body.add_labels = addLabels; body.remove_labels = removeLabels; }
      } else if (mode === "transition") {
        body.transition_to_status_id = toStatus;
        body.resolution_id = resolution;
      } else if (mode === "move") {
        body.move = { project: target, type_map: typeMap, status_map: statusMap };
        const fields = Object.fromEntries(Object.entries(moveValues).filter(([, v]) => !isEmptyValue(v)));
        if (Object.keys(fields).length) body.move.fields = toPatch(fields);
      } else if (mode === "watch") {
        body.watch = watch;
      } else if (mode === "archive") {
        body.archive = true;
      } else {
        body.delete = true;
      }
      return unwrap(api.POST("/api/v1/issues/bulk", { body }));
    },
    onSuccess: (r) => {
      setResult(r);
      setRetryIds(null);
      invalidateIssueViews(qc);
      qc.invalidateQueries({ queryKey: ["search"] });
      if (!r.failed.length) { toast.success(rows.length === 1 ? "Listo" : `${r.updated.length} incidencias actualizadas`); onDone(r); onClose(); }
    },
    onError: (e) => {
      const fe = fieldErrors(e);
      if (mode === "move" && Object.keys(fe).length) setMoveErrors(fe);
      toast.error(errorMessage(e));
    },
  });

  const submitMove = () => {
    if (moveScreen) {
      const errs = requiredErrors(moveScreen, moveValues);
      setMoveErrors(errs);
      if (Object.keys(errs).length) return;
    }
    run.mutate();
  };

  // fields of the edit screen: types (of the selection) where a field can't be edited
  const notOnEdit = (key) => {
    if (!single || !rules.data) return [];
    const types = Array.from(new Map(rows.map((r) => [r.type.id, r.type])).values());
    return types.filter((t) => { const e = editKeys(rules.data, t.id); return e && !e.has(key); }).map((t) => t.name);
  };
  const requiredIn = (key) => {
    if (!single || !meta.data) return [];
    const types = Array.from(new Map(rows.map((r) => [r.type.id, r.type])).values());
    return types.filter((t) => requiredKeys(rules.data, meta.data, t.id).has(key)).map((t) => t.name);
  };
  const screenHint = (key, emptying) => {
    const off = notOnEdit(key);
    const req = emptying ? requiredIn(key) : [];
    const parts = [];
    if (off.length) parts.push(`No está en la pantalla de edición de ${off.join(", ")}: esas incidencias fallarán.`);
    if (req.length) parts.push(`Es obligatorio en ${req.join(", ")}: no se puede vaciar.`);
    return parts.length ? <p className="mt-1 text-xs text-warning">{parts.join(" ")}</p> : null;
  };

  const anyEdit = Object.values(on).some(Boolean);
  const canRun = mode === "edit" ? anyEdit
    : mode === "transition" ? !!toStatus
    : mode === "move" ? !!target && !projectKeys.every((k) => k === target)
    : mode === "delete" ? confirmDelete === "ELIMINAR" : true;

  const toggleRow = (k, label, control, disabled) => (
    <div className={cn("grid grid-cols-[180px_1fr] items-center gap-3 py-1.5", disabled && "opacity-50")}>
      <Checkbox checked={!!on[k]} disabled={!!disabled} onChange={(v) => setOn({ ...on, [k]: v })} label={label} />
      <div className={cn(!on[k] && "pointer-events-none opacity-60")}>{disabled ? <span className="text-xs text-fg-subtle">{disabled}</span> : control}</div>
    </div>
  );

  if (result?.failed.length) {
    // move: the destination asked for fields → offer to fill them and retry only those issues
    const missing = mode === "move" ? Array.from(new Set(result.failed.flatMap((f) => Object.keys(f.fields ?? {})))) : [];
    return (
      <div className="space-y-3 text-sm">
        <p><b>{result.updated.length}</b> incidencias actualizadas. <b className="text-danger">{result.failed.length}</b> no se pudieron cambiar:</p>
        <ul className="max-h-72 space-y-2 overflow-auto rounded-[3px] bg-bg-subtle p-2">
          {result.failed.map((f) => {
            const fields = f.fields && typeof f.fields === "object" ? Object.entries(f.fields) : [];
            return (
              <li key={String(f.key)}>
                <b>{String(f.key)}</b>: {fields.length ? null : String(f.message)}
                {fields.length > 0 && (
                  <ul className="ml-4 list-disc">
                    {fields.map(([k, m]) => <li key={k}><span className="font-medium">{fieldLabel(catalog, k)}</span>: {String(m)}</li>)}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
        <div className="flex justify-end gap-2">
          {missing.length > 0 && (
            <Button onClick={() => {
              const ids = rows.filter((r) => result.failed.some((f) => String(f.key) === r.key)).map((r) => r.id);
              setRetryIds(ids.length ? ids : null);
              setMoveErrors(Object.fromEntries(missing.map((k) => [k, `«${fieldLabel(catalog, k)}» es obligatorio en el destino`])));
              setResult(null);
            }}>Completar campos y reintentar</Button>
          )}
          <Button variant="primary" onClick={() => { onDone(result); onClose(); }}>Cerrar</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {!only && <Tabs value={mode} onChange={setMode} tabs={[
        { value: "edit", label: "Editar campos" }, { value: "transition", label: "Cambiar estado" },
        { value: "move", label: "Mover" }, { value: "watch", label: "Observar" }, { value: "archive", label: "Archivar" }, { value: "delete", label: "Eliminar" },
      ]} />}

      {mode === "edit" && (
        <div className="divide-y divide-line">
          {toggleRow("assignee", "Responsable",
            <div>
              <UserPicker meId={me.data?.id} value={assignee} onSelect={setAssignee} onPickUser={setAssigneeUser} projectKey={single} assignable={!!single}
                          trigger={<button className={sel}><Avatar user={assignee ? assigneeUser : null} size="xs" />{assignee ? assigneeUser?.name : "Sin asignar"}</button>} />
              {on.assignee && screenHint("assignee", !assignee)}
            </div>)}
          {toggleRow("priority", "Prioridad",
            <Picker value={priority} onSelect={setPriority} width={240}
                    options={(meta.data?.priorities ?? []).map((p) => ({ value: p.id, label: p.name, icon: <PriorityIcon priority={p} /> }))}
                    trigger={<button className={sel}>{meta.data?.priorities.find((p) => p.id === priority)?.name ?? "Elegir prioridad"}</button>} />)}
          {on.priority && screenHint("priority", false)}
          {toggleRow("labels", "Etiquetas", (
            <div className="grid grid-cols-2 gap-2">
              <LabelPicker value={addLabels} onChange={setAddLabels} projectKey={single}
                           trigger={<button className={sel}>{addLabels.length ? `Agregar: ${addLabels.join(", ")}` : "Agregar etiquetas"}</button>} />
              <LabelPicker value={removeLabels} onChange={setRemoveLabels} projectKey={single}
                           trigger={<button className={sel}>{removeLabels.length ? `Quitar: ${removeLabels.join(", ")}` : "Quitar etiquetas"}</button>} />
            </div>
          ))}
          {toggleRow("sprint", "Sprint",
            <Picker value={sprint ?? 0} onSelect={(v) => setSprint(v || null)} width={260}
                    options={[{ value: 0, label: "Backlog (sin sprint)" }, ...(sprints.data ?? []).filter((s) => s.state !== "closed").map((s) => ({ value: s.id, label: s.name, description: choiceLabel(appMeta.data?.sprint_states, s.state) }))]}
                    trigger={<button className={sel}>{sprints.data?.find((s) => s.id === sprint)?.name ?? "Backlog (sin sprint)"}</button>} />,
            single ? undefined : "Solo disponible si todas son del mismo proyecto")}
          {toggleRow("due", "Fecha de vencimiento", <div><Input type="date" className="h-8 w-44" value={due} onChange={(e) => setDue(e.target.value)} />{on.due && screenHint("due_date", !due)}</div>)}
          {toggleRow("flagged", "Impedimento", <Checkbox checked={flagged} onChange={setFlagged} label={flagged ? "Marcar como impedimento" : "Quitar impedimento"} />)}
        </div>
      )}

      {mode === "transition" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Nuevo estado" required hint="Se aplica la transición del flujo de cada incidencia; si no existe, esa incidencia falla.">
            <Picker value={toStatus} onSelect={setToStatus} width={280}
                    options={(statuses.data ?? []).map((s) => ({ value: s.id, label: s.name, icon: <Lozenge category={s.category}>{" "}</Lozenge> }))}
                    trigger={<button className={sel}>{statuses.data?.find((s) => s.id === toStatus)?.name ?? "Elegir estado"}</button>} />
          </Field>
          <Field label="Resolución (opcional)">
            <Picker value={resolution ?? 0} onSelect={(v) => setResolution(v || null)} width={260}
                    options={[{ value: 0, label: "Por defecto" }, ...(resolutions.data ?? []).map((r) => ({ value: r.id, label: r.name }))]}
                    trigger={<button className={sel}>{resolutions.data?.find((r) => r.id === resolution)?.name ?? "Por defecto"}</button>} />
          </Field>
        </div>
      )}

      {mode === "move" && <MoveForm rows={moveRows} target={target} setTarget={(v) => { setTarget(v); setMoveValues({}); setMoveErrors({}); }}
                                    typeMap={typeMap} setTypeMap={setTypeMap} statusMap={statusMap} setStatusMap={setStatusMap}
                                    values={moveValues} setValues={setMoveValues} errors={moveErrors} setErrors={setMoveErrors} askScreen={moveScreen} />}

      {mode === "watch" && (
        <div className="space-y-2">
          <Checkbox checked={watch} onChange={() => setWatch(true)} label="Empezar a observar estas incidencias" />
          <Checkbox checked={!watch} onChange={() => setWatch(false)} label="Dejar de observarlas" />
        </div>
      )}

      {mode === "archive" && (
        <p className="rounded-[3px] bg-bg-subtle p-3 text-sm">Las <b>{rows.length}</b> incidencias (y sus subtareas) quedarán de solo lectura y dejarán de verse en tableros, backlog y búsquedas. Un administrador del proyecto puede restaurarlas desde <i>Configuración → Incidencias archivadas</i>. Requiere ser administrador del proyecto.</p>
      )}

      {mode === "delete" && (
        <div className="space-y-3 rounded-[3px] bg-danger-subtle p-3 text-sm">
          <p>Se eliminarán <b>{rows.length}</b> incidencias con sus subtareas, comentarios y adjuntos. <b>No se puede deshacer.</b></p>
          <Field label='Escribe "ELIMINAR" para confirmar'><Input value={confirmDelete} onChange={(e) => setConfirmDelete(e.target.value)} className="w-48" /></Field>
        </div>
      )}

      <div className="flex items-center gap-3 border-t border-line pt-3">
        <Checkbox checked={notify} onChange={setNotify} label="Enviar notificaciones" />
        <div className="ml-auto flex gap-2">
          <Button variant="subtle" onClick={onClose}>Cancelar</Button>
          <Button variant={mode === "delete" ? "danger" : "primary"} disabled={!canRun} loading={run.isPending} onClick={() => (mode === "move" ? submitMove() : run.mutate())}>
            {mode === "delete" ? "Eliminar" : mode === "move" ? "Mover" : mode === "archive" ? "Archivar" : "Aplicar"} ({retryIds?.length ?? rows.length})
          </Button>
        </div>
      </div>
    </div>
  );
}

const AUTO = 0;

/*
 * Mirrors apps/issues/services.py (`_target_type` + `move_issue`) so the preview shows exactly
 * what the backend will do when nothing is mapped:
 *   type   → the same type if the target project has it, else its first type of the same level;
 *   status → the same status if the target type's workflow has it, else the workflow status of
 *            the same category with the lowest id, else the workflow's initial status.
 * `status_map` is keyed by source status only, so when issues sharing a status land in
 * different workflows we only offer statuses valid in all of them.
 */
/** Type an issue type becomes in the target project (same rule as the backend's `_target_type`). */
function targetTypeFor(t, tTypes, typeMap) {
  const opts = tTypes.filter((x) => x.level === t.level);
  return (typeMap[t.id] && opts.find((x) => x.id === typeMap[t.id])) || opts.find((x) => x.id === t.id) || opts[0];
}

/**
 * Required fields of the destination (its create_required per target type) that some of the
 * moved issues don't have, plus any field the backend reported missing (`errors`). The
 * backend applies `move.fields` to the moved issues.
 */
function useMoveRequired(rows, target, typeMap, errors) {
  const meta = useProjectMeta(target || undefined);
  const rules = useFieldRules(target || undefined);
  const appMeta = useMeta();
  if (!target || !meta.data || rules.isPending) return null;
  const types = Array.from(new Map(rows.map((r) => [r.type.id, r.type])).values());
  const required = new Map();
  for (const t of types) {
    const tt = targetTypeFor(t, meta.data.issue_types, typeMap);
    if (!tt) continue;
    const screen = screenFor(rules.data, meta.data, appMeta.data, tt.id, "create");
    const need = new Set(quickCreateMissing(rules.data, meta.data, tt.id));
    for (const f of screen.tabs.flatMap((x) => x.fields)) {
      if (!need.has(f.key)) continue;
      // only rows that carry the field (search results may not) count as lacking it
      const lacking = rows.some((r) => r.type.id === t.id && (cfIdOf(f.key) !== null ? r.custom_fields !== undefined : r[f.key] !== undefined)
        && isEmptyValue(issueValue(r, f.key)));
      if (lacking || errors[f.key]) required.set(f.key, { ...f, required: true, types: [...(required.get(f.key)?.types ?? []), tt.name] });
    }
  }
  const catalog = fieldCatalog(rules.data, meta.data, appMeta.data);
  for (const k of Object.keys(errors)) {
    const c = catalog.get(k);
    if (!required.has(k) && c) required.set(k, { key: k, label: c.label, custom: c.custom, required: true, description: "", types: [] });
  }
  if (!required.size) return null;
  const fields = [...required.values()].map((f) => ({
    ...f, description: f.types.length ? `Obligatorio en ${Array.from(new Set(f.types)).join(", ")} (${target})` : f.description,
  }));
  return { tabs: [{ id: "move", name: "", fields }], meta: meta.data };
}

function MoveForm({ rows, target, setTarget, typeMap, setTypeMap, statusMap, setStatusMap, values, setValues, errors, setErrors, askScreen }) {
  const projects = useProjects();
  const meta = useProjectMeta(target || undefined);
  const { me } = useApp();
  const types = Array.from(new Map(rows.map((r) => [r.type.id, r.type])).values());
  const sts = Array.from(new Map(rows.map((r) => [r.status.id, r.status])).values());
  const tTypes = meta.data?.issue_types ?? [];
  const tStatuses = meta.data?.statuses ?? [];
  const statusById = new Map(tStatuses.map((s) => [s.id, s]));
  const wfByType = new Map((meta.data?.issue_type_workflows ?? []).map((w) => [w.issue_type_id, w]));
  const typeOptions = (t) => tTypes.filter((x) => x.level === t.level);
  const targetType = (t) => targetTypeFor(t, tTypes, typeMap);
  const backendDefault = (s, wf) => {
    if (wf.status_ids.includes(s.id)) return s.id;
    const same = wf.status_ids.filter((id) => statusById.get(id)?.category === s.category).sort((a, b) => a - b);
    return same[0] ?? wf.initial_status_id;
  };
  const statusRows = sts.map((s) => {
    const wfs = Array.from(new Map(rows.filter((r) => r.status.id === s.id)
      .map((r) => wfByType.get(targetType(r.type)?.id)).filter(Boolean)
      .map((wf) => [wf.workflow_id, wf])).values());
    const allowed = wfs.length ? wfs[0].status_ids.filter((id) => wfs.every((wf) => wf.status_ids.includes(id))) : [];
    const defaults = Array.from(new Set(wfs.map((wf) => backendDefault(s, wf))));
    return { s, wfs, allowed, auto: defaults.length === 1 ? defaults[0] : null };
  });
  const pickType = (t, v) => { setTypeMap({ ...typeMap, [t.id]: v }); setStatusMap({}); };

  const pickStatus = (s, v, auto) => {
    const next = { ...statusMap };
    if (v === AUTO || v === auto) delete next[s.id];
    else next[s.id] = v;
    setStatusMap(next);
  };
  return (
    <div className="space-y-4">
      <Field label="Proyecto destino" required hint="Cada incidencia recibe una clave nueva; la clave anterior sigue funcionando. Las subtareas se mueven con su principal.">
        <Picker value={target} onSelect={(v) => { setTarget(v); setTypeMap({}); setStatusMap({}); }} width={320}
                options={(projects.data ?? []).map((p) => ({ value: p.key, label: `${p.name} (${p.key})` }))}
                trigger={<button className={cn(sel, "w-80")}>{projects.data?.find((p) => p.key === target)?.name ?? "Elegir proyecto"}</button>} />
      </Field>
      {target && meta.data && (
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold text-fg-subtle">Tipos de incidencia</h3>
            {types.map((t) => {
              const opts = typeOptions(t);
              const cur = targetType(t)?.id;
              return (
                <div key={t.id} className="mb-2 flex items-center gap-2 text-sm">
                  <span className="flex w-28 items-center gap-1.5"><IssueTypeIcon type={t} />{t.name}</span>→
                  <Picker value={cur ?? null} onSelect={(v) => pickType(t, v)} width={220}
                          options={opts.map((x) => ({ value: x.id, label: x.name, icon: <IssueTypeIcon type={x} /> }))}
                          trigger={<button className={cn(sel, "flex-1")}>{opts.find((x) => x.id === cur)?.name ?? <span className="text-danger">Sin tipo compatible</span>}</button>} />
                </div>
              );
            })}
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold text-fg-subtle">Estados</h3>
            {statusRows.map(({ s, wfs, allowed, auto }) => {
              const cur = statusMap[s.id] ?? auto ?? AUTO;
              const options = [
                ...(auto == null ? [{ value: AUTO, label: "Automático", description: "Según el flujo de cada tipo" }] : []),
                ...allowed.map((id) => statusById.get(id)).filter(Boolean)
                  .map((x) => ({ value: x.id, label: x.name, description: x.id === auto ? "Por defecto" : undefined })),
              ];
              return (
                <div key={s.id} className="mb-2 flex items-center gap-2 text-sm">
                  <span className="w-28"><Lozenge category={s.category}>{s.name}</Lozenge></span>→
                  <Picker value={cur} onSelect={(v) => pickStatus(s, v, auto)} width={240} options={options}
                          trigger={<button className={cn(sel, "flex-1")} disabled={!wfs.length}>
                            {cur === AUTO ? (wfs.length ? "Automático (según el flujo)" : <span className="text-fg-subtlest">Sin flujo destino</span>) : statusById.get(cur)?.name}
                          </button>} />
                </div>
              );
            })}
          </div>
        </div>
      )}
      {target && askScreen && (
        <div className="rounded-[3px] border border-line p-3">
          <h3 className="mb-1 text-sm font-semibold">Campos obligatorios en {target}</h3>
          <p className="mb-3 text-xs text-fg-subtle">Algunas incidencias no tienen estos campos y el destino los exige. El valor se aplica a las incidencias movidas.</p>
          <ScreenForm screen={askScreen} values={values} errors={errors}
                      ctx={{ projectKey: target, meta: askScreen.meta, me, typeLevel: 0 }}
                      onChange={(k, v) => { setValues({ ...values, [k]: v }); if (errors[k]) { const n = { ...errors }; delete n[k]; setErrors(n); } }} />
        </div>
      )}
    </div>
  );
}
