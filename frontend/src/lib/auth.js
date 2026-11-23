import { getCookie, rawFetch } from "./api/client";

const BASE = "/_allauth/browser/v1";

export async function ensureCsrf() {
  if (!getCookie("gestiona_csrf")) await fetch("/api/v1/auth/config", { credentials: "same-origin" });
}

export async function login(email, password) {
  await ensureCsrf();
  return rawFetch(`${BASE}/auth/login`, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logout() {
  await ensureCsrf();
  try {
    await rawFetch(`${BASE}/auth/session`, { method: "DELETE" });
  } catch {
    /* allauth answers 401 after logout — expected */
  }
}

export async function requestPasswordReset(email) {
  await ensureCsrf();
  return rawFetch(`${BASE}/auth/password/request`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function resetPassword(key, password) {
  await ensureCsrf();
  return rawFetch(`${BASE}/auth/password/reset`, {
    method: "POST",
    body: JSON.stringify({ key, password }),
  });
}

/** SSO must be a top-level form POST so the browser follows the provider redirect. */
export async function startSSO(provider, next) {
  await ensureCsrf();
  const form = document.createElement("form");
  form.method = "POST";
  form.action = `${BASE}/auth/provider/redirect`;
  const fields = {
    provider,
    process: "login",
    callback_url: `${window.location.origin}/auth/sso-callback?next=${encodeURIComponent(next)}`,
    csrfmiddlewaretoken: getCookie("gestiona_csrf") ?? "",
  };
  for (const [k, v] of Object.entries(fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = k;
    input.value = v;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
}

const DEFAULT_NEXT = "/your-work";
const PARSE_ORIGIN = "http://gestiona.invalid"; // parse-only origin; works during SSR too

/** Same-origin path to go to after login. Anything that could leave the site → default.
 * Browsers treat "\" as "/" and drop tabs/newlines, so "/\evil.com" would act as "//evil.com". */
export function safeNext(next) {
  if (typeof next !== "string" || !next.startsWith("/") || /[\\\u0000-\u001f\u007f]/.test(next)) return DEFAULT_NEXT;
  try {
    const u = new URL(next, PARSE_ORIGIN);
    // Validate what we return, not what came in: "/.//evil.com" normalizes to "//evil.com".
    const out = u.pathname + u.search + u.hash;
    if (u.origin !== PARSE_ORIGIN || !out.startsWith("/") || out.startsWith("//") || u.pathname.startsWith("/auth"))
      return DEFAULT_NEXT;
    return out;
  } catch {
    return DEFAULT_NEXT;
  }
}
