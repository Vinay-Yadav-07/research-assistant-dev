"use client";

import { Check, CircleCheck, CircleX, Pause, Play } from "lucide-react";
import { AnimatePresence, motion, useInView } from "motion/react";
import { type FocusEvent, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { CitationChip } from "./citation-chip";
import { DEMO_CLAIMS, DEMO_QUESTION, PANG, STAGES } from "./content";
import { useReducedAfterMount } from "./use-reduced";

const TICK = 50;
const TYPE_END = 1500;
const STAGE_START = 1700;
const STAGE_LEN = 550;
const stageAt = (i: number) => STAGE_START + i * STAGE_LEN;
const CLAIMS_AT = stageAt(3);
const REMOVED_AT = stageAt(4) + 350;
const HIGHLIGHT_AT = stageAt(5);
const LOOP = 10500;
const ease = [0.23, 1, 0.32, 1] as const;

/**
 * Looping hero demo: question → pipeline stages → claims with citations → one claim
 * removed → the cited passage highlighted on its page. Pauses off-screen, on mouse hover,
 * on keyboard focus, or with the button; reduced motion shows the final frame (DESIGN.md §7).
 */
export function HeroDemo() {
  const reduced = useReducedAfterMount();
  const [elapsed, setElapsed] = useState(0);
  const [held, setHeld] = useState(false);
  const [stopped, setStopped] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref);
  const running = !reduced && !held && !stopped && inView;

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setElapsed((ms) => (ms + TICK) % LOOP), TICK);
    return () => clearInterval(id);
  }, [running]);

  const ms = reduced ? LOOP - 1 : elapsed;
  const typed = DEMO_QUESTION.slice(
    0,
    Math.round((DEMO_QUESTION.length * Math.min(ms, TYPE_END)) / TYPE_END),
  );
  const stage =
    ms < STAGE_START ? -1 : Math.floor((ms - STAGE_START) / STAGE_LEN);
  const highlighted = ms >= HIGHLIGHT_AT;

  return (
    <div
      ref={ref}
      className="relative pb-44 sm:pb-40"
      // Mouse and keyboard only: a tap would otherwise leave the demo paused.
      onPointerEnter={(e) => e.pointerType === "mouse" && setHeld(true)}
      onPointerLeave={(e) => e.pointerType === "mouse" && setHeld(false)}
      onFocus={(e: FocusEvent) =>
        e.target.matches(":focus-visible") && setHeld(true)
      }
      onBlur={() => setHeld(false)}
    >
      {/* The cited page, stacked behind the answer card. */}
      <div
        aria-hidden
        className="absolute right-0 bottom-0 w-[88%] rotate-[2deg] rounded-[4px] border bg-surface-sunk px-5 pt-24 pb-5 shadow-[0_18px_40px_-24px_var(--shadow-warm)] sm:w-[80%]"
      >
        <p className="font-serif text-[0.8rem] leading-relaxed text-foreground/80">
          {PANG.before}
          <motion.span
            className={cn(
              "transition-colors duration-300",
              highlighted ? "text-mark-foreground" : "text-foreground",
            )}
            style={{
              backgroundImage:
                "linear-gradient(var(--highlight), var(--highlight))",
              backgroundRepeat: "no-repeat",
              boxDecorationBreak: "clone",
              WebkitBoxDecorationBreak: "clone",
            }}
            initial={false}
            animate={{ backgroundSize: highlighted ? "100% 100%" : "0% 100%" }}
            transition={{ duration: highlighted ? 0.7 : 0, ease }}
          >
            {PANG.highlight}
          </motion.span>
          {PANG.after}
        </p>
        <p className="mt-3 text-right font-mono text-[0.7rem] text-muted-foreground">
          {PANG.arxiv} · p.10
        </p>
      </div>

      <figure className="relative z-10 w-[94%] rounded-[10px] border bg-card p-5 shadow-[0_12px_32px_-20px_var(--shadow-warm)] sm:w-[88%] sm:p-6">
        <div className="flex items-center justify-between gap-3">
          <figcaption className="eyebrow">Example run</figcaption>
          {!reduced && (
            <button
              type="button"
              onClick={() => setStopped((s) => !s)}
              aria-label={stopped ? "Play the demo" : "Pause the demo"}
              className="-m-2 inline-flex size-10 items-center justify-center rounded-[6px] text-muted-foreground transition-[color,transform] duration-[120ms] hover:text-foreground active:scale-[0.97]"
            >
              {stopped ? (
                <Play className="size-4" aria-hidden />
              ) : (
                <Pause className="size-4" aria-hidden />
              )}
            </button>
          )}
        </div>

        <p className="mt-3 min-h-[3lh] text-sm font-medium sm:min-h-[2lh]">
          <span aria-hidden>{typed}</span>
          {!reduced && ms < TYPE_END && (
            <span
              aria-hidden
              className="ml-px inline-block h-4 w-px translate-y-0.5 bg-foreground"
            />
          )}
          <span className="sr-only">{DEMO_QUESTION}</span>
        </p>

        <ol
          aria-label="Pipeline stages"
          className="mt-3 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[0.7rem]"
        >
          {STAGES.map((name, i) => (
            <li
              key={name}
              className={cn(
                "inline-flex items-center gap-1 transition-colors duration-200",
                i < stage || ms >= LOOP - 1
                  ? "text-muted-foreground"
                  : i === stage
                    ? "text-foreground"
                    : "text-muted-foreground/60",
              )}
            >
              {(i < stage || ms >= LOOP - 1) && (
                <Check className="size-3" aria-hidden />
              )}
              {name}
            </li>
          ))}
        </ol>

        <ul className="mt-4 space-y-3 font-serif text-[0.95rem] leading-snug">
          <AnimatePresence initial={false}>
            {DEMO_CLAIMS.map((claim, i) => {
              if (ms < CLAIMS_AT + i * 300) return null;
              const removed = claim.removed && ms >= REMOVED_AT;
              return (
                <motion.li
                  key={claim.text}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: removed ? 0.6 : 1, y: 0 }}
                  exit={{ opacity: 0, transition: { duration: 0.15 } }}
                  transition={{ duration: 0.35, ease }}
                  className="grid grid-cols-[1fr_auto] gap-3"
                >
                  <span>
                    {/* Strike drawn per line: a 1px gradient band swept left to right. */}
                    <motion.span
                      style={{
                        backgroundImage:
                          "linear-gradient(var(--unsupported), var(--unsupported))",
                        backgroundRepeat: "no-repeat",
                        backgroundPosition: "0 55%",
                        boxDecorationBreak: "clone",
                        WebkitBoxDecorationBreak: "clone",
                      }}
                      initial={false}
                      animate={{
                        backgroundSize: removed ? "100% 1px" : "0% 1px",
                      }}
                      transition={{ duration: removed ? 0.4 : 0, ease }}
                    >
                      {claim.text}
                    </motion.span>
                    {!claim.removed && (
                      <sup className="ml-0.5 font-mono">¹</sup>
                    )}
                  </span>
                  <span className="pt-0.5 font-sans text-[0.7rem] leading-tight">
                    {claim.removed ? (
                      removed && (
                        <span className="inline-flex flex-col items-end gap-0.5 text-right text-status-unsupported">
                          <span className="inline-flex items-center gap-1">
                            <CircleX className="size-3.5" aria-hidden />
                            Unsupported — removed
                          </span>
                          <span className="eyebrow text-[0.6rem]">
                            Illustration
                          </span>
                        </span>
                      )
                    ) : (
                      <span className="inline-flex items-center gap-1 text-status-supported">
                        <CircleCheck className="size-3.5" aria-hidden />
                        Supported
                      </span>
                    )}
                  </span>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>

        <div className="mt-4 flex min-h-7 items-center border-t pt-3">
          {ms >= CLAIMS_AT && (
            <CitationChip
              id="hero-cite"
              marker="¹"
              label={PANG.cite}
              preview={
                <>
                  …{PANG.highlight}…
                  <span className="mt-2 block font-mono text-xs text-muted-foreground">
                    {PANG.arxiv}
                  </span>
                </>
              }
            />
          )}
        </div>
      </figure>
    </div>
  );
}
