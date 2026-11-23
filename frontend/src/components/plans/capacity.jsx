"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RotateCcw, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageSpinner } from "@/components/ui/button";
import { EmptyState, Tip } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { choiceLabel, useMeta } from "@/lib/api/hooks";
import { cn, fmtDate } from "@/lib/utils";
import { planKeys, usePlanCapacity } from "./api";
import { selectCls } from "./plan-form";

const fmt = (n) => (n === null || n === undefined ? "—" : Number.isInteger(n) ? String(n) : n.toFixed(1));

/** Thin meter: assigned against capacity. The fill turns to the danger status (with icon
 *  and label beside it) when the team is overloaded; the tick marks the capacity. */
function Meter({ assigned, capacity, over }) {
  const scale = Math.max(assigned, capacity ?? 0) || 1;
  const pct = capacity ? Math.round((assigned / capacity) * 100) : null;
  return (
    <Tip content={capacity !== null ? `${fmt(assigned)} de ${fmt(capacity)} (${pct}%)` : `${fmt(assigned)} asignado · sin capacidad definida`}>
      <div role="meter" aria-valuemin={0} aria-valuemax={capacity ?? undefined} aria-valuenow={assigned}
           aria-label={capacity !== null ? `${fmt(assigned)} de ${fmt(capacity)}` : `${fmt(assigned)} asignado`}
           className={cn("relative h-2 w-full rounded-full", over ? "bg-danger-subtle" : "bg-brand-subtle")}>
        <div className={cn("absolute inset-y-0 left-0 rounded-full", over ? "bg-danger" : "bg-brand")} style={{ width: `${(assigned / scale) * 100}%` }} />
        {capacity !== null && capacity > 0 && (
          <div className="absolute -top-1 h-4 w-0.5 rounded bg-fg" style={{ left: `calc(${(capacity / scale) * 100}% - 1px)` }} />
        )}
      </div>
    </Tip>
  );
}

function CapacityInput({ value, overridden, disabled, onCommit, label }) {
  const [draft, setDraft] = useState(null);
  const shown = draft ?? (value ?? "");
  const commit = () => {
    if (draft === null) return;
    const next = draft === "" ? null : Number(draft);
    setDraft(null);
    if (next !== value && !(next !== null && Number.isNaN(next))) onCommit(next);
  };
  return (
    <input type="number" min={0} step="0.5" aria-label={label} disabled={disabled} value={shown}
           onChange={(e) => setDraft(e.target.value)} onBlur={commit}
           onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setDraft(null); }}
           className={cn("h-7 w-20 rounded-[3px] border-2 border-line bg-bg-subtle px-1.5 text-right text-sm tabular-nums outline-none hover:bg-bg-hover focus:border-focus focus:bg-bg disabled:border-transparent disabled:bg-transparent",
                         overridden && "font-semibold")} />
  );
}

export function PlanCapacity({ plan }) {
  const meta = useMeta();
  const qc = useQueryClient();
  const [iterations, setIterations] = useState(8);
  const cap = usePlanCapacity(plan.id, iterations);
  const save = useMutation({
    mutationFn: (body) => unwrap(api.PUT("/api/v1/plans/{pid}/capacity", { params: { path: { pid: plan.id }, query: { iterations } }, body })),
    onSuccess: (d) => qc.setQueryData(planKeys.capacity(plan.id, iterations), d),
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (cap.isPending) return <PageSpinner />;
  if (cap.error) return <p className="px-6 py-4 text-sm text-danger">{errorMessage(cap.error)}</p>;
  const unitLabel = choiceLabel(meta.data?.plans.estimations, cap.data.unit);
  const modeLabel = (m) => choiceLabel(meta.data?.plans.capacity_modes, m);
  const anyFixed = cap.data.teams.some((t) => t.mode === "fixed");

  if (!cap.data.teams.length) {
    return (
      <EmptyState icon={<Users size={40} />} title="Este plan no tiene equipos"
                  body={plan.can_edit ? "Añade equipos en «Configuración» y asigna incidencias a cada equipo desde el cronograma." : "El propietario del plan todavía no ha añadido equipos."}
                  action={<Button asChild><Link href="/plans/teams">Ver equipos</Link></Button>} />
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-8">
      <div className="flex flex-wrap items-center gap-3 pb-3 text-sm text-fg-subtle">
        <span>Unidad: <b className="text-fg">{unitLabel}</b>. Se suma lo asignado a cada equipo en cada iteración y se compara con su capacidad{plan.can_edit ? "; puedes sobrescribirla en cada iteración" : ""}.</span>
        {anyFixed && (
          <label className="ml-auto flex items-center gap-2">Iteraciones fijas a mostrar
            <select className={cn(selectCls, "h-7 w-20")} value={iterations} onChange={(e) => setIterations(Number(e.target.value))}>
              {[4, 8, 12, 26].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        )}
      </div>
      {cap.data.filter_error && <p className="mb-3 rounded-[3px] bg-warning-subtle px-3 py-2 text-sm">El filtro JQL del plan no se puede aplicar con tus permisos: {cap.data.filter_error}</p>}
      <div className="space-y-6">
        {cap.data.teams.map((t) => {
          const overCount = t.iterations.filter((i) => i.over).length;
          return (
            <section key={t.team.id} className="rounded-[3px] border border-line">
              <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-3">
                <h2 className="text-base font-semibold">{t.team.name}</h2>
                <span className="text-sm text-fg-subtle">{modeLabel(t.mode)}{t.board ? ` · ${t.board.project_key} · ${t.board.name}` : ` · ${plan.iteration_days} días`}</span>
                {t.board_deleted && <span className="rounded-[3px] bg-warning-subtle px-1.5 text-xs" title="Al restaurar el tablero, el equipo vuelve a planificar con sus sprints">Su tablero está en la papelera</span>}
                <span className="text-sm text-fg-subtle">Capacidad por defecto: <b className="text-fg">{fmt(t.default_capacity)}</b></span>
                {overCount > 0 && <span className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-danger"><AlertTriangle size={14} />{overCount === 1 ? "1 iteración con sobrecarga" : `${overCount} iteraciones con sobrecarga`}</span>}
              </header>
              {!t.iterations.length ? (
                <p className="px-4 py-4 text-sm text-fg-subtle">El tablero no tiene sprints abiertos ni futuros.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-line text-left text-xs font-semibold text-fg-subtle">
                      <th className="px-4 py-2">Iteración</th><th className="py-2">Estado</th><th className="w-[32%] py-2">Carga</th>
                      <th className="py-2 text-right">Asignado</th><th className="py-2 pr-4 text-right">Capacidad</th><th className="w-32" />
                    </tr></thead>
                    <tbody>{t.iterations.map((it) => (
                      <tr key={it.key} className={cn("border-b border-line last:border-0", it.state === "closed" && "text-fg-subtle")}>
                        <td className="px-4 py-2"><div className="font-medium">{it.name}</div>
                          <div className="text-xs text-fg-subtle">{it.start ? `${fmtDate(it.start, "d MMM")} – ${fmtDate(it.end, "d MMM yyyy")}` : "Sin fechas"}</div></td>
                        <td className="py-2 text-xs">{choiceLabel(meta.data?.sprint_states, it.state)}</td>
                        <td className="py-2 pr-4"><Meter assigned={it.assigned} capacity={it.capacity} over={it.over} /></td>
                        <td className="py-2 text-right tabular-nums">{fmt(it.assigned)}<span className="block text-xs text-fg-subtle">{it.issue_count === 1 ? "1 incidencia" : `${it.issue_count} incidencias`}</span></td>
                        <td className="py-2 pr-4 text-right">
                          <span className="inline-flex items-center gap-1">
                            {it.overridden && plan.can_edit && (
                              <Button size="icon-sm" variant="subtle" aria-label="Volver a la capacidad del equipo" title="Volver a la capacidad del equipo"
                                      onClick={() => save.mutate({ team_id: t.team.id, sprint_id: it.sprint_id, iteration_start: it.sprint_id ? null : it.iteration_start, capacity: null })}>
                                <RotateCcw size={13} />
                              </Button>
                            )}
                            <CapacityInput value={it.capacity} overridden={it.overridden} disabled={!plan.can_edit || save.isPending} label={`Capacidad de ${t.team.name} en ${it.name}`}
                                           onCommit={(v) => save.mutate({ team_id: t.team.id, sprint_id: it.sprint_id, iteration_start: it.sprint_id ? null : it.iteration_start, capacity: v })} />
                          </span>
                        </td>
                        <td className="py-2 pr-4">{it.over && <span className="inline-flex items-center gap-1 text-xs font-medium text-danger"><AlertTriangle size={13} />Sobrecarga</span>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
              <p className="border-t border-line px-4 py-2 text-xs text-fg-subtle">
                Sin iteración: {fmt(t.unscheduled.assigned)} en {t.unscheduled.issue_count === 1 ? "1 incidencia" : `${t.unscheduled.issue_count} incidencias`}
                {t.mode === "sprints" ? " (en el backlog)" : " (sin fechas)"}.
              </p>
            </section>
          );
        })}
      </div>
    </div>
  );
}
