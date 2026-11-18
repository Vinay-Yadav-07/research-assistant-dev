import { CircleHelp, MessageSquare } from "lucide-react";

import { CitationChip } from "./citation-chip";
import { UNANSWERABLE } from "./content";
import { Reveal } from "./reveal";

/** The same unanswerable benchmark question, answered by a plain chatbot and by this assistant. */
export function Comparison() {
  return (
    <div>
      <Reveal>
        <p className="eyebrow">Benchmark question test-051</p>
        <p className="mt-3 max-w-3xl font-serif text-xl leading-snug sm:text-2xl">
          “{UNANSWERABLE.question}”
        </p>
        <p className="mt-3 max-w-prose text-muted-foreground">
          None of the papers in the workspace report this. Here is what each
          kind of assistant does with it.
        </p>
      </Reveal>

      <div className="mt-10 grid gap-6 md:grid-cols-2">
        <Reveal
          index={1}
          className="rounded-[10px] border border-dashed p-5 sm:p-6"
        >
          <div className="flex items-center justify-between gap-3">
            <p className="flex items-center gap-2 text-sm font-medium">
              <MessageSquare className="size-4" aria-hidden />A plain chatbot
            </p>
            <span className="eyebrow">Illustration</span>
          </div>
          <p className="mt-4 font-serif text-lg leading-relaxed">
            {UNANSWERABLE.chatbot}
          </p>
          <p className="mt-4 text-sm text-muted-foreground">
            Confident, specific and unsourced. Nothing tells you the number
            isn&apos;t in your papers.
          </p>
        </Reveal>

        <Reveal index={2} className="rounded-[10px] border bg-card p-5 sm:p-6">
          <p className="flex items-center gap-2 text-sm font-medium">
            <CircleHelp className="size-4 text-status-uncertain" aria-hidden />
            Research Assistant
          </p>
          <p className="mt-4 font-serif text-lg leading-relaxed">
            Your papers don&apos;t report how much copper the scaffolds released
            per day.
          </p>
          <p className="eyebrow mt-5">What they do cover</p>
          <ul className="mt-2 space-y-3 text-sm leading-relaxed">
            {UNANSWERABLE.covered.map((c, i) => (
              <li key={c.cite}>
                {c.text}{" "}
                <CitationChip
                  id={`cover-${i}`}
                  label={c.cite}
                  preview={
                    i === 0
                      ? "The elements Si, O, Mg, Ca, and Cu were found to be evenly distributed over the hollow scaffold's cross-sectional surface."
                      : "Cu-DIO extract had the same proliferation trend on HUVECs and Saos-2 cells after 1, 3, and 7 days of incubation."
                  }
                />
              </li>
            ))}
          </ul>
          <p className="eyebrow mt-5">Continue with</p>
          <ul className="mt-2 flex flex-wrap gap-2 text-sm">
            <li className="rounded-[6px] border border-foreground px-3 py-2">
              Stay corpus-only
            </li>
            <li className="rounded-[6px] border px-3 py-2">
              Use general knowledge
            </li>
            <li className="rounded-[6px] border border-dashed px-3 py-2 text-muted-foreground">
              Search external sources ·{" "}
              <span className="font-mono text-xs">Phase 5</span>
            </li>
          </ul>
        </Reveal>
      </div>
    </div>
  );
}
