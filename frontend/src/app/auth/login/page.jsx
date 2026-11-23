"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { useAuthConfig } from "@/lib/api/hooks";
import { errorMessage, hardNavigate } from "@/lib/api/client";
import { login, requestPasswordReset, safeNext, startSSO } from "@/lib/auth";

const PROVIDER_LABEL = { google: "Google", microsoft: "Microsoft" };

function LoginForm() {
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const cfg = useAuthConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(
    params.get("error") === "sso" ? "No se pudo iniciar sesión con tu cuenta de la organización." : null,
  );
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState("login");

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "forgot") {
        await requestPasswordReset(email);
        setMode("sent");
      } else {
        await login(email, password);
        hardNavigate(next);
      }
    } catch (err) {
      setError(mode === "forgot" ? errorMessage(err) : "Email o contraseña incorrectos.");
    } finally {
      setLoading(false);
    }
  }

  const providers = cfg.data?.providers ?? [];
  const passwordLogin = cfg.data?.password_login ?? true;

  if (mode === "sent") {
    return (
      <div className="text-center">
        <h1 className="mb-3 text-base font-semibold">Revisa tu correo</h1>
        <p className="text-fg-subtle">Si existe una cuenta para <b>{email}</b>, te enviamos un enlace para restablecer la contraseña.</p>
        <Button variant="link" className="mt-6" onClick={() => setMode("login")}>Volver a iniciar sesión</Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-center text-base font-semibold text-fg-subtle">
        {mode === "forgot" ? "¿No puedes iniciar sesión?" : "Inicia sesión para continuar"}
      </h1>
      {error && <div className="rounded-[3px] bg-danger-subtle px-3 py-2 text-sm text-danger">{error}</div>}
      {(passwordLogin || mode === "forgot") && (
        <>
          <Field label="Correo electrónico" required>
            <Input type="email" autoComplete="username" required autoFocus value={email}
                   onChange={(e) => setEmail(e.target.value)} placeholder="tu@empresa.com" />
          </Field>
          {mode === "login" && (
            <Field label="Contraseña" required>
              <Input type="password" autoComplete="current-password" required value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            </Field>
          )}
          <Button type="submit" variant="primary" className="w-full justify-center" loading={loading}>
            {mode === "forgot" ? "Enviar enlace de recuperación" : "Iniciar sesión"}
          </Button>
        </>
      )}
      {providers.length > 0 && mode === "login" && (
        <>
          {passwordLogin && <div className="text-center text-xs text-fg-subtlest">O continúa con</div>}
          {providers.map((p) => (
            <Button key={p} className="w-full justify-center border border-line bg-bg shadow-raised"
                    onClick={() => startSSO(p, next)}>
              {PROVIDER_LABEL[p] ?? cfg.data?.provider_names?.[p] ?? p}
            </Button>
          ))}
        </>
      )}
      {passwordLogin && (
        <div className="pt-2 text-center">
          <Button variant="link" onClick={() => { setMode(mode === "login" ? "forgot" : "login"); setError(null); }}>
            {mode === "login" ? "¿No puedes iniciar sesión?" : "Volver a iniciar sesión"}
          </Button>
        </div>
      )}
    </form>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
