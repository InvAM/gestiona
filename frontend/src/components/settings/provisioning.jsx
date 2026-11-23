"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageSpinner } from "@/components/ui/button";
import { Badge, Confirm, EmptyState, Field, Input, Modal } from "@/components/ui/primitives";
import { api, errorMessage, unwrap } from "@/lib/api/client";
import { cn, fmtRelative } from "@/lib/utils";

/** SCIM tokens for automatic user provisioning + SSO setup notes. */
export function Provisioning() {
  const qc = useQueryClient();
  const tokens = useQuery({ queryKey: ["api-tokens"], queryFn: () => unwrap(api.GET("/api/v1/admin/api-tokens")) });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [created, setCreated] = useState(null);
  const [revoking, setRevoking] = useState(null);
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/admin/api-tokens", { body: { name } })),
    onSuccess: (t) => { setCreated(t); setCreating(false); setName(""); qc.invalidateQueries({ queryKey: ["api-tokens"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: (id) => unwrap(api.DELETE("/api/v1/admin/api-tokens/{token_id}", { params: { path: { token_id: id } } })),
    onSuccess: () => { setRevoking(null); qc.invalidateQueries({ queryKey: ["api-tokens"] }); },
  });
  const copy = async (text) => { await navigator.clipboard.writeText(text); toast.success("Copiado"); };
  const scimUrl = typeof window !== "undefined" ? `${window.location.origin}/scim/v2` : "/scim/v2";
  return (
    <div className="max-w-[860px] space-y-8">
      <section>
        <h2 className="text-lg font-medium">Aprovisionamiento automático (SCIM 2.0)</h2>
        <p className="mt-1 text-sm text-fg-subtle">
          Conecta Microsoft Entra ID, Okta, JumpCloud u otro proveedor para que las altas, cambios y bajas de personas lleguen solas a Gestiona.
          Una baja desactiva la cuenta (su historial se conserva). Los permisos por proyecto se siguen asignando aquí.
        </p>
        <div className="mt-3 flex items-center gap-2 rounded-[3px] bg-bg-subtle p-3 text-sm">
          <span className="text-fg-subtle">URL base SCIM:</span><code className="font-mono">{scimUrl}</code>
          <Button size="icon" variant="subtle" aria-label="Copiar URL" onClick={() => copy(scimUrl)}><Copy size={14} /></Button>
        </div>
        <div className="mt-4 flex justify-end"><Button variant="primary" onClick={() => setCreating(true)}><Plus size={16} />Crear token</Button></div>
        {tokens.isPending ? <PageSpinner /> : !tokens.data?.length ? (
          <EmptyState icon={<KeyRound size={36} />} title="Sin tokens" body="Crea un token y pégalo como «Secret Token» en la app empresarial de tu proveedor de identidad." />
        ) : (
          <table className="mt-3 w-full text-sm">
            <thead><tr className="border-b-2 border-line text-left text-xs font-semibold text-fg-subtle"><th className="py-2">Nombre</th><th>Token</th><th>Creado</th><th>Último uso</th><th className="w-24" /></tr></thead>
            <tbody>{tokens.data.map((t) => (
              <tr key={t.id} className={cn("border-b border-line", t.revoked && "opacity-50")}>
                <td className="py-2 font-medium">{t.name}{t.revoked && <Badge className="ml-2">Revocado</Badge>}</td>
                <td className="py-2 font-mono text-xs">{t.prefix}…</td>
                <td className="py-2 text-fg-subtle">{fmtRelative(t.created_at)}</td>
                <td className="py-2 text-fg-subtle">{t.last_used_at ? fmtRelative(t.last_used_at) : "Nunca"}</td>
                <td className="py-2 text-right">{!t.revoked && <Button size="sm" variant="subtle" onClick={() => setRevoking(t)}>Revocar</Button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </section>

      <section>
        <h2 className="text-lg font-medium">Inicio de sesión único (SSO)</h2>
        <p className="mt-1 text-sm text-fg-subtle">Se configura en el servidor (archivo <code>.env.production</code>) y luego aparece como botón en la pantalla de inicio de sesión:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
          <li><b>Google / Microsoft:</b> <code>SSO_GOOGLE_ENABLED</code>, <code>SSO_MICROSOFT_ENABLED</code> y sus credenciales.</li>
          <li><b>Cualquier proveedor OpenID Connect</b> (Okta, Keycloak, Authentik, Entra ID, Auth0, JumpCloud): <code>SSO_OIDC_ENABLED=true</code>, <code>OIDC_SERVER_URL</code>, <code>OIDC_CLIENT_ID</code>, <code>OIDC_CLIENT_SECRET</code> y <code>OIDC_NAME</code>. Callback: <code>{typeof window !== "undefined" ? window.location.origin : ""}/accounts/oidc/login/callback/</code></li>
          <li><code>PASSWORD_LOGIN_ENABLED=false</code> obliga a usar SSO. <code>ALLOWED_SIGNUP_DOMAINS</code> permite que entren personas del dominio sin invitación.</li>
        </ul>
      </section>

      <Modal open={creating} onOpenChange={setCreating} title="Crear token SCIM" width={460}>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field label="Nombre" required hint="Para reconocerlo después, p. ej. «Entra ID producción»."><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <div className="flex justify-end gap-2"><Button type="button" variant="subtle" onClick={() => setCreating(false)}>Cancelar</Button><Button type="submit" variant="primary" disabled={!name.trim()} loading={create.isPending}>Crear</Button></div>
        </form>
      </Modal>
      <Modal open={!!created} onOpenChange={(o) => !o && setCreated(null)} title="Token creado" width={560}>
        {created && (
          <div className="space-y-3 text-sm">
            <p className="rounded-[3px] bg-warning-subtle p-2">Cópialo ahora: <b>no se volverá a mostrar</b>.</p>
            <div className="flex items-center gap-2"><code className="flex-1 break-all rounded-[3px] bg-bg-sunken p-2 font-mono text-xs">{created.token}</code>
              <Button size="icon" variant="subtle" aria-label="Copiar token" onClick={() => copy(created.token)}><Copy size={14} /></Button></div>
            <p className="text-fg-subtle">En tu proveedor usa <b>Tenant URL</b> = <code>{created.scim_url}</code> y <b>Secret Token</b> = el token de arriba.</p>
            <div className="flex justify-end"><Button variant="primary" onClick={() => setCreated(null)}>Listo</Button></div>
          </div>
        )}
      </Modal>
      <Confirm open={!!revoking} onOpenChange={(o) => !o && setRevoking(null)} danger confirmLabel="Revocar" title={`¿Revocar «${revoking?.name}»?`}
               body="El proveedor dejará de poder sincronizar usuarios con este token." onConfirm={() => revoking && revoke.mutate(revoking.id)} />
    </div>
  );
}
