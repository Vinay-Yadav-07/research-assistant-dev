"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import {
  type Kind,
  type Result,
  ResultView,
  SaveButton,
  useSourceViewer,
} from "@/components/analysis/results";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDocuments } from "@/components/workspaces/document-library";
import { api, type Schemas, unwrap } from "@/lib/api/client";

const TABS: { kind: Kind; label: string; topic: boolean; hint: string }[] = [
  {
    kind: "compare",
    label: "Compare",
    topic: false,
    hint: "Objective, methods, materials, setup, findings and limitations, side by side.",
  },
  {
    kind: "synthesize",
    label: "Synthesis",
    topic: true,
    hint: "Themes across the papers on one topic.",
  },
  {
    kind: "contradictions",
    label: "Contradictions",
    topic: true,
    hint: "Findings on one topic that may disagree.",
  },
  {
    kind: "gaps",
    label: "Gaps",
    topic: false,
    hint: "Open questions from the papers' limitations and future work.",
  },
];

const FINDING_TYPE: Record<Result["kind"], Schemas["FindingCreate"]["type"]> = {
  compare: "comparison",
  synthesize: "answer",
  contradictions: "contradiction",
  gaps: "gap",
  answer: "answer",
};

async function runAnalysis(
  kind: Kind,
  workspaceId: string,
  documentIds: string[],
  topic: string,
): Promise<Result> {
  const params = { path: { workspace_id: workspaceId } };
  const ids = { document_ids: documentIds };
  switch (kind) {
    case "compare":
      return {
        kind,
        data: await unwrap(
          api.POST("/api/v1/workspaces/{workspace_id}/compare", {
            params,
            body: ids,
          }),
        ),
      };
    case "synthesize":
      return {
        kind,
        data: await unwrap(
          api.POST("/api/v1/workspaces/{workspace_id}/synthesize", {
            params,
            body: { ...ids, topic },
          }),
        ),
      };
    case "contradictions":
      return {
        kind,
        data: await unwrap(
          api.POST("/api/v1/workspaces/{workspace_id}/contradictions", {
            params,
            body: { ...ids, topic },
          }),
        ),
      };
    case "gaps":
      return {
        kind,
        data: await unwrap(
          api.POST("/api/v1/workspaces/{workspace_id}/gaps", {
            params,
            body: ids,
          }),
        ),
      };
  }
}

/** Compare, synthesis, contradictions and gaps over chosen papers, run on demand (FR-18–21). */
export function Analysis({ workspaceId }: { workspaceId: string }) {
  const documents = useDocuments(workspaceId);
  const ready = useMemo(
    () => (documents.data ?? []).filter((d) => d.status === "ready"),
    [documents.data],
  );
  const docsById = useMemo(() => new Map(ready.map((d) => [d.id, d])), [ready]);
  const { cite, viewer } = useSourceViewer(docsById);

  const [tab, setTab] = useState<Kind>("compare");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [topic, setTopic] = useState("");
  const [results, setResults] = useState<
    Partial<Record<Kind, { result: Result; title: string }>>
  >({});
  // Bumped per result so a new result gets a fresh Save button.
  const [runCount, setRunCount] = useState(0);

  const current = TABS.find((t) => t.kind === tab)!;
  const run = useMutation({
    mutationFn: async (kind: Kind) => {
      // The title names what the analysis ran on, even if the choice changes meanwhile.
      const title = titleFor(kind);
      const result = await runAnalysis(
        kind,
        workspaceId,
        [...selected],
        topic.trim(),
      );
      return { result, title };
    },
    onSuccess: (done) => {
      setResults((r) => ({ ...r, [done.result.kind]: done }));
      setRunCount((n) => n + 1);
    },
  });
  const shown = results[tab];
  const canRun =
    selected.size >= 2 && (!current.topic || topic.trim().length > 0);

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  function titleFor(kind: Kind) {
    const tabInfo = TABS.find((t) => t.kind === kind)!;
    const about = tabInfo.topic
      ? topic.trim()
      : [...selected]
          .map((id) => docsById.get(id)?.title ?? "Untitled paper")
          .join("; ");
    return `${tabInfo.label}: ${about}`.slice(0, 300);
  }

  return (
    <div>
      <Link
        href={`/workspaces/${workspaceId}`}
        className="link-draw tap-target text-sm text-muted-foreground"
      >
        ← Library
      </Link>
      <h1 className="mt-3 text-3xl font-medium">Analysis</h1>
      <p className="mt-2 text-muted-foreground">
        Choose two or more papers, then run an analysis. Every statement cites
        the passage it comes from.
      </p>

      <fieldset className="mt-8">
        <legend className="text-xs font-medium tracking-[0.08em] text-muted-foreground uppercase">
          Papers · {selected.size} selected
        </legend>
        {documents.isPending ? (
          <p className="mt-2 text-muted-foreground">Loading papers…</p>
        ) : documents.isError ? (
          <p role="alert" className="mt-2 text-destructive">
            Couldn&apos;t load papers: {documents.error.message}
          </p>
        ) : ready.length < 2 ? (
          <p className="mt-2 text-muted-foreground">
            Analysis needs at least two ready papers in this workspace.
          </p>
        ) : (
          <ul className="mt-2 divide-y border-y">
            {ready.map((d) => (
              <li key={d.id}>
                <label className="flex min-h-10 cursor-pointer items-start gap-3 py-2.5">
                  <input
                    type="checkbox"
                    className="mt-1.5 size-4 accent-foreground"
                    checked={selected.has(d.id)}
                    onChange={() => toggle(d.id)}
                  />
                  <span className="min-w-0">
                    <span className="block font-serif leading-snug break-words">
                      {d.title ?? "Untitled paper"}
                    </span>
                    {(d.authors?.[0] || d.year) && (
                      <span className="block text-sm text-muted-foreground">
                        {[d.authors?.[0], d.year].filter(Boolean).join(" · ")}
                      </span>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      <div
        role="tablist"
        aria-label="Analysis type"
        className="mt-8 flex flex-wrap gap-1 border-b"
      >
        {TABS.map((t) => (
          <button
            key={t.kind}
            type="button"
            role="tab"
            aria-selected={tab === t.kind}
            onClick={() => setTab(t.kind)}
            className="tap-target -mb-px min-h-10 border-b-2 border-transparent px-3 text-sm text-muted-foreground transition-colors duration-[120ms] hover:text-foreground aria-selected:border-foreground aria-selected:text-foreground"
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-label={current.label} className="mt-4">
        <p className="text-sm text-muted-foreground">{current.hint}</p>
        <form
          className="mt-3 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (canRun && !run.isPending) run.mutate(tab);
          }}
        >
          {current.topic && (
            <Input
              aria-label="Topic"
              placeholder="Topic, e.g. scaffold porosity and cell viability"
              value={topic}
              maxLength={500}
              onChange={(e) => setTopic(e.target.value)}
              className="h-10"
            />
          )}
          <Button
            type="submit"
            className="h-10 px-4"
            disabled={!canRun || run.isPending}
          >
            {run.isPending ? "Running…" : `Run ${current.label.toLowerCase()}`}
          </Button>
        </form>

        <p role="status" aria-live="polite" className="mt-3 text-sm">
          {run.isPending && "Reading the papers. This can take a minute."}
        </p>
        {run.isError && run.variables === tab && (
          <p role="alert" className="text-destructive">
            {run.error.message}
          </p>
        )}

        {shown && (
          <div className="mt-6">
            <div className="mb-3 flex justify-end">
              <SaveButton
                key={runCount}
                workspaceId={workspaceId}
                finding={() => ({
                  type: FINDING_TYPE[shown.result.kind],
                  title: shown.title,
                  content: shown.result.data,
                })}
              />
            </div>
            <ResultView id={tab} result={shown.result} cite={cite} />
          </div>
        )}
      </div>
      {viewer}
    </div>
  );
}
