"use client";

import { motion, useMotionValueEvent, useScroll } from "motion/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants } from "@/components/ui/button";
import { SUPABASE_URL, supabase } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { id: "how", label: "How it works" },
  { id: "compare", label: "Why it abstains" },
  { id: "results", label: "Results" },
];

/**
 * Transparent at the top; compacts with a hairline and a reading-progress line after scrolling.
 * Fixed over a constant-height spacer, so compacting switches instantly without shifting the page.
 */
export function Navbar() {
  const { scrollY, scrollYProgress } = useScroll();
  const [compact, setCompact] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    if (!SUPABASE_URL) return;
    supabase()
      .auth.getSession()
      .then(({ data }) => setSignedIn(Boolean(data.session)));
  }, []);

  useMotionValueEvent(scrollY, "change", (y) => setCompact(y > 24));

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          if (entry.isIntersecting) setActive(entry.target.id);
          else setActive((id) => (id === entry.target.id ? null : id));
      },
      { rootMargin: "-45% 0px -50% 0px" },
    );
    for (const { id } of SECTIONS) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <header
        className={cn(
          "fixed inset-x-0 top-0 z-50 border-b transition-[background-color,border-color] duration-200",
          compact
            ? "border-border bg-background/95"
            : "border-transparent bg-transparent",
        )}
      >
        <nav
          aria-label="Main"
          className={cn(
            "mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 sm:px-6",
            compact ? "h-12" : "h-16",
          )}
        >
          <Link href="/" className="tap-target font-serif text-lg font-medium">
            Research Assistant
          </Link>
          <ul className="hidden items-center gap-6 text-sm md:flex">
            {SECTIONS.map(({ id, label }) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  aria-current={active === id ? "true" : undefined}
                  className="link-draw text-muted-foreground transition-colors duration-[120ms] hover:text-foreground aria-[current]:text-foreground"
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <Link
              href={signedIn ? "/workspaces" : "/login"}
              className={cn(
                buttonVariants({ variant: "outline" }),
                "h-10 px-4",
              )}
            >
              {signedIn ? "Your workspaces" : "Sign in"}
            </Link>
          </div>
        </nav>
        <motion.div
          aria-hidden
          className="absolute bottom-[-1px] left-0 h-[2px] w-full origin-left bg-highlight"
          style={{ scaleX: scrollYProgress }}
        />
      </header>
      <div aria-hidden className="h-16 shrink-0" />
    </>
  );
}
