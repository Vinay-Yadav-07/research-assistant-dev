"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { type FormEvent, useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api, type Schemas, unwrap } from "@/lib/api/client";

type Workspace = Schemas["WorkspaceRead"];

/** All the user's workspaces, newest first, archived included. */
export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces", { params: { query: { limit: 100 } } }),
      ),
  });
}

/** Workspace index: create, open, rename, archive, delete. */
export function WorkspaceList() {
  const queryClient = useQueryClient();
  const workspaces = useWorkspaces();
  const [editing, setEditing] = useState<Workspace | "new" | null>(null);
  const [deleting, setDeleting] = useState<Workspace | null>(null);

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["workspaces"] });

  const archive = useMutation({
    mutationFn: (w: Workspace) =>
      unwrap(
        api.PATCH("/api/v1/workspaces/{workspace_id}", {
          params: { path: { workspace_id: w.id } },
          body: { archived: !w.archived },
        }),
      ),
    onSuccess: refresh,
  });

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl font-medium">Workspaces</h1>
        <Button className="h-10 px-4" onClick={() => setEditing("new")}>
          New workspace
        </Button>
      </div>

      <div className="mt-8">
        {workspaces.isPending ? (
          <p className="text-muted-foreground">Loading workspaces…</p>
        ) : workspaces.isError ? (
          <p role="alert" className="text-destructive">
            Couldn&apos;t load workspaces: {workspaces.error.message}
          </p>
        ) : workspaces.data.length === 0 ? (
          <p className="text-muted-foreground">
            No workspaces yet. Create one for a research topic, then upload its
            papers.
          </p>
        ) : (
          <ul className="divide-y border-y">
            {workspaces.data.map((w) => (
              <li
                key={w.id}
                className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <Link
                    href={`/workspaces/${w.id}`}
                    className="link-draw font-serif text-lg font-medium break-words data-[archived]:text-muted-foreground"
                    data-archived={w.archived || undefined}
                  >
                    {w.name}
                  </Link>
                  {w.archived && (
                    <span className="ml-2 font-mono text-xs text-muted-foreground uppercase">
                      Archived
                    </span>
                  )}
                  {w.description && (
                    <p className="mt-0.5 text-sm break-words text-muted-foreground">
                      {w.description}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-1 text-sm">
                  <Button
                    variant="ghost"
                    className="h-10"
                    onClick={() => setEditing(w)}
                  >
                    Rename
                  </Button>
                  <Button
                    variant="ghost"
                    className="h-10"
                    disabled={archive.isPending}
                    onClick={() => archive.mutate(w)}
                  >
                    {w.archived ? "Unarchive" : "Archive"}
                  </Button>
                  <Button
                    variant="ghost"
                    className="h-10 text-destructive"
                    onClick={() => setDeleting(w)}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {archive.isError && (
          <p role="alert" className="mt-3 text-sm text-destructive">
            {archive.error.message}
          </p>
        )}
      </div>

      <WorkspaceDialog
        key={editing === "new" ? "new" : editing?.id}
        workspace={editing}
        onClose={() => setEditing(null)}
        onSaved={refresh}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete “${deleting?.name ?? ""}”?`}
        description="Its conversations are deleted too. Papers used by no other workspace are deleted with it. This can't be undone."
        confirmLabel="Delete workspace"
        onConfirm={async () => {
          if (!deleting) return;
          await unwrap(
            api.DELETE("/api/v1/workspaces/{workspace_id}", {
              params: { path: { workspace_id: deleting.id } },
            }),
          );
          await refresh();
        }}
      />
    </div>
  );
}

/** Create (`workspace === "new"`) or rename a workspace. */
function WorkspaceDialog({
  workspace,
  onClose,
  onSaved,
}: {
  workspace: Workspace | "new" | null;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const existing = workspace === "new" ? null : workspace;
  const save = useMutation({
    mutationFn: (body: { name: string; description: string | null }) =>
      existing
        ? unwrap(
            api.PATCH("/api/v1/workspaces/{workspace_id}", {
              params: { path: { workspace_id: existing.id } },
              body,
            }),
          )
        : unwrap(
            api.POST("/api/v1/workspaces", {
              body: { ...body, default_mode: "corpus_only" },
            }),
          ),
    onSuccess: async () => {
      await onSaved();
      onClose();
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const description = String(form.get("description")).trim();
    save.mutate({
      name: String(form.get("name")).trim(),
      description: description || null,
    });
  }

  return (
    <Dialog
      open={workspace !== null}
      onOpenChange={(open) => !open && onClose()}
    >
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>
              {existing ? "Rename workspace" : "New workspace"}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-1.5">
            <label htmlFor="ws-name" className="text-sm font-medium">
              Name
            </label>
            <Input
              id="ws-name"
              name="name"
              required
              maxLength={120}
              defaultValue={existing?.name}
              className="h-10"
            />
          </div>
          <div className="grid gap-1.5">
            <label htmlFor="ws-description" className="text-sm font-medium">
              Description{" "}
              <span className="text-muted-foreground">(optional)</span>
            </label>
            <Input
              id="ws-description"
              name="description"
              maxLength={2000}
              defaultValue={existing?.description ?? ""}
              className="h-10"
            />
          </div>
          {save.isError && (
            <p role="alert" className="text-sm text-destructive">
              {save.error.message}
            </p>
          )}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" className="h-10" />}>
              Cancel
            </DialogClose>
            <Button type="submit" className="h-10" disabled={save.isPending}>
              {existing ? "Save" : "Create workspace"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
