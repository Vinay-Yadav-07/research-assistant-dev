import type { Metadata } from "next";

import { Chat } from "@/components/chat/chat";

export const metadata: Metadata = { title: "Ask · Research Assistant" };

export default async function ChatPage({
  params,
}: PageProps<"/workspaces/[id]/chat">) {
  const { id } = await params;
  return <Chat workspaceId={id} />;
}
