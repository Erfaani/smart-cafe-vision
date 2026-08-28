"use client";

import { useState } from "react";

import { CameraForm } from "@/components/camera-form";
import { CameraTable } from "@/components/camera-table";
import type { Camera } from "@/lib/types";

export function CamerasPageClient({ cameras }: { cameras: Camera[] }) {
  const [adding, setAdding] = useState(false);

  return (
    <div className="space-y-4">
      {adding ? (
        <CameraForm onDone={() => setAdding(false)} onCancel={() => setAdding(false)} />
      ) : (
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface"
        >
          Add camera
        </button>
      )}

      <CameraTable cameras={cameras} />
    </div>
  );
}
