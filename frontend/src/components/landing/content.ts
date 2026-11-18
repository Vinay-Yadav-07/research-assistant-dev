/**
 * Landing-page content. Passages and questions are real benchmark data (DESIGN.md §1);
 * anything not from a paper is marked `illustration`.
 */

export const PANG = {
  cite: "Pang 2023 · p.10",
  title:
    "Additive manufacturing and performance of bioceramic scaffolds with different hollow strut geometries",
  arxiv: "arXiv 2303.11051",
  // Page 10, verbatim; `highlight` is the span the claims cite.
  before:
    "Scaffolds with various hollow strut geometries can be directly extruded by robocasting using the designed nozzles. After sintering, the scaffold with hollow channels had a ",
  highlight:
    "significantly higher porosity of approximately 84% compared to the solid scaffold (73%)",
  after:
    ", corresponding to apparent densities of 1.145 ± 0.052 g/cm3 and 1.369 ± 0.045 g/cm3, respectively.",
};

/** Benchmark item cal-024 (answerable from Pang 2023, p.10). */
export const DEMO_QUESTION =
  "How porous were scaffolds with hollow channels compared with solid scaffolds after sintering?";

/** The QA graph's real progress stages (`backend/app/graphs/qa.py`). */
export const STAGES = [
  "analyzing",
  "retrieving",
  "assessing",
  "writing",
  "verifying",
  "citing",
] as const;

export type DemoClaim = {
  text: string;
  removed?: boolean;
  illustration?: boolean;
};

export const DEMO_CLAIMS: DemoClaim[] = [
  {
    text: "After sintering, scaffolds with hollow channels reached a porosity of about 84%, against 73% for solid scaffolds.",
  },
  {
    text: "Their apparent density was lower as a result: 1.145 g/cm³ against 1.369 g/cm³.",
  },
  {
    text: "Solid scaffolds had the higher porosity of the two designs.",
    removed: true,
    illustration: true,
  },
];

/** Benchmark item test-051: unanswerable from the scaffolds corpus. */
export const UNANSWERABLE = {
  question:
    "How much copper did the copper-doped diopside scaffolds release per day in culture medium?",
  chatbot:
    "The copper-doped diopside scaffolds released about 2.4 µg of copper per day, a steady level that is safe for cells and supports blood-vessel growth.",
  covered: [
    {
      text: "Copper is evenly distributed across the hollow scaffold's cross-section (EDS mapping).",
      cite: "Pang 2023 · p.10",
    },
    {
      text: "Extracts of the copper-doped scaffolds were tested on HUVECs and Saos-2 cells.",
      cite: "Pang 2023 · p.14",
    },
  ],
};

/** Phase 2 measurements on the deployed Space (docs/PROGRESS.md, 2026-10-07). */
export const RESULTS = [
  {
    value: 12,
    decimals: 0,
    suffix: "/12",
    label: "correct outcomes (answer or abstain)",
  },
  {
    value: 0.4,
    decimals: 1,
    suffix: " s",
    label: "to the first response event",
  },
  {
    value: 6.8,
    decimals: 1,
    suffix: " s",
    label: "median time to a full answer",
  },
  { value: 3.7, decimals: 1, suffix: "", label: "LLM calls per question" },
];

export const GITHUB_URL =
  process.env.NEXT_PUBLIC_GITHUB_URL ||
  "https://github.com/Vinay-Yadav-07/research-assistant-dev";
export const TEAM = [
  "Vinay Yadav",
  "Tejas Sonawane",
  "Punit Jadhav",
  "Shreyas Desai",
];
