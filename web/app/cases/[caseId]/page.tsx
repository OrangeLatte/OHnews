"use client";

import { useParams } from "next/navigation";
import CaseWorkspace from "@/components/case/case-workspace";

export default function CaseDetailPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = Array.isArray(params?.caseId) ? params.caseId[0] : (params?.caseId ?? "");
  if (!caseId) return null;
  return <CaseWorkspace caseId={caseId} />;
}
