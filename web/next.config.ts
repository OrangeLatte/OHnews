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
    // Clean-slate A7：旧 IA 全部 REPLACE/DELETE，级联合并为单一新映射（30d redirect）。
    return [
      // 旧 NOW 首页族 → OBSERVE
      { source: "/", destination: "/observe", permanent: false },
      { source: "/command", destination: "/observe", permanent: false },
      { source: "/today", destination: "/observe", permanent: false },
      { source: "/brief", destination: "/observe", permanent: false },
      // 旧 WATCH 族 → /watch?tab=monitors（IA 迁移：/watch 现为真实页面，
      // 原 /watch→/monitors 重定向已删除——否则 /watch ⇄ /monitors 死循环）
      { source: "/alerts", destination: "/watch?tab=monitors", permanent: false },
      // 旧 INVESTIGATE/对话族 → CASES（对话并入全局 Agent Dock）
      { source: "/agent", destination: "/cases", permanent: false },
      { source: "/research", destination: "/cases", permanent: false },
      { source: "/chat", destination: "/cases", permanent: false },
      { source: "/investigate", destination: "/cases", permanent: false },
      { source: "/investigate/research", destination: "/cases", permanent: false },
      { source: "/analyze", destination: "/cases", permanent: false },
      { source: "/analyze/:id", destination: "/cases", permanent: false },
      { source: "/events/:id", destination: "/cases", permanent: false },
      // 事件流/patrol/timeline 族 → OBSERVE（实体历史入 Entities Lens）
      { source: "/intel", destination: "/observe", permanent: false },
      { source: "/investigate/patrol", destination: "/observe", permanent: false },
      { source: "/investigate/timeline", destination: "/observe", permanent: false },
      { source: "/timeline", destination: "/observe", permanent: false },
      { source: "/events", destination: "/observe", permanent: false },
      { source: "/changes", destination: "/observe", permanent: false },
      { source: "/changes/:id", destination: "/observe", permanent: false },
      // 旧 MEMORY 族 → ARCHIVE
      { source: "/library", destination: "/archive", permanent: false },
      { source: "/decisions", destination: "/archive", permanent: false },
      { source: "/memory", destination: "/archive", permanent: false },
      // 开发者工具入口保留（settings/developer 未在 A7 删除范围）
      { source: "/dev/monitor", destination: "/settings/developer", permanent: false },
    ];
  },
};

export default nextConfig;
