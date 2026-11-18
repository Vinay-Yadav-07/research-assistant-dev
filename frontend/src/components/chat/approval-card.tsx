import { CircleCheck, CircleDot, CircleMinus } from "lucide-react";
import { motion } from "motion/react";

import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/client";
import type { Decision } from "@/lib/api/stream";

type Coverage = Schemas["SubQuestionCoverage"];

const COVERAGE: Record<
  Coverage["coverage"],
  { label: string; Icon: typeof CircleCheck; className: string }
> = {
  covered: {
    label: "Covered",
    Icon: CircleCheck,
    className: "text-status-supported",
  },
  partial: {
    label: "Partly covered",
    Icon: CircleDot,
    className: "text-status-partial",
  },
  insufficient: {
    label: "Not covered",
    Icon: CircleMinus,
    className: "text-muted-foreground",
  },
};

/**
 * The run paused because the corpus is insufficient (FR-14). Shows what the papers do and don't
 * cover and asks how to continue; nothing is pre-selected and the run never continues on its own.
 */
export function ApprovalCard({
  request,
  busy,
  onDecide,
}: {
  request: Schemas["ApprovalRequest"];
  busy: boolean;
  onDecide: (decision: Decision) => void;
}) {
  const offers = (d: Decision) => request.options.includes(d);
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.23, 1, 0.32, 1] }}
      aria-labelledby="approval-title"
      className="rounded-[10px] border bg-card p-4 sm:p-5"
    >
      <h3 id="approval-title" className="font-serif text-xl font-medium">
        Your papers don&apos;t fully cover this
      </h3>
      {/* The sub-question list says the same thing in more detail. */}
      {request.sub_questions.length === 0 && (
        <p className="mt-1.5 max-w-prose text-muted-foreground">
          {request.reason}
        </p>
      )}

      {request.sub_questions.length > 0 && (
        <ul className="mt-4 divide-y border-y">
          {request.sub_questions.map((q) => {
            const { label, Icon, className } = COVERAGE[q.coverage];
            return (
              <li
                key={q.id}
                className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr] sm:gap-4"
              >
                <span
                  className={`inline-flex items-start gap-1.5 text-sm font-medium ${className}`}
                >
                  <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
                  {label}
                </span>
                <div className="min-w-0">
                  <p className="font-serif leading-snug">{q.text}</p>
                  {q.reason && (
                    <p className="mt-1 text-sm text-muted-foreground">
                      {q.reason}
                    </p>
                  )}
                  {q.closest && (
                    <p className="mt-1 text-sm break-words text-muted-foreground">
                      Closest: {q.closest.document_title ?? "Untitled paper"}{" "}
                      <span className="font-mono text-xs">
                        · p.{q.closest.page_start}
                        {q.closest.page_end !== q.closest.page_start &&
                          `–${q.closest.page_end}`}
                        {q.closest.section && ` · ${q.closest.section}`}
                      </span>
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-5 text-sm font-medium">How should I continue?</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <Option
          label="Stay corpus-only"
          detail="Answer only what your papers support."
          autoFocus
          disabled={busy}
          onClick={() => onDecide("corpus_only")}
        />
        {offers("general_knowledge") && (
          <Option
            label="Use general knowledge"
            detail="Fill gaps from the model, labelled as not from your papers."
            disabled={busy}
            onClick={() => onDecide("general_knowledge")}
          />
        )}
        {offers("corpus_web") && (
          <Option
            label="Search external sources"
            detail="Available in Phase 5."
            disabled
          />
        )}
      </div>
    </motion.section>
  );
}

function Option({
  label,
  detail,
  autoFocus,
  disabled,
  onClick,
}: {
  label: string;
  detail: string;
  autoFocus?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <Button
      variant="outline"
      autoFocus={autoFocus}
      disabled={disabled}
      onClick={onClick}
      className="h-auto flex-col items-start justify-start gap-0.5 rounded-[6px] px-3 py-2.5 text-left whitespace-normal"
    >
      <span>{label}</span>
      <span className="text-xs font-normal text-muted-foreground">
        {detail}
      </span>
    </Button>
  );
}
