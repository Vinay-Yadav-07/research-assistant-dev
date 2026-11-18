import type { Metadata } from "next";

import { KnowledgeGraph } from "@/components/graph/knowledge-graph";

export const metadata: Metadata = {
  title: "Knowledge graph · Research Assistant",
};

export default async function GraphPage({
  params,
}: PageProps<"/workspaces/[id]/graph">) {
  const { id } = await params;
  return <KnowledgeGraph workspaceId={id} />;
}
