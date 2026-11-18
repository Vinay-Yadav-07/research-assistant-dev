"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  type Result,
  ResultView,
  useSourceViewer,
} from "@/components/analysis/results";
import { Button } from "@/components/ui/button";
import { useDocuments } from "@/components/workspaces/document-library";
import { api, type Schemas, unwrap } from "@/lib/api/client";

type Finding = Schemas["FindingRead"];

const TYPE_LABEL: Record<Finding["type"], string> = {
  answer: "Answer",
  comparison: "Comparison",
  contradiction: "Contradictions",
  gap: "Gaps",
  review: "Review",
};

const EXPORTS = {
  md: { label: "Markdown", file: "findings.md", type: "text/markdown" },
  bibtex: {
    label: "BibTeX",
    file: "findings.bib",
    type: "application/x-bibtex",
  },
} as const;

/** The stored output in the shape its renderer takes, told apart by its fields. */
function asResult(content: Finding["content"]): Result | null {
  const data = content as never;
  if ("papers" in content) return { kind: "compare", data };
  if ("themes" in content) return { kind: "synthesize", data };
  if ("contradictions" in content) return { kind: "contradictions", data };
  if ("gaps" in content) return { kind: "gaps", data };
  if ("claims" in content) return { kind: "answer", data };
  return null;
}

/** Saved findings with Markdown and BibTeX export (FR-26, FR-32). */
export function Findings({ workspaceId }: { workspaceId: string }) {
  const path = { workspace_id: workspaceId };
  const findings = useQuery({
    queryKey: ["findings", workspaceId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/findings", {
          params: { path },
        }),
      ),
  });
  const documents = useDocuments(workspaceId);
  const docsById = useMemo(
    () => new Map((documents.data ?? []).map((d) => [d.id, d])),
    [documents.data],
  );
  const { cite, viewer } = useSourceViewer(docsById);
  const [exportError, setExportError] = useState<string>();

  const download = async (format: keyof typeof EXPORTS) => {
    setExportError(undefined);
    try {
      const text = await unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/findings/export", {
          params: { path, query: { format } },
          parseAs: "text",
        }),
      );
      const { file, type } = EXPORTS[format];
      const url = URL.createObjectURL(new Blob([text], { type }));
      const a = Object.assign(document.createElement("a"), {
        href: url,
        download: file,
      });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <Link
        href={`/workspaces/${workspaceId}`}
        className="link-draw tap-target text-sm text-muted-foreground"
      >
        ← Library
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <h1 className="text-3xl font-medium">Saved findings</h1>
        {findings.data && findings.data.length > 0 && (
          <div className="flex gap-2">
            {(Object.keys(EXPORTS) as (keyof typeof EXPORTS)[]).map((f) => (
              <Button
                key={f}
                variant="outline"
                className="h-10 px-3"
                onClick={() => void download(f)}
              >
                <Download aria-hidden />
                {EXPORTS[f].label}
              </Button>
            ))}
          </div>
        )}
      </div>
      {exportError && (
        <p role="alert" className="mt-2 text-destructive">
          Export failed: {exportError}
        </p>
      )}

      <div className="mt-8">
        {findings.isPending ? (
          <p className="text-muted-foreground">Loading findings…</p>
        ) : findings.isError ? (
          <p role="alert" className="text-destructive">
            Couldn&apos;t load findings: {findings.error.message}
          </p>
        ) : findings.data.length === 0 ? (
          <p className="text-muted-foreground">
            Nothing saved yet. Use &ldquo;Save finding&rdquo; on an answer or an
            analysis.
          </p>
        ) : (
          <ul className="divide-y border-y">
            {findings.data.map((f) => {
              const result = asResult(f.content);
              return (
                <li key={f.id}>
                  <details className="group py-3">
                    <summary className="tap-target flex min-h-10 cursor-pointer list-none flex-col justify-center">
                      <span className="font-serif text-lg leading-snug break-words">
                        {f.title}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {TYPE_LABEL[f.type]} ·{" "}
                        {new Date(f.created_at).toLocaleDateString()}
                      </span>
                    </summary>
                    <div className="mt-4">
                      {result ? (
                        <ResultView id={f.id} result={result} cite={cite} />
                      ) : (
                        <p className="text-muted-foreground">
                          This finding can&apos;t be shown here; it is included
                          in the Markdown export.
                        </p>
                      )}
                    </div>
                  </details>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {viewer}
    </div>
  );
}
