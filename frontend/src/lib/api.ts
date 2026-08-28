import "server-only";

import { getAccessToken, getRefreshToken } from "@/lib/session";
import type { ApiError } from "@/lib/types";

/**
 * Server-side client for the Django API.
 *
 * Every browser request goes through this app's own server, never straight to
 * Django. That is what lets the tokens stay in httpOnly cookies, and it also
 * means the café's backend does not have to be reachable from the LAN at all —
 * only the Next.js server does.
 */

export const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

/** How long to wait before deciding the backend is not answering. */
const DEFAULT_TIMEOUT_MS = 8000;

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

type ApiFetchOptions = RequestInit & {
  /** Attach the caller's access token. Off for login and health. */
  authenticated?: boolean;
  timeoutMs?: number;
};

async function rawFetch(path: string, options: ApiFetchOptions, token?: string) {
  const { authenticated: _authenticated, timeoutMs, ...init } = options;
  // timeoutMs: 0 disables the abort timer entirely -- used by the camera
  // preview proxies, which hold a connection open for minutes on purpose.
  // Everything else gets a short default: a café manager waiting on an
  // analytics number should see a failure quickly, not a long hang.
  const effectiveTimeout = timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = effectiveTimeout > 0 ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), effectiveTimeout) : undefined;

  try {
    return await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      signal: controller?.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
      // Analytics and health must never be served from a stale cache: a café
      // manager looking at occupancy needs the current number.
      cache: "no-store",
    });
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function readError(response: Response): Promise<ApiRequestError> {
  let code = "error";
  let message = `Request failed with status ${response.status}.`;
  let detail: unknown;
  try {
    const body = (await response.json()) as ApiError;
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      detail = body.error.detail;
    }
  } catch {
    // A non-JSON body (nginx error page, backend still booting) is not worth
    // reporting verbatim to a café manager.
  }
  return new ApiRequestError(response.status, code, message, detail);
}

/**
 * Exchange the refresh token for a new access token.
 *
 * Returns the new access token, or null when the session is truly over. It does
 * not touch the cookie: Next only allows cookie writes from route handlers and
 * server actions, and this is called from server components too.
 */
export async function refreshAccessToken(): Promise<string | null> {
  const refresh = await getRefreshToken();
  if (!refresh) return null;

  const response = await rawFetch("/api/v1/auth/refresh/", {
    method: "POST",
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) return null;

  const body = (await response.json()) as { access?: string };
  return body.access ?? null;
}

/**
 * Call the API as the signed-in user.
 *
 * On a 401 it retries once with a refreshed token, so a manager who left the
 * dashboard open over a lunch shift does not get bounced to the login screen
 * mid-glance.
 *
 * The refreshed token is used for that one request and not written back to the
 * cookie: Next only permits cookie writes from route handlers and server
 * actions, and this runs in server components too. That costs an extra refresh
 * round trip per expired-token request, which is acceptable because
 * BLACKLIST_AFTER_ROTATION is off — the refresh token stays valid, so repeated
 * refreshes succeed rather than logging the user out.
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const response = await apiFetchRaw(path, options);
  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * Same auth/refresh handling as apiFetch, but returns the raw Response
 * instead of decoding JSON. Used by the camera preview proxies, which stream
 * MJPEG/JPEG bytes straight through to the browser rather than parsing them.
 */
export async function apiFetchRaw(path: string, options: ApiFetchOptions = {}): Promise<Response> {
  const authenticated = options.authenticated ?? true;
  let token = authenticated ? await getAccessToken() : undefined;

  let response = await rawFetch(path, options, token);

  if (response.status === 401 && authenticated) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      token = refreshed;
      response = await rawFetch(path, options, token);
    }
  }

  return response;
}
