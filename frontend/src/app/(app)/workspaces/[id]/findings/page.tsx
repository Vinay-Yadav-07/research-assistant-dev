import type { Metadata } from "next";

import { Findings } from "@/components/analysis/findings";

export const metadata: Metadata = {
  title: "Saved findings · Research Assistant",
};

export default async function FindingsPage({
  params,
}: PageProps<"/workspaces/[id]/findings">) {
  const { id } = await params;
  return <Findings workspaceId={id} />;
}
