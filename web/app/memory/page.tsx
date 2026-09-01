"use client";

import { LibrarySection } from "@/app/memory/library-section";
import { DecisionsSection } from "@/app/memory/decisions-section";

/* MEMORY（阶段 1.5 IA 手术）：我的判断如何变化 = 认知时间线 + 决策日志 + 研究档案 */
export default function MemoryPage() {
  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="font-paper text-3xl tracking-tight">MEMORY · 认知档案</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          你的判断如何随证据变化：认知快照时间线、决策回填、研究沉淀。系统只记录，不代写。
        </p>
      </div>
      <DecisionsSection />
      <LibrarySection />
    </div>
  );
}
