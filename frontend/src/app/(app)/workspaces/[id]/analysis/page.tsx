import type { Metadata } from "next";

import { Analysis } from "@/components/analysis/analysis";

export const metadata: Metadata = { title: "Analysis · Research Assistant" };

export default async function AnalysisPage({
  params,
}: PageProps<"/workspaces/[id]/analysis">) {
  const { id } = await params;
  return <Analysis workspaceId={id} />;
}
