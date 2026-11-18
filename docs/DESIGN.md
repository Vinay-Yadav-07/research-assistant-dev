# Design

The visual, layout and motion rules for the frontend (D-088). Read this before any UI work. Design skills (Impeccable, Emil Kowalski's motion skills) guide general taste; this file decides for this project. CLAUDE.md and the SRS win on scope, process, accessibility, and approvals. The evidence UI (claim status, citations, mode badge, approval card, source highlight) also follows the `trust-ui` skill, which this file never overrides.

## 0. Status: current and target

This file describes the **target** design. The redesign is being implemented in steps (Section 13), so the running app does not match it yet. Never describe a target element as existing in docs, PRs or copy until it ships.

| Area                  | Current implementation (2026-10-20)                                                 | Target                                                                             |
| --------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Direction             | "Paper & ink": warm paper, ink, serif headings (D-073, D-074)                       | Precise research workspace (Section 1)                                             |
| Fonts                 | IBM Plex Sans, IBM Plex Mono, Newsreader for all headings and answer text           | Geist Sans, Geist Mono, Newsreader for quoted source text only                     |
| Colour                | Warm neutrals; primary = ink; focus = ink outline with yellow halo                  | Cool neutrals; indigo for interaction; yellow for evidence only                    |
| Shell                 | Top bar with two links (Workspaces, Discover); every page in one `max-w-4xl` column | Collapsible sidebar with workspace navigation, top bar, per-page widths            |
| Workspace navigation  | Five buttons on the library page; other pages link back with "← Library"            | Persistent workspace section in the sidebar                                        |
| Source viewer         | Full-height modal sheet                                                             | Side panel beside the answer on wide screens; sheet below                          |
| Loading, empty, error | Text lines ("Loading papers…", red error text)                                      | Skeletons, empty states with one action, errors with Retry                         |
| Primitives            | button, badge, card, dialog, input                                                  | Plus tabs, tooltip, menu, sheet, skeleton (on `@base-ui/react`, already installed) |
| Theme control         | Light/dark toggle                                                                   | System / Light / Dark menu                                                         |

Tokens: `frontend/src/app/globals.css` still holds the current palette until the foundation PR replaces it. Until then, use the existing token names; never raw hex.

## 1. Direction: a precise research workspace

The product's promise is "every claim has a page to prove it". The interface should feel like a precise professional instrument for reading and checking research: calm neutral surfaces, exact typography, dense but scannable layouts, and evidence that is always one click away. It is neither a journal page nor a chatbot.

Influences, not templates: Linear (precision, navigation, interaction quality), Notion (workspace organisation), Perplexity (evidence-first answers and source exploration). Nothing is copied from them.

Three signatures:

1. **Two voices.** Text the system writes is set in Geist Sans. Text quoted from a paper is set in Newsreader on a sunk surface with a page reference. Readers can always tell the model from the source.
2. **Indigo acts, yellow proves.** Indigo marks what you can do or have selected: the primary action, the active nav item, focus, links. Yellow marks evidence: highlighted passages and the quote a citation points to. The two never swap roles.
3. **Provenance as instrument readouts.** Mode badge, claim counts ("4 of 5 supported"), citation chips and pipeline stages are set as compact mono readouts, precise and always visible, never decorative.

**Honest content.** Examples use real passages from the benchmark or test papers, never invented citations. Numbers come from `docs/PROGRESS.md` and are labelled provisional until the benchmark is verified. Experimental features carry an "Experimental" label; planned features are absent or shown disabled with their phase.

## 2. Two surfaces

|         | Landing page (persuade)                               | App (operate)                               |
| ------- | ----------------------------------------------------- | ------------------------------------------- |
| Goal    | Tell the story once                                   | Get research done many times a session      |
| Motion  | Expressive but purposeful: hero demo, enter-on-scroll | Functional only: explains a change of state |
| Density | Generous space, display type                          | Compact, scannable                          |
| Serif   | Quoted passages in the demo                           | Quoted passages only                        |

## 3. Typography

| Role         | Font                                           | Use                                                                                                                |
| ------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Sans         | Geist Sans (`next/font/google`, variable)      | All interface text: headings, answers, labels, buttons, navigation                                                 |
| Mono         | Geist Mono                                     | Page and section refs (`p.6 · Methods`), DOIs, counts, pipeline stages, mode badge, keyboard hints                 |
| Source serif | Newsreader (`next/font/google`, optical sizes) | Verbatim passages quoted from papers: source viewer excerpts, evidence panels, comparison quotes, the landing demo |

Scale (size / line-height, px):

| Token        | Size                                              | Use                                                  |
| ------------ | ------------------------------------------------- | ---------------------------------------------------- |
| `text-meta`  | 12 / 16                                           | Timestamps, secondary metadata                       |
| `text-dense` | 13 / 20                                           | Tables, sidebar, chips                               |
| `text-ui`    | 14 / 22                                           | Default UI text                                      |
| `text-body`  | 15 / 24                                           | Answer text and long descriptions (measure 60–72 ch) |
| `text-quote` | 16 / 26                                           | Newsreader passages                                  |
| `h3`         | 18 / 26, weight 600                               | Section titles                                       |
| `h2`         | 22 / 28, weight 600                               | Panel titles                                         |
| `h1`         | 28 / 34, weight 600, tracking −0.015em            | Page titles                                          |
| display      | `clamp(40px, 6vw, 64px)` / 1.05, tracking −0.02em | Landing only                                         |

- Numbers in tables, counts and results use tabular figures.
- No all-caps eyebrow labels in the app; section labels are sentence case in `fg-muted`.

## 4. Colour tokens (target)

Defined as CSS variables on `:root` and `.dark`, mapped onto the shadcn tokens in `globals.css`. Components use tokens only, never raw hex. The trust token names `mark` and `status-*` are kept so evidence components don't change meaning.

| Token                  | Light            | Dark                          | Use                                                     |
| ---------------------- | ---------------- | ----------------------------- | ------------------------------------------------------- |
| `--bg`                 | `#F8F9FB`        | `#0C0D10`                     | App canvas                                              |
| `--surface`            | `#FFFFFF`        | `#14161A`                     | Cards, panels, sidebar                                  |
| `--surface-sunk`       | `#F1F3F6`        | `#1B1E24`                     | Inputs, quoted passages, hover rows                     |
| `--fg`                 | `#0E1116`        | `#ECEEF2`                     | Primary text                                            |
| `--fg-muted`           | `#4B5261`        | `#A3A9B5`                     | Secondary text                                          |
| `--fg-subtle`          | `#636A79`        | `#868D99`                     | Metadata                                                |
| `--border`             | `#E3E6EB`        | `#262A31`                     | Decorative dividers and card edges                      |
| `--border-control`     | `#8A909C`        | `#6B7280`                     | Input and control outlines                              |
| `--accent`             | `#4F46E5`        | `#5E5CE6`                     | Primary button fill (white text)                        |
| `--accent-fg`          | `#4338CA`        | `#A5A8FF`                     | Links, active nav, focus ring, selected text            |
| `--accent-subtle`      | `--accent` at 8% | `--accent` at 14%             | Selected row and nav backgrounds                        |
| `--mark`               | `#FDE68A`        | `#4A3F12` (text stays `--fg`) | Evidence highlight                                      |
| `--status-supported`   | `#15803D`        | `#6CCB8F`                     | Claim status                                            |
| `--status-partial`     | `#B45309`        | `#E5B45A`                     | Claim status                                            |
| `--status-unsupported` | `#B91C1C`        | `#F08A84`                     | Claim status, destructive actions                       |
| `--status-uncertain`   | `#5C6675`        | `#9AA4B2`                     | Claim status (neutral, so it never reads as the accent) |
| `--status-general`     | `#A21CAF`        | `#E879F9`                     | General-knowledge label                                 |

Contrast, computed with the WCAG formula (re-check on rendered pages when implemented):

- Text tokens on `--surface`: `fg` 18.9 / 15.6, `fg-muted` 7.8 / 7.7, `fg-subtle` ≥ 4.88 on every surface (light) and 5.4 (dark), `accent-fg` 7.9 / 8.3, statuses 5.0–6.5 (light) and 7.2–9.5 (dark).
- White on `--accent`: 6.29 (light), 5.06 (dark).
- `--border-control`: 3.21 (light) and 3.75 (dark) against `--surface`, meeting WCAG 1.4.11. `--border` is decorative and is never the only boundary of a control.
- Text on `--mark`: 15.2 (light), 9.0 (dark).

Rules:

- Indigo covers about 5% of a screen: one primary action per view, the active nav item, focus, links. Hierarchy comes from neutrals, weight and spacing.
- Status is never colour alone: always icon + word (`trust-ui`).
- `--mark` only for evidence. Not for buttons, brand or decoration.
- No gradients, glows or glass.

## 5. Space, shape, elevation

- Spacing on a 4 px scale. Panel padding 16 / 20 / 24 px. Page gutters 16 px (mobile), 24 px (tablet), 32 px (desktop).
- Radius: 4 px chips, 6 px controls, 8 px cards and popovers, 12 px dialogs and sheets. No pill-shaped cards.
- Borders first. Elevation:
  - e0: border only (cards, panels).
  - e1 (popovers, menus, tooltips): light `0 1px 2px rgb(15 17 22 / .06), 0 4px 12px rgb(15 17 22 / .06)`; dark `0 0 0 1px var(--border), 0 8px 24px rgb(0 0 0 / .5)`.
  - e2 (dialogs, sheets): e1 with doubled offsets and blur.
- In dark mode, raised layers use a lighter surface; shadows only separate floating layers.

## 6. App shell and layout (target)

```
┌──────────────┬──────────────────────────────────────────────────────┐
│ Research     │ Breadcrumbs › page             [mode badge] actions │ top bar 48 px
│ Assistant    ├──────────────────────────────────────────────────────┤
│ Workspace ▾  │                                                      │
│──────────────│                    page content                      │
│ Library      │                                                      │
│ Ask          │                                                      │
│   recent …   │                                                      │
│ Analysis     │                                                      │
│ Findings     │                                                      │
│ Graph  Exp.  │                                                      │
│──────────────│                                                      │
│ Discover     │                                                      │
│ Workspaces   │                                                      │
│ Theme ▾      │                                                      │
│ Account ▾    │                                                      │
└──────────────┴──────────────────────────────────────────────────────┘
```

- **Sidebar:** 240 px open, 56 px icon rail collapsed; the choice is remembered per browser. The workspace section appears only inside `/workspaces/[id]/*` and comes from existing endpoints (workspace list, conversations); no API changes. The Knowledge graph item carries an "Experimental" label.
- **Top bar:** breadcrumbs, page actions, and on chat pages the mode badge.
- **Routes stay the same.** The shell changes navigation, not URLs.
- **Page widths:** reading pages (chat thread, findings) 720 px measure; list pages (library, workspaces, discover) up to 1120 px; canvas pages (graph, analysis tables) full width.
- **Chat with evidence:** at ≥ 1280 px a citation opens the source viewer as a 480 px panel beside the thread, so claim and passage are visible together; below that it opens as a sheet. Its behaviour (page, highlight, quote matching) is unchanged.

Breakpoints:

| Width    | Shell                                    | Chat source viewer   | Wide content                            |
| -------- | ---------------------------------------- | -------------------- | --------------------------------------- |
| ≥ 1280   | Sidebar open                             | Side panel           | Full width                              |
| 768–1279 | Icon rail, expandable                    | Sheet from the right | Tables scroll horizontally              |
| < 768    | Menu button opens the sidebar as a sheet | Full-screen sheet    | Graph shows the relationship list first |

No horizontal page scroll from 375 px.

## 7. Components and states

- **Primitives:** shadcn components on `@base-ui/react` in `src/components/ui/`. Button variants primary (accent), secondary, ghost, destructive; sizes 32 / 36 / 40 px, every target at least 40 px tall through `tap-target`. Tabs, tooltips, menus and sheets use the primitives, not hand-written ARIA.
- **Page header:** title, one-line description, actions on the right; no back links inside a workspace once the sidebar exists.
- **Loading:** a skeleton shaped like the final content; text only for waits too short to notice. Chat shows the backend's stage line exactly as sent.
- **Empty:** one sentence saying what belongs here and one primary action ("Upload papers", "Find papers").
- **Error:** a plain reason (reuse `import-errors.ts` mappings where they apply), a Retry action, and the user's input kept.
- **Success:** confirm in place; no toasts for routine saves.
- **Abstention:** a normal answer in neutral styling, never error red.

## 8. Evidence motifs

Behaviour and wording come from `trust-ui`; this section sets their look.

- **Citation chip:** Geist Mono, `Author Year · p.N`, 4 px radius, `--surface-sunk`, accent border on hover and focus; opens the source viewer at the page with the quote in `--mark`.
- **Superscript markers** (`¹ ² ³`) link claims in the answer to the claims list.
- **Claims list:** number, status (icon + word), claim text, chips; "N of M supported" as a mono readout.
- **Quoted passage:** Newsreader on `--surface-sunk`, a 2 px left rule, the matched span in `--mark`, mono page ref.
- **Pipeline stages:** one mono line; current stage in `--fg`, done stages in `--fg-subtle` with a tick.
- **Mode badge:** mono, always visible in the chat top bar, its own icon per mode.
- **Experimental label:** a small neutral badge "Experimental" next to the feature name; never accent colour.

## 9. Motion

Library: `motion` (`motion/react`). No smooth-scroll or scroll-jacking libraries.

| Token         | Value                             | Use                                 |
| ------------- | --------------------------------- | ----------------------------------- |
| `fast`        | 120 ms                            | Hover, press, small state changes   |
| `base`        | 200 ms                            | Popovers, toggles, sidebar collapse |
| `slow`        | 320 ms                            | Panels, the source viewer, dialogs  |
| `story`       | 600–900 ms                        | Landing page only                   |
| `ease-out`    | `cubic-bezier(0.23, 1, 0.32, 1)`  | Entering and most transitions       |
| `ease-in-out` | `cubic-bezier(0.77, 0, 0.175, 1)` | Elements moving on screen           |

- Ask "should this animate at all?" first. In the app, animate only to explain a change of state: a stage advancing, claims arriving, a claim being removed, the source viewer opening and scrolling to the highlight, document status changing.
- Never animate keyboard-triggered actions or anything done many times in a row (sending a message, switching conversations, toggling the sidebar by shortcut).
- Never ease-in for entering elements. Exits are shorter than entrances.
- Animate `transform` and `opacity` only. Sidebar collapse animates the container; labels fade, text does not reflow mid-animation.
- Enter-on-scroll (landing): fade up 12–16 px, once, staggered 60–80 ms.
- Press feedback: scale to 0.97.
- `prefers-reduced-motion`: show the final state immediately; looping demos become a static final frame.

## 10. Accessibility

- Visible focus on every interactive element: 2 px `--accent-fg` outline, 2 px offset.
- All functionality reachable by keyboard; dialogs and sheets trap focus and restore it; the sidebar is a labelled `nav` with `aria-current`.
- SSE progress and claim arrival announced through an `aria-live="polite"` region.
- Layouts work from 375 px wide; touch targets at least 40 px.
- WCAG 2.1 AA contrast in both themes (Section 4).

## 11. Avoid

- Gradients, glowing orbs, glassmorphism, aurora backgrounds; accent colour on large surfaces.
- Sparkle or magic-wand icons, "AI-powered" badges, "Unlock the power of…" copy.
- Chat-bubble layouts for answers, avatars for the model, fake typing.
- Emoji bento grids, everything-centred layouts, identical three-column feature cards.
- Invented papers, quotes, statistics, progress or verification states.
- Decorative motion in the app.

## 12. Checks before a UI PR

Apply to every screen a PR restyles to the target design. Screens not yet migrated keep the current style; don't half-restyle them.

- Light and dark both reviewed at 375 px, 768 px and desktop width.
- Keyboard-only pass and reduced-motion review.
- No raw hex in components.
- Impeccable audit and Emil's `review-animations` run on changed screens; findings fixed or noted in the PR.
- The Playwright E2E test still passes.

## 13. Implementation order

Each step is its own PR into `dev` with this file's Section 0 updated to match what shipped.

1. Foundation and app shell: tokens, fonts, primitives, sidebar, top bar, mobile sheet, theme menu, Experimental label on the graph.
2. Chat and evidence panel; shared loading, empty and error states.
3. Library, workspaces, Discover.
4. Analysis, saved findings, graph re-skin (no behaviour change, D-087).
5. Landing and authentication pages.
