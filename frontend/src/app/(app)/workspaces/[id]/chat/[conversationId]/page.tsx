import type { Metadata } from "next";

import { Chat } from "@/components/chat/chat";

export const metadata: Metadata = {
  title: "Conversation · Research Assistant",
};

export default async function ConversationPage({
  params,
}: PageProps<"/workspaces/[id]/chat/[conversationId]">) {
  const { id, conversationId } = await params;
  // Keyed so switching conversations starts a fresh thread state.
  return (
    <Chat
      key={conversationId}
      workspaceId={id}
      conversationId={conversationId}
    />
  );
}
