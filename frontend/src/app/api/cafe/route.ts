import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Cafe, User } from "@/lib/types";

/** Edits the caller's own café. The slug is never trusted from the request
 * body -- resolved server-side from the caller's own profile, same principle
 * as CafeScopedCreateMixin never trusting a client to say which café it
 * means (see backend/apps/core/viewsets.py). */
export async function PATCH(request: Request) {
  const body = await request.json();
  try {
    const user = await apiFetch<User>("/api/v1/auth/me/");
    if (!user.cafe_slug) {
      return NextResponse.json(
        { error: { code: "no_cafe", message: "No café is assigned to this account." } },
        { status: 404 },
      );
    }
    const cafe = await apiFetch<Cafe>(`/api/v1/cafes/${user.cafe_slug}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    return NextResponse.json(cafe);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json(
        { error: { code: error.code, message: error.message, detail: error.detail } },
        { status: error.status },
      );
    }
    throw error;
  }
}
