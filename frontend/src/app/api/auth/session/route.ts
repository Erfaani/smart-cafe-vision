import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

/** Who am I? Used by client components that need the profile after hydration. */
export async function GET() {
  try {
    const user = await apiFetch<User>("/api/v1/auth/me/");
    return NextResponse.json({ user });
  } catch (error) {
    const status = error instanceof ApiRequestError ? error.status : 503;
    return NextResponse.json({ user: null }, { status: status === 401 ? 401 : status });
  }
}
