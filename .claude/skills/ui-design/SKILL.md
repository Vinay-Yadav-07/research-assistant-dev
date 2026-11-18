---
name: ui-design
description: Visual design rules for the research-assistant frontend (precise research-workspace direction, tokens, type, layout, motion, copy, banned patterns). Load before building or restyling any page or component in frontend/.
---

# UI design

The rules live in **`docs/DESIGN.md`** (D-088). Read it fully before any UI work; it decides
direction, tokens, typography, layout, motion and accessibility for this project. CLAUDE.md and
the SRS still win on scope, process and approvals. The `trust-ui` skill still governs claim
status, citations, mode badge, approval card and source highlight, and is never overridden.

Quick reminders:

- **Current vs target.** DESIGN.md §0 says what the running app uses today and what the target is.
  Build new or restyled screens to the target; don't half-restyle screens outside the PR's scope,
  and never document a target element as shipped.
- Tokens only, never raw hex in components. Tokens live in `frontend/src/app/globals.css`, mapped
  onto the shadcn tokens; `mark` is the evidence highlight, `status-*` the claim statuses. Until
  the foundation PR lands, `globals.css` still holds the old "Paper & ink" palette.
- Fonts (target): Geist Sans for the interface, Geist Mono for refs, counts and stages, Newsreader
  only for text quoted from papers. Indigo for interaction, yellow for evidence, never swapped.
- Motion: `motion/react`. The root layout wraps the app in `<MotionConfig reducedMotion="user">`;
  looping demos use `useReducedAfterMount` (`src/components/landing/use-reduced.ts`) to show their final frame.
- Theme: `.dark` on `<html>`, set before paint by the script in `layout.tsx`; saved choice is
  `localStorage.theme` (`"light"` | `"dark"`, absent = system).
- Experimental features (the knowledge graph, D-087) carry an "Experimental" label; planned
  features are absent or disabled with their phase.
- Claim status, citations, mode badge and approval card: also load the `trust-ui` skill.
