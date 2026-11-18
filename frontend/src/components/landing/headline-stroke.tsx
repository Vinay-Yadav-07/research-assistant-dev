"use client";

import { motion, useReducedMotion } from "motion/react";

/**
 * Highlighter block drawn behind the headline's last words on load (DESIGN.md §1 signature).
 * It covers the full letter height, so the words are set in `--highlight-ink` in both themes.
 */
export function HeadlineStroke() {
  const reduced = useReducedMotion();
  return (
    <svg
      aria-hidden
      viewBox="0 0 300 40"
      preserveAspectRatio="none"
      className="absolute -inset-x-[0.12em] top-[0.02em] -z-10 h-[1.08em] w-[calc(100%+0.24em)] overflow-visible"
    >
      <motion.path
        d="M6 21 C 60 17, 140 24, 200 19 S 276 20, 294 21"
        fill="none"
        stroke="var(--highlight)"
        strokeWidth="36"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={
          reduced
            ? { duration: 0 }
            : { duration: 0.8, delay: 0.35, ease: [0.77, 0, 0.175, 1] }
        }
      />
    </svg>
  );
}
