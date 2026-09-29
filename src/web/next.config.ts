import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  agentRules: false,
  async rewrites() {
    const backend = process.env.API_BASE_URL || "http://localhost:8000";
    return [
      { source: "/themes/:path*", destination: `${backend}/themes/:path*` },
      { source: "/runs/:path*", destination: `${backend}/runs/:path*` },
    ];
  },
};

export default nextConfig;
