import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginForm } from "@/components/login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-surface px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Smart Café Vision</h1>
          <p className="mt-1 text-sm text-ink-muted">Sign in to your café dashboard.</p>
        </div>

        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>

        <p className="mt-8 text-xs leading-relaxed text-ink-muted">
          This system measures how busy the café is using anonymous camera analytics. It does
          not recognise faces, store identities, or keep footage.
        </p>
      </div>
    </main>
  );
}
