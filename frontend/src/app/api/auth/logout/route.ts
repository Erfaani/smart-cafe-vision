import { NextResponse } from "next/server";

import { BACKEND_URL } from "@/lib/api";
import { clearSessionCookies, getAccessToken, getRefreshToken } from "@/lib/session";

export async function POST() {
  const access = await getAccessToken();
  const refresh = await getRefreshToken();

  // Tell the backend, but never let a backend problem trap someone in a session
  // they are trying to leave: the cookies are cleared either way.
  if (access) {
    try {
      await fetch(`${BACKEND_URL}/api/v1/auth/logout/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${access}`,
        },
        body: JSON.stringify({ refresh }),
        cache: "no-store",
      });
    } catch {
      // Intentionally ignored, see above.
    }
  }

  await clearSessionCookies();
  return NextResponse.json({ ok: true });
}
