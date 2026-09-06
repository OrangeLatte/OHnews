import { redirect } from "next/navigation";

/**
 * 旧 /monitors 路由薄壳：IA 迁移后跟踪预警并入 /watch（monitors tab）。
 * 显式透传其余 query 参数（next/navigation 的 redirect() 不自动合并原请求 query，
 * 自动透传是 next.config redirects 的行为），如 /monitors?open=x → /watch?tab=monitors&open=x。
 */
export default async function MonitorsPage({
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
  params.set("tab", "monitors");
  redirect(`/watch?${params.toString()}`);
}
