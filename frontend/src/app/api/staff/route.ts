import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Paginated, User } from "@/lib/types";

/** Staff account list/create, forwarding to /api/v1/auth/users/ -- same
 * pagination-unwrapping pattern as every other list BFF route (e.g.
 * /api/sessions). */
export async function GET() {
  try {
    const page = await apiFetch<Paginated<User>>("/api/v1/auth/users/");
    return NextResponse.json(page.results);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    throw error;
  }
}

export async function POST(request: Request) {
  const body = await request.json();
  try {
    const user = await apiFetch<User>("/api/v1/auth/users/", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(user, { status: 201 });
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
