"use client";

import { use, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { api, errorMessage, hardNavigate, unwrap } from "@/lib/api/client";
import { ensureCsrf } from "@/lib/auth";

export default function SetPasswordPage({ params }) {
  const { uid, token } = use(params);
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (pw !== pw2) return setError("Las contraseñas no coinciden.");
    setLoading(true);
    setError(null);
    try {
      await ensureCsrf();
      await unwrap(api.POST("/api/v1/auth/set-password", { body: { uid, token, password: pw } }));
      hardNavigate("/your-work");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-center text-base font-semibold">Crea tu contraseña</h1>
      <p className="text-center text-sm text-fg-subtle">Mínimo 10 caracteres. Evita contraseñas comunes.</p>
      {error && <div className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</div>}
      <Field label="Nueva contraseña" required>
        <Input type="password" autoComplete="new-password" minLength={10} required value={pw}
               onChange={(e) => setPw(e.target.value)} autoFocus />
      </Field>
      <Field label="Confirmar contraseña" required>
        <Input type="password" autoComplete="new-password" minLength={10} required value={pw2}
               onChange={(e) => setPw2(e.target.value)} />
      </Field>
      <Button type="submit" variant="primary" className="w-full justify-center" loading={loading}>
        Guardar y entrar
      </Button>
    </form>
  );
}
