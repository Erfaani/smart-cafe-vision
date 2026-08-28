import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Smart Café Vision",
    template: "%s · Smart Café Vision",
  },
  description:
    "Anonymous, local-first occupancy and stay-time analytics for cafés and restaurants.",
  // The dashboard is an internal tool on a café LAN; keep it out of any index.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
