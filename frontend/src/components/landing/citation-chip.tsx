import type { ReactNode } from "react";

/**
 * Mono citation chip with a passage preview on hover or focus (DESIGN.md §6).
 * CSS only: the preview is in the DOM, so screen readers get it through `aria-describedby`.
 */
export function CitationChip({
  id,
  label,
  preview,
  marker,
  onClick,
}: {
  id: string;
  label: string;
  preview: ReactNode;
  marker?: string;
  onClick?: () => void;
}) {
  return (
    <span className="group relative inline-block">
      <button
        type="button"
        aria-describedby={id}
        onClick={onClick}
        className="tap-target inline-flex min-h-7 items-center gap-1 rounded-[6px] border bg-background px-1.5 font-mono text-xs whitespace-nowrap transition-colors duration-[120ms] hover:border-foreground/40"
      >
        {marker && <sup className="text-muted-foreground">{marker}</sup>}
        {label}
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-0 z-20 mb-2 w-72 max-w-[80vw] translate-y-1 rounded-[10px] border bg-popover p-3 text-left font-serif text-sm leading-relaxed opacity-0 shadow-[0_8px_24px_-12px_var(--shadow-warm)] transition-[opacity,transform,visibility] duration-200 ease-[var(--ease-out)] group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100 group-hover:visible group-hover:translate-y-0 group-hover:opacity-100"
      >
        {preview}
      </span>
    </span>
  );
}
