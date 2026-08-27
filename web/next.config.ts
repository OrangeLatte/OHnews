import type { NextConfig } from "next";

const API_PORT = process.env.OHNEWS_API_PORT ?? "8787";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `http://127.0.0.1:${API_PORT}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
