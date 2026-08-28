import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { TableEditor } from "@/components/table-editor";
import { ApiRequestError, apiFetch } from "@/lib/api";
import type { Camera, TableZone } from "@/lib/types";

export const metadata: Metadata = { title: "Tables" };
export const dynamic = "force-dynamic";

export default async function CameraTablesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let camera: Camera;
  let tables: TableZone[];
  try {
    [camera, tables] = await Promise.all([
      apiFetch<Camera>(`/api/v1/cameras/${id}/`),
      apiFetch<TableZone[]>(`/api/v1/cameras/${id}/tables/`),
    ]);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 404) notFound();
    throw error;
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <Link href="/dashboard/cameras" className="text-xs text-ink-muted hover:text-ink">
          &larr; Cameras
        </Link>
        <h1 className="mt-1 text-lg font-semibold tracking-tight text-ink">
          Tables — {camera.name}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">
          Draw a rectangle over each table to detect when it&apos;s occupied. Only a position and a
          timestamp are ever recorded — nobody&apos;s presence at a table is otherwise identified.
        </p>
      </header>

      <TableEditor camera={camera} initialTables={tables} />
    </div>
  );
}
