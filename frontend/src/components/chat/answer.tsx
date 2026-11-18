import {
  CircleCheck,
  CircleDot,
  CircleQuestionMark,
  CircleX,
  ExternalLink,
} from "lucide-react";
import { motion } from "motion/react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { CitationChip } from "@/components/landing/citation-chip";
import type { Schemas } from "@/lib/api/client";

type Claim = Schemas["ClaimRead"];
type Citation = Schemas["CitationRead"];
type Document = Schemas["DocumentRead"];

const SourceViewer = dynamic(() => import("@/components/chat/source-viewer"), {
  ssr: false,
});

/** Icon, label and colour of each claim status (trust-ui). */
export const STATUS: Record<
  Claim["status"],
  { label: string; Icon: typeof CircleCheck; className: string }
> = {
  supported: {
    label: "Supported",
    Icon: CircleCheck,
    className: "text-status-supported",
  },
  partially_supported: {
    label: "Partly supported",
    Icon: CircleDot,
    className: "text-status-partial",
  },
  unsupported: {
    label: "Not supported",
    Icon: CircleX,
    className: "text-status-unsupported",
  },
  uncertain: {
    label: "Uncertain",
    Icon: CircleQuestionMark,
    className: "text-status-uncertain",
  },
};

type Segment = { text: string; claim?: number };

/** Splits the answer into plain text and claim sentences; claims not found verbatim are left out. */
function annotate(content: string, claims: Claim[]) {
  const segments: Segment[] = [];
  const placed = new Set<number>();
  let cursor = 0;
  claims.forEach((claim, i) => {
    const at = content.indexOf(claim.text, cursor);
    if (at === -1) return;
    if (at > cursor) segments.push({ text: content.slice(cursor, at) });
    segments.push({ text: claim.text, claim: i });
    placed.add(i);
    cursor = at + claim.text.length;
  });
  if (cursor < content.length) segments.push({ text: content.slice(cursor) });
  return { segments, placed };
}

/**
 * An answer set like a paper: superscript markers in the prose and one footnote per claim with
 * its status and citations (DESIGN.md §6). A claim the prose does not contain verbatim shows its
 * text in the footnote. `animate` staggers the footnotes in when they have just arrived.
 */
export function AnnotatedAnswer({
  messageId,
  content,
  claims,
  documents,
  animate,
}: {
  messageId: string;
  content: string;
  claims: Claim[];
  documents: Map<string, Document>;
  animate: boolean;
}) {
  const { segments, placed } = annotate(content, claims);
  const supported = claims.filter((c) => c.status === "supported").length;
  const note = (i: number) => `note-${messageId}-${i}`;
  const [source, setSource] = useState<Citation | null>(null);
  return (
    <>
      <p className="max-w-[68ch] font-serif text-[1.0625rem] leading-[1.6] whitespace-pre-line">
        {segments.map((s, k) =>
          s.claim === undefined ? (
            s.text
          ) : (
            <span key={k}>
              {s.text}
              <sup className="ml-px font-mono text-[0.7em]">
                <a
                  href={`#${note(s.claim)}`}
                  aria-label={`Claim ${s.claim + 1}: ${STATUS[claims[s.claim].status].label}`}
                  className="rounded-[2px] px-0.5 text-muted-foreground hover:text-foreground"
                >
                  {s.claim + 1}
                </a>
              </sup>
            </span>
          ),
        )}
      </p>
      {claims.length > 0 && (
        <section className="mt-6" aria-label="Claims">
          <p className="text-xs font-medium tracking-[0.08em] text-muted-foreground uppercase">
            Claims · {supported} of {claims.length} supported
          </p>
          <ol className="mt-2 divide-y border-y">
            {claims.map((claim, i) => {
              const { label, Icon, className } = STATUS[claim.status];
              return (
                <motion.li
                  key={claim.id}
                  id={note(i)}
                  initial={animate ? { opacity: 0, y: 12 } : false}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: 0.32,
                    delay: i * 0.07,
                    ease: [0.23, 1, 0.32, 1],
                  }}
                  className="grid scroll-mt-24 grid-cols-[1.5rem_1fr] gap-x-2 py-2.5 target:bg-mark/15 sm:grid-cols-[1.5rem_9.5rem_1fr]"
                >
                  <span className="pt-0.5 font-mono text-xs text-muted-foreground tabular-nums">
                    {i + 1}
                  </span>
                  <span
                    className={`inline-flex items-start gap-1.5 text-sm font-medium ${className}`}
                  >
                    <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
                    {label}
                  </span>
                  <div className="col-start-2 min-w-0 sm:col-start-3">
                    {!placed.has(i) && (
                      <p className="mb-1.5 font-serif leading-snug">
                        {claim.text}
                      </p>
                    )}
                    <Sources
                      claimId={claim.id}
                      citations={claim.citations}
                      documents={documents}
                      onOpen={setSource}
                    />
                  </div>
                </motion.li>
              );
            })}
          </ol>
        </section>
      )}
      <SourceViewer
        citation={source}
        label={source ? citationLabel(source, documents) : ""}
        onClose={() => setSource(null)}
      />
    </>
  );
}

/** A claim's citation chips, plus the External and General-knowledge labels (trust-ui). */
export function Sources({
  claimId,
  citations,
  documents,
  onOpen,
}: {
  claimId: string;
  citations: Citation[];
  documents: Map<string, Document>;
  onOpen: (citation: Citation) => void;
}) {
  const general = citations.some((c) => c.source_type === "general");
  const chips = citations.filter((c) => c.source_type !== "general");
  if (!general && chips.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5 sm:mt-0">
      {chips.map((c) => (
        <CitationChip
          key={c.id}
          id={`cite-${claimId}-${c.id}`}
          label={citationLabel(c, documents)}
          preview={<Preview citation={c} />}
          onClick={
            c.source_type === "workspace" && c.document_id
              ? () => onOpen(c)
              : undefined
          }
        />
      ))}
      {chips.some((c) => c.source_type === "external") && (
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <ExternalLink aria-hidden className="size-3.5" />
          External
        </span>
      )}
      {general && (
        <span className="text-sm text-status-general">
          General knowledge — not from your papers
        </span>
      )}
    </div>
  );
}

function Preview({ citation: c }: { citation: Citation }) {
  return (
    <>
      {c.quote ? (
        <span className="block">
          <mark className="rounded-[2px] bg-mark px-0.5 text-mark-foreground">
            {c.quote}
          </mark>
        </span>
      ) : (
        <span className="block text-muted-foreground">No passage stored.</span>
      )}
      <span className="mt-2 block font-sans text-xs break-words text-muted-foreground">
        {c.document_title ?? "Untitled paper"}
        {c.section && <span className="font-mono"> · {c.section}</span>}
      </span>
    </>
  );
}

/** `Surname Year · p.N` (DESIGN.md §6); falls back to a shortened title when authors are unknown. */
export function citationLabel(c: Citation, documents: Map<string, Document>) {
  const doc = c.document_id ? documents.get(c.document_id) : undefined;
  const first = doc?.authors?.[0]?.trim().split(/\s+/).at(-1);
  const author = first
    ? `${first}${(doc?.authors?.length ?? 0) > 1 ? " et al." : ""}`
    : shorten(c.document_title ?? doc?.title ?? "Source");
  const who = [author, doc?.year].filter(Boolean).join(" ");
  if (c.page_start === null) return who;
  const pages =
    c.page_end !== null && c.page_end !== c.page_start
      ? `p.${c.page_start}–${c.page_end}`
      : `p.${c.page_start}`;
  return `${who} · ${pages}`;
}

function shorten(title: string) {
  return title.length > 28 ? `${title.slice(0, 26).trimEnd()}…` : title;
}
