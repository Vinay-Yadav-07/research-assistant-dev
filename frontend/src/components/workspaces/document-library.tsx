"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bookmark,
  CircleAlert,
  Columns3,
  CircleCheck,
  LoaderCircle,
  MessagesSquare,
  Network,
  Search,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { UploadPanel } from "@/components/workspaces/upload-panel";
import { api, type Schemas, unwrap } from "@/lib/api/client";

type Document = Schemas["DocumentRead"];

const STATUS_LABEL: Record<Document["status"], string> = {
  uploaded: "Queued",
  parsing: "Reading PDF",
  embedding: "Indexing",
  ready: "Ready",
  failed: "Failed",
};

const isProcessing = (d: Document) =>
  d.status !== "ready" && d.status !== "failed";

/** The workspace's documents, polled while any is still being ingested. */
export function useDocuments(workspaceId: string) {
  return useQuery({
    queryKey: ["documents", workspaceId],
    // ponytail: first 100 documents only (API maximum page); add paging if a workspace outgrows it.
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/documents", {
          params: {
            path: { workspace_id: workspaceId },
            query: { limit: 100 },
          },
        }),
      ),
    // Poll while anything is still being ingested; stop once all are ready or failed.
    refetchInterval: (query) =>
      query.state.data?.some(isProcessing) ? 3000 : false,
  });
}

/** Documents of one workspace with live ingestion status, upload and removal. */
export function DocumentLibrary({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient();
  const [removing, setRemoving] = useState<Document | null>(null);
  const path = { workspace_id: workspaceId };

  const workspace = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}", { params: { path } }),
      ),
  });
  const documents = useDocuments(workspaceId);

  if (workspace.isError)
    return (
      <div>
        <BackLink />
        <p role="alert" className="mt-6 text-destructive">
          {workspace.error.message}
        </p>
      </div>
    );

  return (
    <div>
      <BackLink />
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <h1 className="min-w-0 text-3xl font-medium break-words">
          {workspace.data?.name ?? " "}
        </h1>
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/discover?workspace=${workspaceId}`}
            className={buttonVariants({
              variant: "ghost",
              className: "h-10 px-3",
            })}
          >
            <Search aria-hidden />
            Find papers
          </Link>
          <Link
            href={`/workspaces/${workspaceId}/findings`}
            className={buttonVariants({
              variant: "ghost",
              className: "h-10 px-3",
            })}
          >
            <Bookmark aria-hidden />
            Saved findings
          </Link>
          <Link
            href={`/workspaces/${workspaceId}/graph`}
            className={buttonVariants({
              variant: "outline",
              className: "h-10 px-4",
            })}
          >
            <Network aria-hidden />
            Knowledge graph
          </Link>
          <Link
            href={`/workspaces/${workspaceId}/analysis`}
            className={buttonVariants({
              variant: "outline",
              className: "h-10 px-4",
            })}
          >
            <Columns3 aria-hidden />
            Analysis
          </Link>
          <Link
            href={`/workspaces/${workspaceId}/chat`}
            className={buttonVariants({ className: "h-10 px-4" })}
          >
            <MessagesSquare aria-hidden />
            Ask your papers
          </Link>
        </div>
      </div>
      {workspace.data?.description && (
        <p className="mt-2 text-muted-foreground">
          {workspace.data.description}
        </p>
      )}

      {workspace.data && (
        <div className="mt-8">
          <UploadPanel workspace={workspace.data} />
        </div>
      )}

      <h2 className="mt-10 text-xl font-medium">Papers</h2>
      <div className="mt-3">
        {documents.isPending ? (
          <p className="text-muted-foreground">Loading papers…</p>
        ) : documents.isError ? (
          <p role="alert" className="text-destructive">
            Couldn&apos;t load papers: {documents.error.message}
          </p>
        ) : documents.data.length === 0 ? (
          <p className="text-muted-foreground">
            No papers yet. Upload a PDF or find papers to import, then start
            asking questions.
          </p>
        ) : (
          <ul className="divide-y border-y">
            {documents.data.map((d) => (
              <DocumentRow key={d.id} document={d} onRemove={setRemoving} />
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove this paper from the workspace?"
        description="It stays in any other workspace that uses it; if none does, the paper is deleted."
        confirmLabel="Remove paper"
        onConfirm={async () => {
          if (!removing) return;
          await unwrap(
            api.DELETE(
              "/api/v1/workspaces/{workspace_id}/documents/{document_id}",
              {
                params: { path: { ...path, document_id: removing.id } },
              },
            ),
          );
          await queryClient.invalidateQueries({
            queryKey: ["documents", workspaceId],
          });
        }}
      />
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/workspaces"
      className="link-draw tap-target text-sm text-muted-foreground"
    >
      ← Workspaces
    </Link>
  );
}

function DocumentRow({
  document: d,
  onRemove,
}: {
  document: Document;
  onRemove: (d: Document) => void;
}) {
  const names = d.authors ?? [];
  const authors =
    names.length > 3
      ? `${names.slice(0, 3).join(", ")} et al.`
      : names.join(", ");
  const meta = [authors, d.year, d.venue].filter(Boolean).join(" · ");

  return (
    <li className="flex flex-col gap-2 py-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <p className="font-serif text-lg leading-snug break-words">
          {d.title ?? (isProcessing(d) ? "New paper" : "Untitled paper")}
        </p>
        {meta && (
          <p className="mt-0.5 text-sm break-words text-muted-foreground">
            {meta}
          </p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <StatusLabel status={d.status} />
          {d.page_count !== null && (
            <span className="font-mono text-xs text-muted-foreground">
              {d.page_count} pp.
            </span>
          )}
          {d.doi && (
            <span className="font-mono text-xs break-all text-muted-foreground">
              {d.doi}
            </span>
          )}
        </div>
        {d.status === "failed" && d.error && (
          <p className="mt-1 text-sm text-destructive">{d.error}</p>
        )}
      </div>
      <Button
        variant="ghost"
        className="h-10 shrink-0 self-start text-destructive"
        onClick={() => onRemove(d)}
      >
        Remove
      </Button>
    </li>
  );
}

function StatusLabel({ status }: { status: Document["status"] }) {
  const Icon =
    status === "ready"
      ? CircleCheck
      : status === "failed"
        ? CircleAlert
        : LoaderCircle;
  return (
    <span
      className="inline-flex items-center gap-1.5 data-[status=failed]:text-status-unsupported data-[status=ready]:text-status-supported"
      data-status={status}
    >
      <Icon
        aria-hidden
        className="size-4 data-[spin]:motion-safe:animate-spin"
        data-spin={status !== "ready" && status !== "failed" ? "" : undefined}
      />
      {STATUS_LABEL[status]}
    </span>
  );
}
