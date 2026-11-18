import { BookOpen, Globe, Lightbulb } from "lucide-react";

import type { Schemas } from "@/lib/api/client";

export type Mode = Schemas["MessageRead"]["mode"];

export const MODES: Record<Mode, { label: string; Icon: typeof BookOpen }> = {
  corpus_only: { label: "Corpus only", Icon: BookOpen },
  corpus_web: { label: "Corpus + Web", Icon: Globe },
  general_knowledge: { label: "General knowledge", Icon: Lightbulb },
};

/** The knowledge mode an answer or conversation runs in (trust-ui: always visible). */
export function ModeBadge({ mode }: { mode: Mode }) {
  const { label, Icon } = MODES[mode];
  return (
    <span
      className="inline-flex h-6 shrink-0 items-center gap-1.5 rounded-[6px] border px-2 text-xs font-medium whitespace-nowrap data-[mode=general_knowledge]:border-status-general/40 data-[mode=general_knowledge]:text-status-general"
      data-mode={mode}
    >
      <Icon aria-hidden className="size-3.5" />
      <span className="sr-only">Mode: </span>
      {label}
    </span>
  );
}
