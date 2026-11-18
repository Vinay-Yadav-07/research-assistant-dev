import type { Metadata } from "next";

import { DocumentLibrary } from "@/components/workspaces/document-library";

export const metadata: Metadata = { title: "Library · Research Assistant" };

export default async function WorkspacePage({
  params,
}: PageProps<"/workspaces/[id]">) {
  const { id } = await params;
  return <DocumentLibrary workspaceId={id} />;
}
