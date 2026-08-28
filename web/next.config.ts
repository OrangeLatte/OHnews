import type { NextConfig } from "next";

const API_PORT = process.env.OHNEWS_API_PORT ?? "8787";
// 容器网络下 web→api 用服务名（OHNEWS_API_ORIGIN=http://api）；本地默认 127.0.0.1
const API_ORIGIN = process.env.OHNEWS_API_ORIGIN ?? "http://127.0.0.1";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_ORIGIN}:${API_PORT}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
