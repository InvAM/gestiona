"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Columns3, LayoutTemplate, ListChecks, Repeat } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { EmptyState, Field, Input, Textarea } from "@/components/ui/primitives";
import { useApp } from "@/components/shell/app-context";
import { useDebounced } from "@/components/board/filters-bar";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api/client";
import { useMeta } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

// Template/access values and labels come from GET /meta; this only adds an icon and a
// longer explanation for the cards (used when the backend sends no description).
const TEMPLATE_UI = {
  scrum: { icon: Repeat, body: "Planifica en sprints, gestiona un backlog y mide la velocidad del equipo." },
  kanban: { icon: Columns3, body: "Visualiza un flujo continuo de trabajo y limita el trabajo en curso." },
  business: { icon: ListChecks, body: "Organiza tareas simples de cualquier área." },
};
const ACCESS_UI = {
  open: "Todos pueden ver, crear y editar incidencias.",
  limited: "Todos pueden ver y comentar; solo miembros editan.",
  private: "Solo los miembros pueden ver el proyecto.",
};

export default function NewProjectPage() {
  const { me } = useApp();
  const router = useRouter();
  const qc = useQueryClient();
  const meta = useMeta();
  const [template, setTemplate] = useState("scrum");
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyTouched, setKeyTouched] = useState(false);
  const [access, setAccess] = useState("limited");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const dname = useDebounced(name, 300);

  useEffect(() => {
    if (keyTouched || !dname.trim()) return;
    unwrap(api.GET("/api/v1/projects/suggest-key", { params: { query: { name: dname } } }))
      .then((r) => setKey(r.key)).catch(() => {});
  }, [dname, keyTouched]);

  if (!me.can_create_projects) return <EmptyState title="Sin permiso" body="Solo los administradores pueden crear proyectos." />;

  async function submit() {
    const errs = {};
    if (!name.trim()) errs.name = "El nombre es obligatorio";
    if (!/^[A-Z][A-Z0-9]{1,9}$/.test(key)) errs.key = "De 2 a 10 caracteres, empieza con letra (A-Z, 0-9)";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setSaving(true);
    try {
      const p = await unwrap(api.POST("/api/v1/projects", { body: { name: name.trim(), key, template, access, description } }));
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast.success(`Proyecto ${p.name} creado`);
      router.push(`/projects/${p.key}`);
    } catch (e) {
      if (e instanceof ApiError && (e.code === "key" || e.code === "name")) setErrors({ [e.code]: e.message });
      else toast.error(errorMessage(e));
    } finally { setSaving(false); }
  }

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[760px] px-8 py-10">
        <h1 className="text-2xl font-medium">Crear proyecto</h1>
        <p className="mt-1 text-fg-subtle">Elige una plantilla. Podrás ajustar flujo, tipos y campos después.</p>
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {(meta.data?.project_templates ?? []).map((t) => {
            const Icon = TEMPLATE_UI[t.value]?.icon ?? LayoutTemplate;
            return (
              <button key={t.value} onClick={() => setTemplate(t.value)}
                      className={cn("rounded-[3px] border-2 p-4 text-left transition-colors hover:bg-bg-hover",
                                    template === t.value ? "border-brand bg-bg-selected" : "border-line")}>
                <Icon size={24} className="text-brand" />
                <div className="mt-2 font-semibold">{t.label}</div>
                <div className="mt-1 text-xs text-fg-subtle">{t.description || TEMPLATE_UI[t.value]?.body}</div>
              </button>
            );
          })}
        </div>
        <div className="mt-8 max-w-[480px] space-y-4">
          <Field label="Nombre" required error={errors.name}>
            <Input autoFocus value={name} maxLength={80} invalid={!!errors.name} onChange={(e) => setName(e.target.value)} placeholder="Ej. Plataforma de pagos" />
          </Field>
          <Field label="Clave" required error={errors.key} hint="Prefijo de las incidencias (ej. PAG-123). No se puede cambiar después.">
            <Input value={key} maxLength={10} invalid={!!errors.key} className="w-40 uppercase"
                   onChange={(e) => { setKeyTouched(true); setKey(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "")); }} />
          </Field>
          <Field label="Acceso">
            <div className="space-y-2">
              {(meta.data?.project_access ?? []).map((a) => (
                <label key={a.value} className="flex cursor-pointer gap-2 text-sm">
                  <input type="radio" name="access" className="mt-1 accent-[var(--brand)]" checked={access === a.value} onChange={() => setAccess(a.value)} />
                  <span><b>{a.label}</b> — <span className="text-fg-subtle">{a.description || ACCESS_UI[a.value]}</span></span>
                </label>
              ))}
            </div>
          </Field>
          <Field label="Descripción"><Textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
          <div className="flex gap-2 pt-2">
            <Button variant="primary" loading={saving} onClick={submit}>Crear proyecto</Button>
            <Button variant="subtle" onClick={() => router.back()}>Cancelar</Button>
          </div>
        </div>
      </div>
    </main>
  );
}
