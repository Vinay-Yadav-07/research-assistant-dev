"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bookmark, BookmarkCheck } from "lucide-react";
import dynamic from "next/dynamic";
import { type ReactNode, useState } from "react";

import { asCitation } from "@/components/analysis/citations";
import { citationLabel, Sources, STATUS } from "@/components/chat/answer";
import { ModeBadge } from "@/components/chat/mode-badge";
import { Button } from "@/components/ui/button";
import { api, type Schemas, unwrap } from "@/lib/api/client";

type Citation = Schemas["CitationRead"];
type Document = Schemas["DocumentRead"];
type Draft = Schemas["CitationDraft"];
export type ComparisonTable = Schemas["ComparisonTable"];
export type ThemeSynthesis = Schemas["ThemeSynthesis"];
export type ContradictionReport = Schemas["ContradictionReport"];
export type GapReport = Schemas["GapReport"];

export type Kind = "compare" | "synthesize" | "contradictions" | "gaps";
export type Result =
  | { kind: "compare"; data: ComparisonTable }
  | { kind: "synthesize"; data: ThemeSynthesis }
  | { kind: "contradictions"; data: ContradictionReport }
  | { kind: "gaps"; data: GapReport }
  | { kind: "answer"; data: SavedAnswer };

/** A chat answer as the Save button on it stores it. */
export type SavedAnswer = {
  question: string;
  mode: Schemas["MessageRead"]["mode"];
  claims: Schemas["ClaimRead"][];
};

const SourceViewer = dynamic(() => import("@/components/chat/source-viewer"), {
  ssr: false,
});

/** What a result needs to show citation chips: the papers by id and a way to open a source. */
export type Cite = {
  documents: Map<string, Document>;
  onOpen: (c: Citation) => void;
};

/** One source viewer for a page of results; returns the `onOpen` the chips call and the viewer. */
export function useSourceViewer(documents: Map<string, Document>) {
  const [source, setSource] = useState<Citation | null>(null);
  const viewer = (
    <SourceViewer
      citation={source}
      label={source ? citationLabel(source, documents) : ""}
      onClose={() => setSource(null)}
    />
  );
  return { cite: { documents, onOpen: setSource } satisfies Cite, viewer };
}

function Chips({
  id,
  citations,
  cite,
}: {
  id: string;
  citations: Draft[];
  cite: Cite;
}) {
  return (
    <Sources
      claimId={id}
      citations={citations.map((c, i) => asCitation(c, String(i)))}
      documents={cite.documents}
      onOpen={cite.onOpen}
    />
  );
}

const ATTRIBUTE_LABEL: Record<string, string> = {
  objective: "Objective",
  methodology: "Methodology",
  materials: "Materials",
  setup: "Setup",
  findings: "Findings",
  limitations: "Limitations",
};

/** Papers as columns, attributes as rows; every cell is cited or says "Not reported" (FR-18). */
function ComparisonView({
  id,
  table,
  cite,
}: {
  id: string;
  table: ComparisonTable;
  cite: Cite;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] border-collapse text-left align-top text-sm">
        <thead>
          <tr className="border-b">
            <th scope="col" className="w-28 py-2 pr-3" />
            {table.papers.map((p) => (
              <th
                key={p.document_id}
                scope="col"
                className="py-2 pr-4 font-serif text-base leading-snug font-medium"
              >
                {p.document_title ?? "Untitled paper"}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.attributes.map((attr) => (
            <tr key={attr} className="border-b align-top">
              <th
                scope="row"
                className="py-3 pr-3 text-xs font-medium tracking-[0.08em] text-muted-foreground uppercase"
              >
                {ATTRIBUTE_LABEL[attr] ?? attr}
              </th>
              {table.papers.map((p) => {
                const cell = p.cells.find((c) => c.attribute === attr);
                return (
                  <td key={p.document_id} className="py-3 pr-4">
                    {!cell || !cell.reported ? (
                      <span className="text-muted-foreground italic">
                        Not reported
                      </span>
                    ) : (
                      <>
                        <p className="font-serif leading-relaxed">
                          {cell.text}
                        </p>
                        <Chips
                          id={`${id}-${p.document_id}-${attr}`}
                          citations={cell.citations}
                          cite={cite}
                        />
                      </>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClaimList({
  id,
  claims,
  cite,
}: {
  id: string;
  claims: { text: string; citations: Draft[] }[];
  cite: Cite;
}) {
  return (
    <ul className="divide-y border-y">
      {claims.map((claim, i) => (
        <li key={i} className="py-3">
          <p className="max-w-[68ch] font-serif leading-relaxed">
            {claim.text}
          </p>
          <Chips id={`${id}-${i}`} citations={claim.citations} cite={cite} />
        </li>
      ))}
    </ul>
  );
}

/** Themes across papers, each claim citing every paper it names (FR-19). */
function SynthesisView({
  id,
  synthesis,
  cite,
}: {
  id: string;
  synthesis: ThemeSynthesis;
  cite: Cite;
}) {
  if (synthesis.themes.length === 0)
    return <Empty>The papers say nothing on this topic.</Empty>;
  return (
    <div className="space-y-6">
      {synthesis.themes.map((theme, i) => (
        <section key={i}>
          <h3 className="font-serif text-lg font-medium">{theme.title}</h3>
          <div className="mt-2">
            <ClaimList id={`${id}-${i}`} claims={theme.claims} cite={cite} />
          </div>
        </section>
      ))}
    </div>
  );
}

const PAIR_LABEL = {
  potential_contradiction: "Potential contradiction",
  context_dependent: "Depends on context",
} as const;

/** Pairs of findings that may disagree, with the context check's note (FR-20). */
function ContradictionsView({
  id,
  report,
  cite,
}: {
  id: string;
  report: ContradictionReport;
  cite: Cite;
}) {
  if (report.contradictions.length === 0)
    return <Empty>No disagreements found between these papers.</Empty>;
  return (
    <ul className="space-y-6">
      {report.contradictions.map((pair, i) => (
        <li key={i} className="border-l-2 border-border pl-4">
          <p className="text-xs font-medium tracking-[0.08em] text-muted-foreground uppercase">
            {PAIR_LABEL[pair.label]}
          </p>
          {[pair.finding_a, pair.finding_b].map((f, side) => (
            <div key={side} className="mt-2">
              <p className="max-w-[68ch] font-serif leading-relaxed">
                {f.text}
              </p>
              <Chips
                id={`${id}-${i}-${side}`}
                citations={f.citations}
                cite={cite}
              />
            </div>
          ))}
          {pair.context_note && (
            <p className="mt-2 text-sm text-muted-foreground">
              {pair.context_note}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Potential gaps from the papers' limitations and future work, each with evidence (FR-21). */
function GapsView({
  id,
  report,
  cite,
}: {
  id: string;
  report: GapReport;
  cite: Cite;
}) {
  if (report.gaps.length === 0)
    return <Empty>The papers name no limitations or open questions.</Empty>;
  return (
    <>
      <p className="mb-2 text-sm text-muted-foreground">
        Potential gaps, read from what these papers say they did not do.
      </p>
      <ClaimList id={id} claims={report.gaps} cite={cite} />
    </>
  );
}

/** Renders any analysis result, fresh or saved. */
export function ResultView({
  id,
  result,
  cite,
}: {
  id: string;
  result: Result;
  cite: Cite;
}) {
  switch (result.kind) {
    case "compare":
      return <ComparisonView id={id} table={result.data} cite={cite} />;
    case "synthesize":
      return <SynthesisView id={id} synthesis={result.data} cite={cite} />;
    case "contradictions":
      return <ContradictionsView id={id} report={result.data} cite={cite} />;
    case "gaps":
      return <GapsView id={id} report={result.data} cite={cite} />;
    case "answer":
      return <AnswerView id={id} answer={result.data} cite={cite} />;
  }
}

function AnswerView({
  id,
  answer,
  cite,
}: {
  id: string;
  answer: SavedAnswer;
  cite: Cite;
}) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <p className="font-serif text-lg leading-snug">{answer.question}</p>
        <ModeBadge mode={answer.mode} />
      </div>
      <ol className="mt-2 divide-y border-y">
        {answer.claims.map((claim, i) => {
          const { label, Icon, className } = STATUS[claim.status];
          return (
            <li key={claim.id} className="py-3">
              <span
                className={`inline-flex items-center gap-1.5 text-sm font-medium ${className}`}
              >
                <Icon aria-hidden className="size-4" />
                {label}
              </span>
              <p className="mt-1 max-w-[68ch] font-serif leading-relaxed">
                {claim.text}
              </p>
              <Sources
                claimId={`${id}-${i}`}
                citations={claim.citations}
                documents={cite.documents}
                onOpen={cite.onOpen}
              />
            </li>
          );
        })}
      </ol>
    </>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-muted-foreground">{children}</p>;
}

/** Saves an output as a finding (FR-26); the button stays "Saved" for that output. */
export function SaveButton({
  workspaceId,
  finding,
}: {
  workspaceId: string;
  finding: () => Schemas["FindingCreate"];
}) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/findings", {
          params: { path: { workspace_id: workspaceId } },
          body: finding(),
        }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["findings", workspaceId] }),
  });
  return (
    <span className="inline-flex items-center gap-2">
      <Button
        variant="ghost"
        className="h-10"
        disabled={save.isPending || save.isSuccess}
        onClick={() => save.mutate()}
      >
        {save.isSuccess ? (
          <BookmarkCheck aria-hidden />
        ) : (
          <Bookmark aria-hidden />
        )}
        {save.isSuccess ? "Saved" : save.isPending ? "Saving…" : "Save finding"}
      </Button>
      {save.isError && (
        <span role="alert" className="text-sm text-destructive">
          {save.error.message}
        </span>
      )}
    </span>
  );
}
