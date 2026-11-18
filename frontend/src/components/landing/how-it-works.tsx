"use client";

import { CircleCheck, CircleDot, CircleX, FileText } from "lucide-react";
import { motion, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { DEMO_QUESTION, PANG } from "./content";
import { useReducedAfterMount } from "./use-reduced";

const ease = [0.23, 1, 0.32, 1] as const;

const STEPS = [
  {
    title: "Your PDFs become passages",
    body: "Each paper is parsed, split into passages and indexed with its page and section, so every answer can point back to a page.",
  },
  {
    title: "The question is broken down",
    body: "A question is split into the sub-questions it depends on. Each one is searched on its own, only inside your workspace.",
  },
  {
    title: "Passages are ranked",
    body: "Keyword and meaning search run together, then a reranker reads each candidate passage against the question and reorders them.",
  },
  {
    title: "Every claim is checked",
    body: "The draft is split into claims. Each is tested against its cited passage; a claim the passage doesn't back is removed.",
  },
  {
    title: "No evidence, no answer",
    body: "When your papers don't cover a sub-question, the run stops and asks you what to do. Nothing outside your papers is used without approval.",
  },
];

/** Sticky scroll-driven walkthrough: steps on the right, the matching frame pinned on the left. */
export function HowItWorks() {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLLIElement | null)[]>([]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          if (entry.isIntersecting)
            setActive(Number((entry.target as HTMLElement).dataset.step));
      },
      { rootMargin: "-45% 0px -45% 0px" },
    );
    for (const el of refs.current) if (el) observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="grid gap-12 lg:grid-cols-2 lg:gap-16">
      <div className="hidden lg:block">
        <div className="sticky top-[calc(50vh-11rem)] h-[22rem]">
          <Frame step={active} />
        </div>
      </div>
      <ol>
        {STEPS.map((step, i) => (
          <li
            key={step.title}
            ref={(el) => {
              refs.current[i] = el;
            }}
            data-step={i}
            className="flex flex-col justify-center py-8 lg:min-h-[70vh] lg:py-0"
          >
            <span className="font-mono text-sm text-muted-foreground">
              {String(i + 1).padStart(2, "0")}
            </span>
            <h3
              className={cn(
                "mt-1 text-2xl font-medium transition-colors duration-200",
                active === i ? "text-foreground" : "lg:text-muted-foreground",
              )}
            >
              {step.title}
            </h3>
            <p className="mt-3 max-w-prose leading-relaxed text-muted-foreground">
              {step.body}
            </p>
            {/* Narrow screens: the frame sits under its step instead of pinned. */}
            <div className="mt-6 lg:hidden">
              <Frame step={i} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Frame({ step }: { step: number }) {
  return (
    <motion.div
      key={step}
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.4, ease }}
      className="h-full rounded-[10px] border bg-card p-5 text-sm sm:p-6"
    >
      {step === 0 && <PassagesFrame />}
      {step === 1 && <SubQuestionsFrame />}
      {step === 2 && <RankingFrame />}
      {step === 3 && <VerifyFrame />}
      {step === 4 && <ApprovalFrame />}
    </motion.div>
  );
}

function PassagesFrame() {
  const passages = [
    { tag: "p.3 · Introduction", width: "w-11/12" },
    { tag: "p.10 · Results", width: "w-full", cited: true },
    { tag: "p.14 · Cell viability", width: "w-4/5" },
  ];
  return (
    <div>
      <p className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
        <FileText className="size-4" aria-hidden />
        2303.11051.pdf · 20 pages
      </p>
      <ul className="mt-5 space-y-3">
        {passages.map((p, i) => (
          <motion.li
            key={p.tag}
            initial={{ opacity: 0, x: -8 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.35, delay: 0.1 + i * 0.07, ease }}
            className="rounded-[6px] border bg-surface-sunk p-3"
          >
            <span className="font-mono text-[0.7rem] text-muted-foreground">
              {p.tag}
            </span>
            {p.cited ? (
              <p className="mt-1 line-clamp-2 font-serif text-[0.8rem] leading-snug">
                …{PANG.highlight}…
              </p>
            ) : (
              <span
                className={cn("mt-2 block h-2 rounded-full bg-border", p.width)}
              />
            )}
          </motion.li>
        ))}
      </ul>
    </div>
  );
}

function SubQuestionsFrame() {
  return (
    <div>
      <p className="font-serif text-base leading-snug">{DEMO_QUESTION}</p>
      <ul className="mt-5 space-y-3 border-l pl-4">
        {[
          "What porosity did hollow-channel scaffolds have after sintering?",
          "What porosity did solid scaffolds have after sintering?",
        ].map((q, i) => (
          <motion.li
            key={q}
            initial={{ opacity: 0, y: 8 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.35, delay: 0.2 + i * 0.08, ease }}
          >
            <span className="font-mono text-[0.7rem] text-muted-foreground">
              sub-question {i + 1}
            </span>
            <p className="mt-0.5">{q}</p>
          </motion.li>
        ))}
      </ul>
      <p className="eyebrow mt-5">Illustration</p>
    </div>
  );
}

const CANDIDATES = [
  { id: "a", tag: "p.6 · Methods", fused: 0.62, reranked: 0.31 },
  { id: "b", tag: "p.10 · Results", fused: 0.55, reranked: 0.94 },
  { id: "c", tag: "p.18 · Discussion", fused: 0.51, reranked: 0.58 },
  { id: "d", tag: "p.11 · Results", fused: 0.44, reranked: 0.72 },
];

function RankingFrame() {
  const reduced = useReducedAfterMount();
  const [reranked, setReranked] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -20% 0px" });

  useEffect(() => {
    if (!inView) return;
    const id = setTimeout(() => setReranked(true), reduced ? 0 : 900);
    return () => clearTimeout(id);
  }, [inView, reduced]);

  const order = [...CANDIDATES].sort((x, y) =>
    reranked ? y.reranked - x.reranked : y.fused - x.fused,
  );
  return (
    <div ref={ref}>
      <p className="font-mono text-xs text-muted-foreground">
        {reranked ? "after reranking" : "after keyword + meaning search"}
      </p>
      <ul className="mt-5 space-y-3">
        {order.map((c) => {
          const score = reranked ? c.reranked : c.fused;
          return (
            <motion.li
              key={c.id}
              layout
              transition={{ duration: 0.5, ease: [0.77, 0, 0.175, 1] }}
              className="grid grid-cols-[8.5rem_1fr_2.5rem] items-center gap-3"
            >
              <span className="font-mono text-[0.7rem] text-muted-foreground">
                {c.tag}
              </span>
              <span className="h-2 overflow-hidden rounded-full bg-surface-sunk">
                <motion.span
                  className={cn(
                    "block h-full origin-left rounded-full",
                    c.id === "b" ? "bg-highlight" : "bg-muted-foreground/40",
                  )}
                  initial={false}
                  animate={{ scaleX: score }}
                  transition={{ duration: 0.5, ease }}
                />
              </span>
              <span className="text-right font-mono text-[0.7rem] tabular-nums">
                {score.toFixed(2)}
              </span>
            </motion.li>
          );
        })}
      </ul>
      <p className="eyebrow mt-5">Illustration · scores not from a real run</p>
    </div>
  );
}

function VerifyFrame() {
  const claims = [
    {
      text: "Hollow-channel scaffolds reached about 84% porosity.",
      status: "supported",
    },
    {
      text: "Solid scaffolds reached about 73% porosity.",
      status: "supported",
    },
    {
      text: "Solid scaffolds had the higher porosity of the two.",
      status: "removed",
    },
  ];
  return (
    <ul className="space-y-4 font-serif text-[0.95rem] leading-snug">
      {claims.map((c, i) => (
        <motion.li
          key={c.text}
          initial={{ opacity: 0, y: 8 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.35, delay: i * 0.1, ease }}
          className="grid grid-cols-[1fr_auto] gap-3"
        >
          <span
            className={cn(
              c.status === "removed" &&
                "text-muted-foreground line-through decoration-status-unsupported",
            )}
          >
            {c.text}
          </span>
          {c.status === "supported" ? (
            <span className="inline-flex items-center gap-1 font-sans text-[0.7rem] text-status-supported">
              <CircleCheck className="size-3.5" aria-hidden />
              Supported
            </span>
          ) : (
            <span className="inline-flex flex-col items-end font-sans text-[0.7rem] text-status-unsupported">
              <span className="inline-flex items-center gap-1">
                <CircleX className="size-3.5" aria-hidden />
                Unsupported — removed
              </span>
              <span className="eyebrow text-[0.6rem]">Illustration</span>
            </span>
          )}
        </motion.li>
      ))}
      <li className="pt-1 font-mono text-[0.7rem] text-muted-foreground">
        cited: {PANG.cite}
      </li>
    </ul>
  );
}

function ApprovalFrame() {
  return (
    <div>
      <p className="flex items-center gap-2 font-medium">
        <CircleDot className="size-4 text-status-partial" aria-hidden />
        Your papers don&apos;t cover one part of this question
      </p>
      <p className="mt-2 leading-relaxed text-muted-foreground">
        Daily copper release isn&apos;t reported in this workspace. How should
        the answer continue?
      </p>
      <ul className="mt-5 space-y-2">
        <li className="rounded-[6px] border border-foreground px-3 py-2.5 font-medium">
          Stay corpus-only
        </li>
        <li className="rounded-[6px] border px-3 py-2.5">
          Use general knowledge
          <span className="ml-2 text-xs text-status-general">
            labelled as such
          </span>
        </li>
        <li className="flex items-center justify-between rounded-[6px] border border-dashed px-3 py-2.5 text-muted-foreground">
          Search external sources
          <span className="font-mono text-[0.7rem]">Phase 5</span>
        </li>
      </ul>
    </div>
  );
}
