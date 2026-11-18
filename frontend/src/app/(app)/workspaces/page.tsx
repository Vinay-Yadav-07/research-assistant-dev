import type { Metadata } from "next";

import { WorkspaceList } from "@/components/workspaces/workspace-list";

export const metadata: Metadata = { title: "Workspaces · Research Assistant" };

export default function WorkspacesPage() {
  return <WorkspaceList />;
}
