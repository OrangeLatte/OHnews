import { redirect } from "next/navigation";

/**
 * 旧 /sources 路由薄壳：IA 迁移后信源管理并入 /watch（sources tab）。
 * 显式透传其余 query 参数（next/navigation 的 redirect() 不自动合并原请求 query，
 * 自动透传是 next.config redirects 的行为），如 /sources?x=1 → /watch?tab=sources&x=1。
 */
export default async function SourcesPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const sp = await searchParams;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    if (value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) params.append(key, item);
  }
  params.set("tab", "sources");
  redirect(`/watch?${params.toString()}`);
}
