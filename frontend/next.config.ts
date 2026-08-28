import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone output keeps the production image small enough to rebuild on a
  // café mini PC without pulling the whole node_modules tree into the layer.
  output: "standalone",
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: false },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
