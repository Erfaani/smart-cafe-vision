"use client";

import { useEffect, useState } from "react";

import { DisplayEmptyState } from "@/components/display/empty-state";
import type { PublicDisplayMessage } from "@/lib/types";

const MESSAGE_ROTATE_MS = 6000;

/** Rotates through the café's configured funny messages (Phase 7, "spec:
 * configurable funny messages in Persian and English"). Deliberately
 * untargeted -- see apps/display/models.py's module docstring for why a
 * message never references a specific tracked person. */
export function DisplayEntertainmentMode({ messages }: { messages: PublicDisplayMessage[] }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setIndex(0);
    if (messages.length <= 1) return;
    const interval = setInterval(() => setIndex((i) => (i + 1) % messages.length), MESSAGE_ROTATE_MS);
    return () => clearInterval(interval);
  }, [messages.length]);

  const message = messages[index % messages.length];
  if (!message) {
    return <DisplayEmptyState message="No messages configured yet." />;
  }

  return (
    <div className="flex h-full min-h-[40vh] items-center justify-center">
      <p key={message.id} className="max-w-3xl text-center text-5xl font-semibold leading-tight text-white">
        {message.text}
      </p>
    </div>
  );
}
