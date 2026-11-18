---
target: landing page
total_score: 22
max_score: 32
na_heuristics: 7,10
p0_count: 1
p1_count: 2
target_identity: "file:frontend/src/app/page.tsx"
target_fingerprint: "sha256:b768781543e5403eb23d9219fb83237f1e0db8185423a62c47d4c62f029d9883"
target_path: frontend/src/app/page.tsx
timestamp: 2026-10-08T09-29-37Z
slug: frontend-src-app-page-tsx
---
Method: dual-agent (A: design review · B: detector + headless browser)

## Design Health Score (22/32, 69%, Acceptable; 7 and 10 n/a on a Persuade page)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of system status | 3 | Demo stages and progress line clear; hero card opens near-empty |
| 2 | Match system / real world | 4 | Footnotes, page refs, highlighter: how researchers read |
| 3 | User control and freedom | 2 | Both CTAs go to /login, which 404s |
| 4 | Consistency and standards | 3 | Approval options duplicated with different styling |
| 5 | Error prevention | 2 | "Open your workspace" implies self-serve on an invite-only product |
| 6 | Recognition over recall | 3 | Hero's removed claim only makes sense after step 4 |
| 7 | Flexibility and efficiency | n/a | One-pass persuasion page |
| 8 | Aesthetic and minimalist | 3 | Restrained; identical eyebrow+H2+reveal rhythm on every section |
| 9 | Error recovery | 2 | 404 dead end after the primary CTA |
| 10 | Help and documentation | n/a | Marketing surface |

## Specificity verdict
Authored, not interchangeable: real benchmark question, real pipeline stages, verbatim Pang 2023 p.10 passage highlighted, citation chips with real previews. Skeleton is stock (hero, how-it-works, comparison, stat row, footer); the stat row is the generic part.
Detector: static scan clean. In-page scan 13-15 findings per view; eyebrow/kicker, all-caps, mono tiny-text on page refs, cream palette, italic display are brief-sanctioned false positives. Thin-border-wide-shadow/dark-glow on paper stack and tooltips: shadows are DESIGN.md's warm paper shadows, low value in dark. Dark low-contrast on "prove it." is a false positive (detector can't see the SVG stroke) except during the first ~1.1 s draw. Hero passage 1.4:1 hit is measured with background-size 0%: false positive, though the sweep briefly shows dark text on dark before the yellow arrives.

## Priority issues
- [P0] Primary CTAs dead-end: "Open your workspace" and "Sign in" go to /login, which 404s. Fix: until auth ships, a /login stub that says invite-only and how to ask, or point CTAs at GitHub. /impeccable harden
- [P1] Brand commitment missing: nothing says final-year B.Tech project, invite-only, or provisional at the top (PRODUCT.md requires it); CTA reads like a launch. Fix: one status line under the hero CTAs; CTA "Sign in (invite-only)". /impeccable clarify
- [P1] Results don't show the thesis: "Measured on the deployed app" + 12/12 overclaims on 12 items; "LLM calls per question" and "first response event" mean nothing to researchers; no unsupported-claim rate vs plain RAG. Fix: "Early results (12 test items)", lead with answer/abstain outcomes, add a "vs plain RAG: pending benchmark" slot. /impeccable clarify
- [P2] Approval mocks pre-select "Stay corpus-only" via a heavier border (comparison.tsx, how-it-works.tsx), contradicting principle 4. Fix: equal weight for all options. /impeccable polish
- [P2] Story order: the comparison is the hook but comes after ~350vh of desktop mechanism tour; the approval card appears twice; page ends on "3.7 LLM calls" with no closing ask. Fix: comparison right after hero, How it works to 4 steps, closing block (status, repo, team). /impeccable layout

## Persona red flags
- Jordan: CTA → 404; struck claim reads as the product failing.
- Riley: "Open your workspace" implies self-serve; footer credits 1 of 4 team members (TEAM in content.ts vs PRODUCT.md).
- Casey (375): no nav below md; answer card hides most of the cited page so the highlight payoff is barely visible; stroke crowds "to".
- Academic reviewer: no student-project status, no link to SRS/benchmark/method write-up.

## Minor
Hero loop starts on an empty card; stack line in footer is developer noise; "Why it abstains" eyebrow over "two assistants".

## Questions
Why make visitors scroll the mechanism before the comparison? What does the page say to someone without an invite? Would one provisional unsupported-claim number vs plain RAG persuade reviewers more than 12/12?
