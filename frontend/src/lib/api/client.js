import createClient from "openapi-fetch";

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getCookie(name) {
  if (typeof document === "undefined") return undefined;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : undefined;
}

const csrf = {
  onRequest({ request }) {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
      const token = getCookie("gestiona_csrf");
      if (token) request.headers.set("X-CSRFToken", token);
    }
    return request;
  },
};

export const api = createClient({ baseUrl: "", credentials: "same-origin" });
api.use(csrf);

/** Unwrap an openapi-fetch result, throwing ApiError on failure. */
export async function unwrap(p) {
  const { data, error, response } = await p;
  if (!response.ok) {
    const e = error ?? {};
    if (response.status === 401 && typeof window !== "undefined" &&
        !window.location.pathname.startsWith("/auth")) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      hardNavigate(`/auth/login?next=${next}`);
    }
    throw new ApiError(response.status, e.code ?? "error",
      e.message ?? `Error ${response.status}`, e.details);
  }
  return data;
}

/** Plain fetch for endpoints without typed bodies (multipart, allauth). */
export async function rawFetch(url, init = {}) {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  if (method !== "GET") {
    const token = getCookie("gestiona_csrf");
    if (token) headers.set("X-CSRFToken", token);
  }
  if (init.body && typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, { ...init, headers, credentials: "same-origin" });
  const text = await res.text();
  const json = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const msg = json?.message ?? json?.errors?.[0]?.message ?? `Error ${res.status}`;
    throw new ApiError(res.status, json?.code ?? "error", msg, json);
  }
  return json;
}

export function errorMessage(e) {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Ocurrió un error inesperado";
}

/**
 * Full page navigation. Used on auth boundaries (login, logout, session expiry) so that
 * every in-memory cache and websocket from the previous session is discarded.
 */
export function hardNavigate(url) {
  window.location.assign(url);
}
