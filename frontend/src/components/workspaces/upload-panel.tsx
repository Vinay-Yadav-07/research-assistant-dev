"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { type DragEvent, useRef, useState } from "react";

import { useWorkspaces } from "@/components/workspaces/workspace-list";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, ApiError, type Schemas, unwrap } from "@/lib/api/client";

type Workspace = Schemas["WorkspaceRead"];
type Document = Schemas["DocumentRead"];

// Matches the backend's `max_upload_bytes` default.
const MAX_BYTES = 25 * 1024 * 1024;

type Step =
  | { kind: "idle" }
  | { kind: "busy"; message: string }
  | { kind: "done"; message: string; link?: { href: string; label: string } }
  | { kind: "error"; message: string }
  | {
      kind: "unrelated";
      file: File;
      target: Workspace;
      score: number | null;
      threshold: number;
    }
  | { kind: "move"; file: File }
  | {
      kind: "duplicate";
      document: Document;
      target: Workspace;
      override: boolean;
    };

/** A PDF as multipart form data; openapi-fetch sends FormData as-is. */
function pdfForm(file: File, override?: boolean) {
  const form = new FormData();
  form.append("file", file);
  if (override !== undefined) form.append("override", String(override));
  return form as never;
}

/**
 * Upload flow (FR-03, FR-22): compatibility check → upload, with dialogs for an unrelated
 * paper (Import anyway / Move to another workspace / Cancel) and for a file the user already has.
 */
export function UploadPanel({ workspace }: { workspace: Workspace }) {
  const queryClient = useQueryClient();
  const workspaces = useWorkspaces();
  const input = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);

  const close = () => setStep({ kind: "idle" });

  /** Runs `action`, turning any failure into an error message. */
  async function attempt(action: () => Promise<void>) {
    try {
      await action();
    } catch (e) {
      setStep({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }

  function done(target: Workspace, message: string) {
    void queryClient.invalidateQueries({ queryKey: ["documents", target.id] });
    setStep(
      target.id === workspace.id
        ? { kind: "done", message }
        : {
            kind: "done",
            message: `${message} It went to “${target.name}”.`,
            link: {
              href: `/workspaces/${target.id}`,
              label: `Open ${target.name}`,
            },
          },
    );
  }

  const check = (file: File, target: Workspace) =>
    attempt(async () => {
      setStep({
        kind: "busy",
        message: `Checking ${file.name} against the workspace topic…`,
      });
      const result = await unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/documents/compatibility", {
          params: { path: { workspace_id: target.id } },
          body: pdfForm(file),
        }),
      );
      if (result.compatible) return upload(file, target, false);
      setStep({
        kind: "unrelated",
        file,
        target,
        score: result.score,
        threshold: result.threshold,
      });
    });

  const upload = (file: File, target: Workspace, override: boolean) =>
    attempt(async () => {
      setStep({ kind: "busy", message: `Uploading ${file.name}…` });
      const result = await unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/documents", {
          params: { path: { workspace_id: target.id } },
          body: pdfForm(file, override),
        }),
      );
      if (!result.duplicate)
        return done(
          target,
          target.id === workspace.id
            ? "Uploaded. Its status updates below while it is processed."
            : "Uploaded.",
        );
      if (result.linked)
        return done(target, "This paper is already in the workspace.");
      setStep({
        kind: "duplicate",
        document: result.document,
        target,
        override,
      });
    });

  const link = (document: Document, target: Workspace, override: boolean) =>
    attempt(async () => {
      setStep({ kind: "busy", message: "Adding your existing copy…" });
      try {
        await unwrap(
          api.PUT("/api/v1/workspaces/{workspace_id}/documents/{document_id}", {
            params: {
              path: { workspace_id: target.id, document_id: document.id },
              query: { override },
            },
          }),
        );
      } catch (e) {
        if (e instanceof ApiError && e.code === "compatibility_warning")
          throw new Error(
            "Your existing copy looks unrelated to this workspace, so it wasn't added.",
          );
        throw e;
      }
      done(target, "Added your existing copy of this paper.");
    });

  function pick(file: File | undefined) {
    if (!file) return;
    if (
      file.type !== "application/pdf" &&
      !file.name.toLowerCase().endsWith(".pdf")
    )
      return setStep({ kind: "error", message: `${file.name} isn't a PDF.` });
    if (file.size > MAX_BYTES)
      return setStep({
        kind: "error",
        message: `${file.name} is larger than 25 MB.`,
      });
    void check(file, workspace);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    pick(event.dataTransfer.files[0]);
  }

  const busy = step.kind === "busy";
  const others = (workspaces.data ?? []).filter(
    (w) => w.id !== workspace.id && !w.archived,
  );

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-dragging={dragging || undefined}
        className="flex flex-col items-start gap-3 rounded-lg border border-dashed p-5 data-[dragging]:border-foreground data-[dragging]:bg-muted sm:flex-row sm:items-center sm:justify-between"
      >
        <p className="text-sm text-muted-foreground">
          Drop a PDF here, up to 25 MB. Each paper is checked against the
          workspace topic first.
        </p>
        <Button
          className="h-10 shrink-0 px-4"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          Upload PDF
        </Button>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>

      <div aria-live="polite" className="mt-3 min-h-6 text-sm">
        {step.kind === "busy" && (
          <p className="text-muted-foreground">{step.message}</p>
        )}
        {step.kind === "done" && (
          <p>
            {step.message}{" "}
            {step.link && (
              <Link href={step.link.href} className="link-draw underline">
                {step.link.label}
              </Link>
            )}
          </p>
        )}
        {step.kind === "error" && (
          <p role="alert" className="text-destructive">
            {step.message}
          </p>
        )}
      </div>

      <Dialog
        open={step.kind === "unrelated"}
        onOpenChange={(o) => !o && close()}
      >
        {step.kind === "unrelated" && (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>This paper looks unrelated</DialogTitle>
              <DialogDescription>
                {step.file.name} doesn&apos;t match the topic of “
                {step.target.name}”
                {step.score !== null && (
                  <>
                    {" "}
                    (similarity{" "}
                    <span className="font-mono">{step.score.toFixed(2)}</span>,
                    threshold{" "}
                    <span className="font-mono">
                      {step.threshold.toFixed(2)}
                    </span>
                    )
                  </>
                )}
                . Unrelated papers can lower answer quality.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose
                render={<Button variant="outline" className="h-10" />}
              >
                Cancel
              </DialogClose>
              <Button
                variant="outline"
                className="h-10"
                onClick={() => setStep({ kind: "move", file: step.file })}
              >
                Move to another workspace
              </Button>
              <Button
                className="h-10"
                onClick={() => upload(step.file, step.target, true)}
              >
                Import anyway
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>

      <Dialog open={step.kind === "move"} onOpenChange={(o) => !o && close()}>
        {step.kind === "move" && (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Move to another workspace</DialogTitle>
              <DialogDescription>
                {step.file.name} is checked against the workspace you choose.
              </DialogDescription>
            </DialogHeader>
            {others.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                You have no other active workspace. Create one on the{" "}
                <Link href="/workspaces" className="underline">
                  workspaces page
                </Link>{" "}
                first.
              </p>
            ) : (
              <ul className="grid max-h-72 gap-1 overflow-y-auto">
                {others.map((w) => (
                  <li key={w.id}>
                    <Button
                      variant="ghost"
                      className="h-10 w-full justify-start truncate"
                      onClick={() => check(step.file, w)}
                    >
                      {w.name}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <DialogFooter>
              <DialogClose
                render={<Button variant="outline" className="h-10" />}
              >
                Cancel
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>

      <Dialog
        open={step.kind === "duplicate"}
        onOpenChange={(o) => !o && close()}
      >
        {step.kind === "duplicate" && (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>You&apos;ve uploaded this paper before</DialogTitle>
              <DialogDescription>
                “{step.document.title ?? "This paper"}” is already in another of
                your workspaces. Add the same copy to “{step.target.name}”? It
                isn&apos;t processed again.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose
                render={<Button variant="outline" className="h-10" />}
              >
                Cancel
              </DialogClose>
              <Button
                className="h-10"
                onClick={() => link(step.document, step.target, step.override)}
              >
                Add to this workspace
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}
