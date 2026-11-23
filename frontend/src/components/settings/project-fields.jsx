"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Lock } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { IssueTypeIcon } from "@/components/icons";
import { FieldShell } from "@/components/fields/screen-form";
import { Button, PageSpinner } from "@/components/ui/button";
import { Picker } from "@/components/ui/picker";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { qk, useFieldRules, useMeta } from "@/lib/api/hooks";
import { fieldCatalog, fieldLabel, typeRules } from "@/lib/screens";
import { cn } from "@/lib/utils";
import { COLLECTIONS, useCollection } from "./fields-admin";

const SEL = "flex h-8 w-full items-center gap-2 rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-left text-sm hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-60";

/**
 * Configuración del proyecto › Campos: which field configuration scheme and issue type screen
 * scheme the project uses (only system admins change them; everybody else sees them read-only)
 * and a preview of what each issue type shows on create / edit / view.
 */
export function ProjectFields({ meta }) {
  const key = meta.project.key;
  const qc = useQueryClient();
  const schemes = useQuery({
    queryKey: ["field-schemes", key],
    queryFn: () => unwrap(api.GET("/api/v1/projects/{key}/field-schemes", { params: { path: { key } } })),
  });
  const canChange = !!schemes.data?.can_change;
  const fcs = useCollection(COLLECTIONS.fcs, canChange);
  const itss = useCollection(COLLECTIONS.itss, canChange);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState(null);
  const save = useMutation({
    mutationFn: (body) => unwrap(api.PUT("/api/v1/projects/{key}/field-schemes", { params: { path: { key } }, body })),
    onSuccess: (d) => {
      qc.setQueryData(["field-schemes", key], d);
      qc.invalidateQueries({ queryKey: qk.fieldRules(key) });
      qc.invalidateQueries({ queryKey: qk.meta(key) });
      for (const c of Object.values(COLLECTIONS)) qc.invalidateQueries({ queryKey: [c.key] });
      setDraft(null);
      setError(null);
      toast.success("Esquemas del proyecto actualizados");
    },
    onError: (e) => setError(errorMessage(e)),
  });
  if (schemes.isPending) return <PageSpinner />;
  if (schemes.error) return <p role="alert" className="text-sm text-danger">{errorMessage(schemes.error)}</p>;
  const cur = {
    fcs: draft?.fcs ?? schemes.data.field_configuration_scheme?.id ?? null,
    itss: draft?.itss ?? schemes.data.issue_type_screen_scheme?.id ?? null,
  };
  const dirty = !!draft && (cur.fcs !== schemes.data.field_configuration_scheme?.id || cur.itss !== schemes.data.issue_type_screen_scheme?.id);
  const pick = (list, value, current, onSelect, label, hint) => (
    <FieldShell label={label} description={hint}>
      {(a11y) => canChange ? (
        <Picker value={value} width={360} onSelect={onSelect}
                options={(list.data ?? []).map((s) => ({ value: s.id, label: s.name, description: s.description || (s.is_default ? "Predeterminado" : undefined) }))}
                trigger={<button type="button" className={SEL} {...a11y}>{list.data?.find((s) => s.id === value)?.name ?? current?.name ?? "—"}<ChevronDown size={16} className="ml-auto text-fg-subtle" /></button>} />
      ) : (
        <div className="flex h-8 items-center gap-2 rounded-[3px] bg-bg-subtle px-2 text-sm" {...a11y} aria-readonly="true"><Lock size={14} className="text-fg-subtlest" />{current?.name ?? "—"}</div>
      )}
    </FieldShell>
  );
  return (
    <div className="max-w-[960px] space-y-6">
      <p className="text-sm text-fg-subtle">
        Los campos que piden y muestran las incidencias de este proyecto salen de dos esquemas compartidos: la configuración de campos (obligatorios, ocultos y ayuda) y las pantallas (qué campos y en qué orden al crear, editar y ver).
        {!canChange && " Solo un administrador del sistema puede cambiarlos."}
      </p>
      {error && <p role="alert" className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        {pick(fcs, cur.fcs, schemes.data.field_configuration_scheme, (v) => setDraft({ ...cur, fcs: v }), "Esquema de configuración de campos",
              canChange ? <Link className="text-link hover:underline" href="/settings/field-configuration-schemes">Administrar esquemas</Link> : undefined)}
        {pick(itss, cur.itss, schemes.data.issue_type_screen_scheme, (v) => setDraft({ ...cur, itss: v }), "Esquema de pantalla por tipo",
              canChange ? <Link className="text-link hover:underline" href="/settings/issue-type-screen-schemes">Administrar esquemas</Link> : undefined)}
      </div>
      {canChange && (
        <div className="flex gap-2">
          <Button variant="primary" disabled={!dirty} loading={save.isPending}
                  onClick={() => save.mutate({ field_configuration_scheme_id: cur.fcs, issue_type_screen_scheme_id: cur.itss })}>Guardar</Button>
          {dirty && <Button variant="subtle" onClick={() => { setDraft(null); setError(null); }}>Descartar</Button>}
        </div>
      )}
      <FieldsPreview meta={meta} />
    </div>
  );
}

/** What each issue type of the project shows on each operation (from /field-rules). */
function FieldsPreview({ meta }) {
  const rules = useFieldRules(meta.project.key);
  const appMeta = useMeta();
  const [open, setOpen] = useState(() => new Set(meta.issue_types.slice(0, 1).map((t) => t.id)));
  if (rules.isPending) return <PageSpinner />;
  if (rules.error) return <p role="alert" className="text-sm text-danger">{errorMessage(rules.error)}</p>;
  if (!rules.data) return <p className="text-sm text-fg-subtle">El servidor todavía no publica las reglas de campos.</p>;
  const catalog = fieldCatalog(rules.data, meta, appMeta.data);
  const ops = appMeta.data?.screen_operations ?? [];
  const toggle = (id) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <section>
      <h2 className="mb-1 text-lg font-medium">Vista previa por tipo</h2>
      <p className="mb-3 text-sm text-fg-subtle">Campos que ve cada tipo de incidencia, en orden. <span className="text-danger">*</span> = obligatorio.</p>
      <div className="space-y-2">
        {meta.issue_types.map((t) => {
          const tr = typeRules(rules.data, t.id);
          const isOpen = open.has(t.id);
          return (
            <div key={t.id} className="rounded-[3px] border border-line">
              <button type="button" aria-expanded={isOpen} onClick={() => toggle(t.id)}
                      className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-sm hover:bg-bg-hover">
                <ChevronDown size={14} className={cn("transition-transform", !isOpen && "-rotate-90")} />
                <IssueTypeIcon type={t} /><b>{t.name}</b>
                {tr && <span className="text-xs text-fg-subtle">Configuración «{tr.field_configuration?.name}» · Esquema de pantalla «{tr.screen_scheme?.name}»</span>}
                {tr?.warnings?.length > 0 && <span className="ml-auto flex items-center gap-1 text-xs text-warning"><AlertTriangle size={14} />{tr.warnings.length} {tr.warnings.length === 1 ? "aviso" : "avisos"}</span>}
              </button>
              {isOpen && tr && (
                <div className="space-y-3 border-t border-line px-3 py-3">
                  {tr.warnings?.length > 0 && (
                    <ul role="note" className="space-y-1 rounded-[3px] bg-warning-subtle px-3 py-2 text-xs">
                      {tr.warnings.map((w) => <li key={`${w.field}-${w.message}`}>{w.message}</li>)}
                    </ul>
                  )}
                  <div className="grid gap-3 md:grid-cols-3">
                    {ops.map((o) => {
                      const s = tr.screens?.[o.value];
                      return (
                        <div key={o.value} className="rounded-[3px] bg-bg-subtle p-2">
                          <div className="mb-1 text-xs font-semibold text-fg-subtle">{o.label}{s?.name && <span className="font-normal"> · {s.name}</span>}</div>
                          {!s ? <p className="text-xs text-fg-subtlest">Sin pantalla</p> : s.tabs.map((tab) => (
                            <div key={tab.id ?? tab.name} className="mb-1">
                              {s.tabs.length > 1 && <div className="text-[11px] font-semibold uppercase text-fg-subtlest">{tab.name}</div>}
                              <ol className="text-sm">
                                {tab.fields.map((f) => (
                                  <li key={f.key} title={f.description || undefined}>
                                    {fieldLabel(catalog, f.key)}{f.required && <span className="ml-0.5 text-danger" aria-label="obligatorio">*</span>}
                                  </li>
                                ))}
                              </ol>
                            </div>
                          ))}
                        </div>
                      );
                    })}
                  </div>
                  {tr.hidden?.length > 0 && <p className="text-xs text-fg-subtle">Ocultos: {tr.hidden.map((k) => fieldLabel(catalog, k)).join(", ")}</p>}
                  {tr.transitions?.some((x) => x.screen || x.required_fields?.length) && (
                    <div className="text-xs text-fg-subtle">
                      <span className="font-semibold">Transiciones con pantalla o campos obligatorios: </span>
                      {tr.transitions.filter((x) => x.screen || x.required_fields?.length).map((x) => (
                        `${x.name}${x.screen ? ` (pantalla «${x.screen.name}»)` : ""}${x.required_fields?.length ? ` — exige ${x.required_fields.map((k) => fieldLabel(catalog, k)).join(", ")}` : ""}`
                      )).join(" · ")}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
