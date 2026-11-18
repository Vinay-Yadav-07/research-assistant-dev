import type { Metadata } from "next";

import { Discover } from "@/components/discover/discover";

export const metadata: Metadata = {
  title: "Discover · Research Assistant",
};

export default async function DiscoverPage({
  searchParams,
}: PageProps<"/discover">) {
  const { workspace } = await searchParams;
  return (
    <Discover
      initialWorkspaceId={typeof workspace === "string" ? workspace : null}
    />
  );
}
