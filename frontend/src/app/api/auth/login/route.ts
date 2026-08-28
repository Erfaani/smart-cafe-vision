import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/api";
import { setSessionCookies } from "@/lib/session";
import type { ApiError, LoginResponse } from "@/lib/types";

/**
 * Login proxy.
 *
 * The browser posts here, this handler talks to Django, and the tokens are
 * written to httpOnly cookies. The access token never reaches client JavaScript.
 */
export async function POST(request: Request) {
  let credentials: { email?: string; password?: string };
  try {
    credentials = await request.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_request", message: "Expected a JSON body." } },
      { status: 400 },
    );
  }

  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}/api/v1/auth/login/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: credentials.email ?? "",
        password: credentials.password ?? "",
      }),
      cache: "no-store",
    });
  } catch {
    // The most common café failure: the backend container is still starting.
    return NextResponse.json(
      {
        error: {
          code: "backend_unreachable",
          message: "The Smart Café Vision server is not responding. Check that it is running.",
        },
      },
      { status: 503 },
    );
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiError | null;
    return NextResponse.json(
      body ?? { error: { code: "login_failed", message: "Invalid email or password." } },
      { status: response.status },
    );
  }

  const data = (await response.json()) as LoginResponse;
  await setSessionCookies(data.access, data.refresh);

  // Only the profile goes back to the browser; the tokens stay in the cookies.
  return NextResponse.json({ user: data.user });
}
