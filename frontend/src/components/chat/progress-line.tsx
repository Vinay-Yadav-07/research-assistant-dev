import { Check } from "lucide-react";
import { motion } from "motion/react";

import type { Schemas } from "@/lib/api/client";

export type Stage = Schemas["StatusEvent"]["stage"];

const STAGE_LABEL: Record<Stage, string> = {
  analyzing: "Reading the question",
  retrieving: "Searching your papers",
  assessing: "Checking the evidence",
  writing: "Writing",
  verifying: "Verifying claims",
  citing: "Citing sources",
};

/** A small dot that pulses while the app is working (still when the user prefers reduced motion). */
export function WorkingDot() {
  return (
    <span
      aria-hidden
      className="inline-block size-1.5 rounded-full bg-foreground motion-safe:animate-pulse"
    />
  );
}

/** The run's stages so far as one mono line: done stages muted with a tick, the current one in ink. */
export function ProgressLine({ stages }: { stages: Stage[] }) {
  if (stages.length === 0)
    return (
      <p className="inline-flex items-center gap-2 font-mono text-xs text-muted-foreground">
        <WorkingDot />
        Starting…
      </p>
    );
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs">
      {stages.map((stage, i) => {
        const current = i === stages.length - 1;
        return (
          <motion.li
            key={stage}
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
            className="inline-flex items-center gap-1 data-[done]:text-muted-foreground"
            data-done={current ? undefined : ""}
            aria-current={current ? "step" : undefined}
          >
            {!current && <Check aria-hidden className="size-3" />}
            {STAGE_LABEL[stage]}
            {current && <WorkingDot />}
            {!current && (
              <span aria-hidden className="ml-1 text-border">
                ·
              </span>
            )}
          </motion.li>
        );
      })}
    </ol>
  );
}
