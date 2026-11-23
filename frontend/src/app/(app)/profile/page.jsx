"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { useApp } from "@/components/shell/app-context";
import { Button } from "@/components/ui/button";
import { Avatar, Field, Input, Toggle } from "@/components/ui/primitives";
import { api, errorMessage, rawFetch, unwrap } from "@/lib/api/client";
import { qk } from "@/lib/api/hooks";

export default function ProfilePage() {
  const { me } = useApp();
  const qc = useQueryClient();
  const fileRef = useRef(null);
  const [name, setName] = useState(me.name);
  const [title, setTitle] = useState(me.job_title);
  const [tz, setTz] = useState(me.timezone);
  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/me", { body: { full_name: name, job_title: title, timezone: tz } })),
    onSuccess: (d) => { qc.setQueryData(qk.me, d); toast.success("Perfil actualizado"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const upload = useMutation({
    mutationFn: (f) => { const fd = new FormData(); fd.append("file", f); return rawFetch("/api/v1/me/avatar", { method: "POST", body: fd }); },
    onSuccess: (d) => qc.setQueryData(qk.me, d), onError: (e) => toast.error(errorMessage(e)),
  });
  const prefs = useQuery({ queryKey: ["notif-prefs"], queryFn: () => unwrap(api.GET("/api/v1/notifications/preferences")) });
  const setPrefs = useMutation({
    mutationFn: (body) => unwrap(api.PUT("/api/v1/notifications/preferences", { body })),
    onSuccess: (d) => qc.setQueryData(["notif-prefs"], d),
  });
  const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [me.timezone];

  return (
    <main className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[760px] px-8 py-8">
        <h1 className="text-2xl font-medium">Perfil y preferencias</h1>
        <div className="mt-6 flex items-center gap-5">
          <Avatar user={me} size="xl" />
          <div className="space-x-2">
            <Button loading={upload.isPending} onClick={() => fileRef.current?.click()}>Cambiar foto</Button>
            {me.avatar_url && <Button variant="subtle" onClick={async () => qc.setQueryData(qk.me, await unwrap(api.DELETE("/api/v1/me/avatar")))}>Quitar</Button>}
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden
                   onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
          </div>
        </div>
        <div className="mt-6 max-w-[420px] space-y-4">
          <Field label="Nombre completo"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Email" hint="Contacta a un administrador para cambiarlo."><Input value={me.email} disabled /></Field>
          <Field label="Cargo"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Zona horaria">
            <select value={tz} onChange={(e) => setTz(e.target.value)} className="h-8 w-full rounded-[3px] border-2 border-line bg-bg-subtle px-2 text-sm">
              {zones.map((z) => <option key={z} value={z}>{z}</option>)}
            </select>
          </Field>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Guardar</Button>
        </div>
        <h2 className="mt-10 text-lg font-medium">Notificaciones</h2>
        <p className="text-sm text-fg-subtle">Recibes avisos de las incidencias que observas, te asignan o donde te mencionan.</p>
        <table className="mt-3 w-full max-w-[560px] text-sm">
          <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Evento</th><th className="py-2">En la app</th><th className="py-2">Email</th></tr></thead>
          <tbody>
            {prefs.data?.map((p) => (
              <tr key={p.event} className="border-b border-line">
                <td className="py-2">{p.label}</td>
                <td className="py-2"><Toggle label="En la app" checked={p.in_app} onChange={(v) => setPrefs.mutate([{ ...p, in_app: v }])} /></td>
                <td className="py-2"><Toggle label="Email" checked={p.email} onChange={(v) => setPrefs.mutate([{ ...p, email: v }])} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
