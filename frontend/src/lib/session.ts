import "server-only";

import { cookies } from "next/headers";

/**
 * Session handling for the admin dashboard.
 *
 * Tokens live in httpOnly cookies written by this app's own route handlers, not
 * in localStorage. That matters more here than in a typical SaaS: this software
 * also serves a public display page on a TV that anyone in the café can walk up
 * to, and browser-readable admin tokens would be one XSS away from an attacker
 * who is standing in the room.
 */

export { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/cookie-names";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/cookie-names";

// Mirrors ACCESS_TOKEN_LIFETIME_MINUTES / REFRESH_TOKEN_LIFETIME_DAYS.
const ACCESS_MAX_AGE = 30 * 60;
const REFRESH_MAX_AGE = 7 * 24 * 60 * 60;

/**
 * `secure` is deliberately conditional: a café LAN install is plain HTTP on a
 * local IP, and a hard-coded `secure: true` would silently drop every cookie
 * and make login appear to do nothing.
 */
function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production" && process.env.BEHIND_TLS_PROXY === "true",
    path: "/",
    maxAge,
  };
}

export async function setSessionCookies(access: string, refresh: string) {
  const jar = await cookies();
  jar.set(ACCESS_COOKIE, access, cookieOptions(ACCESS_MAX_AGE));
  jar.set(REFRESH_COOKIE, refresh, cookieOptions(REFRESH_MAX_AGE));
}

export async function clearSessionCookies() {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}

export async function getAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_COOKIE)?.value;
}

export async function getRefreshToken(): Promise<string | undefined> {
  return (await cookies()).get(REFRESH_COOKIE)?.value;
}
