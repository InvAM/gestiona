"use client";

import { use, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { ApiError, errorMessage, hardNavigate } from "@/lib/api/client";
import { resetPassword } from "@/lib/auth";

export default function ResetPasswordPage({ params }) {
  const { key } = use(params);
  const [pw, setPw] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await resetPassword(key, pw);
      hardNavigate("/your-work");
    } catch (err) {
      // allauth returns 401 on success when it doesn't auto-login: treat as success
      if (err instanceof ApiError && err.status === 401) hardNavigate("/auth/login");
      else setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-center text-base font-semibold">Restablecer contraseña</h1>
      {error && <div className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</div>}
      <Field label="Nueva contraseña" required hint="Mínimo 10 caracteres.">
        <Input type="password" autoComplete="new-password" minLength={10} required value={pw}
               onChange={(e) => setPw(e.target.value)} autoFocus />
      </Field>
      <Button type="submit" variant="primary" className="w-full justify-center" loading={loading}>
        Guardar contraseña
      </Button>
    </form>
  );
}
