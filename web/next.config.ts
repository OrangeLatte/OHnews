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
  async redirects() {
    return [
      // 阶段 1.5 IA 手术：19 路由 → NOW/WATCH/INVESTIGATE/MEMORY + settings
      { source: "/command", destination: "/", permanent: false },
      { source: "/today", destination: "/", permanent: false },
      { source: "/brief", destination: "/", permanent: false },
      { source: "/alerts", destination: "/watch", permanent: false },
      { source: "/agent", destination: "/investigate/research", permanent: false },
      { source: "/research", destination: "/investigate/research", permanent: false },
      { source: "/chat", destination: "/investigate/research", permanent: false },
      { source: "/intel", destination: "/investigate/patrol", permanent: false },
      { source: "/timeline", destination: "/investigate/timeline", permanent: false },
      { source: "/events", destination: "/investigate", permanent: false },
      { source: "/analyze", destination: "/investigate", permanent: false },
      { source: "/analyze/:id", destination: "/events/:id", permanent: false },
      { source: "/library", destination: "/memory", permanent: false },
      { source: "/decisions", destination: "/memory", permanent: false },
      { source: "/dev/monitor", destination: "/settings/developer", permanent: false },
    ];
  },
};

export default nextConfig;
