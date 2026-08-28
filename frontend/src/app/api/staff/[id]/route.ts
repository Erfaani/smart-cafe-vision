import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

type RouteParams = { params: Promise<{ id: string }> };

/** Role/name edits and reactivation (`is_active: true`) -- plain PATCH.
 * Deactivating goes through /api/staff/[id]/deactivate instead: the backend
 * has a dedicated action for that specifically because it is the one that
 * guards against an owner locking themselves out (`self_deactivation`),
 * a check the generic update endpoint this route calls does not carry --
 * see backend/apps/accounts/views.py::UserViewSet.deactivate. */
export async function PATCH(request: Request, { params }: RouteParams) {
  const { id } = await params;
  const body = await request.json();
  try {
    const user = await apiFetch<User>(`/api/v1/auth/users/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    return NextResponse.json(user);
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
