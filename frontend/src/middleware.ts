import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/cookie-names";

/**
 * Route guard.
 *
 * Deliberately a cheap presence check, not a token validation: middleware runs
 * on the edge runtime where verifying a signature would mean shipping the
 * signing key to it. Real authorisation is enforced by Django on every request;
 * this only avoids rendering a dashboard shell that would immediately 401.
 *
 * `/display/:slug` is intentionally NOT guarded — the café TV has no login.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession =
    request.cookies.has(ACCESS_COOKIE) || request.cookies.has(REFRESH_COOKIE);

  if (pathname.startsWith("/dashboard") && !hasSession) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }

  if (pathname === "/login" && hasSession) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/login"],
};
