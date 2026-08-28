import { NextResponse } from "next/server";

import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Camera } from "@/lib/types";

/** Create a camera. Listing happens server-side in the dashboard page itself
 * (apiFetch called directly from a Server Component) -- this route exists
 * only for the client-side "Add camera" form. */
export async function POST(request: Request) {
  const body = await request.json();
  try {
    const camera = await apiFetch<Camera>("/api/v1/cameras/", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return NextResponse.json(camera, { status: 201 });
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return NextResponse.json({ error: { code: error.code, message: error.message, detail: error.detail } }, { status: error.status });
    }
    throw error;
  }
}
