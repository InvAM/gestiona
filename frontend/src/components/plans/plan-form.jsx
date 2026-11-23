"use client";

import { useQueries } from "@tanstack/react-query";
import { ChevronDown, Plus, X } from "lucide-react";
import { useState } from "react";
import { ProjectAvatar } from "@/components/icons";
import { UserPicker } from "@/components/issue/pickers";
import { JqlEditor } from "@/components/search/jql-editor";
import { Button } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { Avatar, Field, Input, Textarea } from "@/components/ui/primitives";
import { api, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta, useProjects } from "@/lib/api/hooks";
import { useSavePlan, useTeams } from "./api";
import { TeamDialog } from "./teams";

export const selectCls = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover";

function Chip({ children, onRemove, label }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-bg-sunken py-0.5 pl-0.5 pr-1.5 text-xs">
      {children}
      {onRemove && <button type="button" aria-label={`Quitar ${label}`} onClick={onRemove} className="rounded-full hover:bg-bg-pressed"><X size={12} /></button>}
    </span>
  );
}

/** Create / edit a plan: sources, access, estimation, iterations and teams. */
export function PlanForm({ plan, onSaved, onCancel, submitLabel = "Guardar" }) {
  const meta = useMeta();
  const projectsQ = useProjects();
  const teamsQ = useTeams("");
  const save = useSavePlan(plan);
  const [name, setName] = useState(plan?.name ?? "");
  const [description, setDescription] = useState(plan?.description ?? "");
  const [projects, setProjects] = useState(plan?.projects ?? []);
  const [jql, setJql] = useState(plan?.filter_jql ?? "");
  const [access, setAccess] = useState(plan?.access ?? "private");
  const [shared, setShared] = useState(plan?.shared_with ?? []);
  const [estimation, setEstimation] = useState(plan?.estimation ?? "story_points");
  const [days, setDays] = useState(plan?.iteration_days ?? 14);
  const [start, setStart] = useState(plan?.iteration_start ?? "");
  const [teams, setTeams] = useState(() => (plan?.teams ?? []).map((t) => ({ team_id: t.team_id, name: t.name, board_id: t.board_id })));
  const [creatingTeam, setCreatingTeam] = useState(false);
  const [error, setError] = useState(null);

  const boards = useQueries({
    queries: projects.map((p) => ({
      queryKey: ["plan-form-boards", p.key],
      queryFn: () => unwrap(api.GET("/api/v1/projects/{key}/boards", { params: { path: { key: p.key } } })),
      staleTime: 60_000,
    })),
  }).flatMap((q) => q.data ?? []);

  const allProjects = projectsQ.data ?? [];
  const toggleProject = (id) => {
    const p = allProjects.find((x) => x.id === id);
    if (!p) return;
    setProjects((ps) => (ps.some((x) => x.id === id) ? ps.filter((x) => x.id !== id) : [...ps, p]));
  };
  const toggleShared = (u) => u && setShared((us) => (us.some((x) => x.id === u.id) ? us.filter((x) => x.id !== u.id) : [...us, u]));
  const addTeam = (t) => setTeams((ts) => (ts.some((x) => x.team_id === t.id) ? ts : [...ts, { team_id: t.id, name: t.name, board_id: null }]));

  const submit = (e) => {
    e.preventDefault();
    setError(null);
    const keys = new Set(boards.map((b) => b.id));
    save.mutate({
      name, description, project_ids: projects.map((p) => p.id), filter_jql: jql, access,
      shared_with_ids: access === "shared" ? shared.map((u) => u.id) : [],
      estimation, iteration_days: Number(days) || 14, iteration_start: start || null,
      teams: teams.map((t) => ({ team_id: t.team_id, board_id: t.board_id && keys.has(t.board_id) ? t.board_id : null })),
    }, { onSuccess: (p) => onSaved?.(p), onError: (err) => setError(err.message) });
  };

  const accessChoices = meta.data?.plans.access ?? [];
  return (
    <>
    <form className="space-y-5" onSubmit={submit}>
      <Field label="Nombre" required><Input autoFocus={!plan} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Descripción"><Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>

      <fieldset className="space-y-3">
        <legend className="mb-1 text-sm font-semibold">Fuentes</legend>
        <Field label="Proyectos" hint={plan?.hidden_project_count ? `Además hay ${plan.hidden_project_count} proyecto(s) que no puedes ver; se conservan.` : "Las incidencias de estos proyectos forman el plan. Cada persona solo verá las de los proyectos a los que tiene acceso."}>
          <div className="flex flex-wrap items-center gap-1.5">
            {projects.map((p) => (
              <Chip key={p.id} label={p.name} onRemove={() => toggleProject(p.id)}><ProjectAvatar project={p} size={16} />{p.name}</Chip>
            ))}
            <Picker multiple value={projects.map((p) => p.id)} onSelect={toggleProject} placeholder="Buscar proyectos" loading={projectsQ.isFetching}
                    options={allProjects.map((p) => ({ value: p.id, label: p.name, description: p.key, icon: <ProjectAvatar project={p} size={20} /> }))}
                    trigger={<Button size="sm" type="button"><Plus size={14} />Añadir proyecto</Button>} />
          </div>
        </Field>
        <Field label="Filtro adicional (JQL)" hint="Opcional. Se aplica sobre los proyectos del plan, p. ej. «labels = q1».">
          <JqlEditor value={jql} onChange={setJql} />
        </Field>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="mb-1 text-sm font-semibold">Acceso</legend>
        <div className="space-y-1.5">
          {accessChoices.map((c) => (
            <label key={c.value} className="flex cursor-pointer items-start gap-2 text-sm">
              <input type="radio" name="plan-access" className="mt-1 accent-[var(--brand)]" checked={access === c.value} onChange={() => setAccess(c.value)} />
              <span><span className="font-medium">{c.label}</span>{c.description && <span className="block text-xs text-fg-subtle">{c.description}</span>}</span>
            </label>
          ))}
        </div>
        {access === "shared" && (
          <div className="flex flex-wrap items-center gap-1.5 pl-6">
            {shared.map((u) => <Chip key={u.id} label={u.name} onRemove={() => toggleShared(u)}><Avatar user={u} size="xs" />{u.name}</Chip>)}
            <UserPicker allowNone={false} multiple value={shared.map((u) => u.id)} onSelect={() => {}} onPickUser={toggleShared}
                        trigger={<Button size="sm" type="button"><Plus size={14} />Compartir con…</Button>} />
          </div>
        )}
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="mb-1 text-sm font-semibold">Capacidad</legend>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Estimación">
            <select className={selectCls} value={estimation} onChange={(e) => setEstimation(e.target.value)}>
              {(meta.data?.plans.estimations ?? []).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </Field>
          <Field label="Iteración fija (días)" hint="Para equipos sin sprints">
            <Input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} />
          </Field>
          <Field label="Primera iteración" hint={!start && plan ? `Por defecto: ${plan.iteration_anchor}` : "Por defecto, el lunes de la creación"}>
            <Input type="date" value={start ?? ""} onChange={(e) => setStart(e.target.value)} />
          </Field>
        </div>
        <Field label="Equipos" hint="Asocia un tablero Scrum para usar sus sprints como iteraciones; sin tablero se usan las iteraciones fijas del plan.">
          <div className="space-y-1.5">
            {teams.map((t) => (
              <div key={t.team_id} className="flex items-center gap-2">
                <span className="w-44 truncate text-sm font-medium">{t.name}</span>
                <select aria-label={`Iteraciones de ${t.name}`} className={selectCls + " max-w-xs"} value={t.board_id ?? ""}
                        onChange={(e) => setTeams((ts) => ts.map((x) => (x.team_id === t.team_id ? { ...x, board_id: e.target.value ? Number(e.target.value) : null } : x)))}>
                  <option value="">Iteraciones fijas del plan</option>
                  {boards.map((b) => <option key={b.id} value={b.id}>{b.project_key} · {b.name} ({choiceLabel(meta.data?.board_kinds, b.kind)})</option>)}
                </select>
                <Button size="icon-sm" variant="subtle" aria-label={`Quitar ${t.name}`} onClick={() => setTeams((ts) => ts.filter((x) => x.team_id !== t.team_id))}><X size={14} /></Button>
              </div>
            ))}
            <div className="flex gap-2">
              <Picker value={teams.map((t) => t.team_id)} multiple placeholder="Buscar equipos"
                      options={(teamsQ.data ?? []).map((t) => ({ value: t.id, label: t.name, description: t.members.map((m) => m.name).join(", ") }))}
                      onSelect={(id) => { const t = teamsQ.data?.find((x) => x.id === id); if (t) addTeam(t); }}
                      trigger={<Button size="sm" type="button"><Plus size={14} />Añadir equipo<ChevronDown size={12} /></Button>} />
              <Button size="sm" variant="subtle" onClick={() => setCreatingTeam(true)}>Crear equipo</Button>
            </div>
          </div>
        </Field>
      </fieldset>

      {error && <p role="alert" className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</p>}
      <div className="flex justify-end gap-2 pb-4">
        {onCancel && <Button type="button" variant="subtle" onClick={onCancel}>Cancelar</Button>}
        <Button type="submit" variant="primary" disabled={!name.trim()} loading={save.isPending}>{submitLabel}</Button>
      </div>
    </form>
    <TeamDialog open={creatingTeam} onOpenChange={setCreatingTeam} onSaved={addTeam} />
    </>
  );
}
