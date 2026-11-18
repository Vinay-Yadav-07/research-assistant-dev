"use client";

import { animate, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { RESULTS } from "./content";
import { Reveal } from "./reveal";

/** Phase 2 figures that count up once when scrolled into view. */
export function Results() {
  return (
    <div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-10 lg:grid-cols-4">
        {RESULTS.map((r, i) => (
          <Reveal
            key={r.label}
            index={i}
            className="flex flex-col border-t pt-4"
          >
            <dt className="order-2 mt-2 text-sm text-muted-foreground">
              {r.label}
              <sup className="ml-0.5 font-mono">*</sup>
            </dt>
            <dd className="font-mono text-4xl tabular-nums sm:text-5xl">
              <CountUp to={r.value} decimals={r.decimals} />
              <span className="text-muted-foreground">{r.suffix}</span>
            </dd>
          </Reveal>
        ))}
      </dl>
      <p className="mt-10 font-mono text-xs text-muted-foreground">
        * Provisional · 12 test items, 2026-10-07. Measured on the deployed
        Space; the benchmark is still being verified.
      </p>
    </div>
  );
}

function CountUp({ to, decimals }: { to: number; decimals: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const reduced = useReducedMotion();
  const hydrated = useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!inView || reduced) return;
    const controls = animate(0, to, {
      duration: 1.2,
      ease: [0.23, 1, 0.32, 1],
      onUpdate: setValue,
    });
    return () => controls.stop();
  }, [inView, reduced, to]);

  // Server markup and reduced motion show the final figure; the client counts up from 0.
  const shown = !hydrated || reduced ? to : value;
  return <span ref={ref}>{shown.toFixed(decimals)}</span>;
}

const noop = () => () => {};
