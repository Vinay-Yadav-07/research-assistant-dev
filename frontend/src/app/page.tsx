import Link from "next/link";

import { HealthStatus } from "@/components/health-status";
import { Comparison } from "@/components/landing/comparison";
import { GITHUB_URL, TEAM } from "@/components/landing/content";
import { HeadlineStroke } from "@/components/landing/headline-stroke";
import { HeroDemo } from "@/components/landing/hero-demo";
import { HowItWorks } from "@/components/landing/how-it-works";
import { Navbar } from "@/components/landing/navbar";
import { Results } from "@/components/landing/results";
import { Reveal } from "@/components/landing/reveal";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STACK = [
  "Next.js",
  "FastAPI",
  "LangGraph",
  "Postgres + pgvector",
  "Supabase",
];

export default function Home() {
  return (
    <div className="paper-grain flex flex-1 flex-col">
      <Navbar />

      <main className="flex-1">
        <section className="relative mx-auto max-w-6xl px-4 sm:px-6">
          {/* Margin rule framing the hero, like a ruled page. */}
          <div
            aria-hidden
            className="absolute inset-y-0 left-4 hidden w-px bg-border sm:left-6 lg:block"
          />
          <div className="grid gap-14 pt-12 pb-24 sm:pt-20 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:gap-16 lg:pt-24 lg:pb-32 lg:pl-10">
            <div>
              <p className="eyebrow">Evidence-grounded research assistant</p>
              <h1 className="mt-5 text-[clamp(2.5rem,6vw,4.25rem)] leading-[1.05] font-medium tracking-[-0.02em]">
                Answers from your papers, with the page to{" "}
                <span className="relative z-0 inline-block whitespace-nowrap">
                  <em className="text-mark-foreground">prove it.</em>
                  <HeadlineStroke />
                </span>
              </h1>
              <p className="mt-6 max-w-[34rem] text-[1.0625rem] leading-relaxed text-muted-foreground">
                Ask questions of the research papers you upload. Every claim
                cites a page, each citation is checked against its passage, and
                when your papers don&apos;t cover a question it says so.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
                <Link
                  href="/login"
                  className={cn(buttonVariants(), "h-10 px-5")}
                >
                  Open your workspace
                </Link>
                <a href="#how" className="link-draw tap-target text-sm">
                  See how it works
                </a>
              </div>
            </div>
            <HeroDemo />
          </div>
        </section>

        <section
          id="how"
          aria-labelledby="how-title"
          className="mx-auto max-w-6xl scroll-mt-16 border-t px-4 py-24 sm:px-6 lg:py-32"
        >
          <Reveal>
            <p className="eyebrow">How it works</p>
            <h2
              id="how-title"
              className="mt-3 max-w-2xl text-[clamp(2rem,4vw,2.75rem)] leading-[1.1] font-medium"
            >
              From PDF to a claim you can check
            </h2>
          </Reveal>
          <div className="mt-12 lg:mt-4">
            <HowItWorks />
          </div>
        </section>

        <section
          id="compare"
          aria-labelledby="compare-title"
          className="mx-auto max-w-6xl scroll-mt-16 border-t px-4 py-24 sm:px-6 lg:py-32"
        >
          <Reveal>
            <p className="eyebrow">Why it abstains</p>
            <h2
              id="compare-title"
              className="mt-3 max-w-2xl text-[clamp(2rem,4vw,2.75rem)] leading-[1.1] font-medium"
            >
              The same question, two assistants
            </h2>
          </Reveal>
          <div className="mt-10">
            <Comparison />
          </div>
        </section>

        <section
          id="results"
          aria-labelledby="results-title"
          className="mx-auto max-w-6xl scroll-mt-16 border-t px-4 py-24 sm:px-6 lg:py-32"
        >
          <Reveal>
            <p className="eyebrow">Results so far</p>
            <h2
              id="results-title"
              className="mt-3 max-w-2xl text-[clamp(2rem,4vw,2.75rem)] leading-[1.1] font-medium"
            >
              Measured on the deployed app
            </h2>
          </Reveal>
          <div className="mt-12">
            <Results />
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 text-sm text-muted-foreground sm:grid-cols-2 sm:px-6">
          <div className="space-y-2">
            <p className="font-serif text-base text-foreground">
              Research Assistant
            </p>
            <p>Built by {TEAM.join(", ")}.</p>
            <a
              href={GITHUB_URL}
              className="link-draw inline-flex min-h-10 items-center"
            >
              Source on GitHub
            </a>
          </div>
          <div className="space-y-3 sm:text-right">
            <p className="font-mono text-xs">{STACK.join(" · ")}</p>
            <HealthStatus />
          </div>
        </div>
      </footer>
    </div>
  );
}
