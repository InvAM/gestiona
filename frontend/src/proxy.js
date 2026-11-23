import { NextResponse } from "next/server";

/** Cheap gate: no session cookie → login page. Real auth is enforced by Django. */
export function proxy(request) {
  const hasSession = request.cookies.has("gestiona_session");
  if (!hasSession) {
    const url = request.nextUrl.clone();
    const next = request.nextUrl.pathname + request.nextUrl.search;
    url.pathname = "/auth/login";
    url.search = next && next !== "/" ? `?next=${encodeURIComponent(next)}` : "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!auth|api|_allauth|accounts|admin|static|media|scim|_next|favicon.ico|.*\\.(?:png|svg|jpg|ico|webp)$).*)",
  ],
};
