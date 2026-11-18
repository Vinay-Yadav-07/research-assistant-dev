"use client";

import "react-pdf/dist/Page/TextLayer.css";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

import {
  findQuote,
  type Highlights,
  markItem,
} from "@/components/chat/pdf-highlight";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, type Schemas, unwrap } from "@/lib/api/client";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

type Citation = Schemas["CitationRead"];

/**
 * Side panel with the cited PDF page and the quote highlighted (FR-13). Loaded client-side only,
 * since pdf.js needs the browser.
 */
export default function SourceViewer({
  citation,
  label,
  onClose,
}: {
  citation: Citation | null;
  label: string;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={citation !== null}
      onOpenChange={(open) => !open && onClose()}
    >
      <DialogContent className="top-0 right-0 left-auto flex h-dvh w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none p-0 duration-[320ms] data-open:zoom-in-100 data-open:slide-in-from-right-8 data-closed:zoom-out-100 sm:max-w-2xl">
        {citation?.document_id && (
          <Viewer
            key={citation.id}
            citation={citation}
            documentId={citation.document_id}
            label={label}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function Viewer({
  citation,
  documentId,
  label,
}: {
  citation: Citation;
  documentId: string;
  label: string;
}) {
  const cited = citation.page_start ?? 1;
  const citedEnd = citation.page_end ?? cited;
  const [page, setPage] = useState(cited);
  const [pages, setPages] = useState<number>();
  const [found, setFound] = useState<{ page: number; marks: Highlights }>();
  const [width, setWidth] = useState<number>();
  const frame = useRef<HTMLDivElement>(null);

  // The signed URL lives 5 minutes; fetch a fresh one on every open and never refetch mid-read.
  const file = useQuery({
    queryKey: ["document-file", documentId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/documents/{document_id}/file", {
          params: { path: { document_id: documentId } },
        }),
      ),
    staleTime: Infinity,
    gcTime: 0,
  });

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth - 32));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const marks = found?.page === page ? found.marks : undefined;
  const renderText = useCallback(
    ({ str, itemIndex }: { str: string; itemIndex: number }) =>
      markItem(str, marks?.get(itemIndex)),
    [marks],
  );

  const scrollToMark = () => {
    const mark = frame.current?.querySelector(".textLayer mark");
    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    mark?.scrollIntoView({
      block: "center",
      behavior: reduce ? "auto" : "smooth",
    });
  };

  const inCitedRange = page >= cited && page <= citedEnd;
  const missed =
    citation.quote && inCitedRange && marks !== undefined && marks.size === 0;

  return (
    <>
      <header className="border-b px-4 py-3 pr-12">
        <DialogTitle className="font-serif text-lg leading-snug">
          {citation.document_title ?? "Untitled paper"}
        </DialogTitle>
        <DialogDescription className="mt-0.5 font-mono text-xs">
          {label}
          {citation.section && ` · ${citation.section}`}
        </DialogDescription>
      </header>

      <div ref={frame} className="min-h-0 flex-1 overflow-y-auto bg-muted p-4">
        {missed && (
          <blockquote className="mb-3 border-l-2 border-foreground/30 bg-background px-3 py-2 font-serif text-sm">
            <mark className="rounded-[2px] bg-mark px-0.5 text-mark-foreground">
              {citation.quote}
            </mark>
            <span className="mt-1 block font-sans text-xs text-muted-foreground">
              The passage could not be located on this page; the stored quote is
              shown instead.
            </span>
          </blockquote>
        )}
        {file.isError ? (
          <Message>Could not open the paper: {file.error.message}</Message>
        ) : file.data ? (
          <Document
            file={file.data.url}
            onLoadSuccess={(pdf) => {
              setPages(pdf.numPages);
              setPage((p) => Math.min(p, pdf.numPages));
            }}
            loading={<Message>Loading the paper…</Message>}
            error={<Message>Could not load the PDF.</Message>}
          >
            {width !== undefined && (
              <Page
                pageNumber={page}
                width={width}
                renderAnnotationLayer={false}
                customTextRenderer={renderText}
                onGetTextSuccess={({ items }) =>
                  setFound({
                    page,
                    marks:
                      inCitedRange && citation.quote
                        ? findQuote(
                            // Marked-content items have no text but keep their index.
                            items.map((i) => ("str" in i ? i : {})),
                            citation.quote,
                          )
                        : new Map(),
                  })
                }
                onRenderTextLayerSuccess={scrollToMark}
                loading={<Message>Loading page {page}…</Message>}
                className="mx-auto w-fit shadow-[0_8px_24px_-12px_var(--shadow-warm)]"
              />
            )}
          </Document>
        ) : (
          <Message>Opening the paper…</Message>
        )}
      </div>

      <footer className="flex items-center justify-between border-t px-4 py-2">
        <Button
          variant="outline"
          size="icon"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          <ChevronLeft />
        </Button>
        <span className="font-mono text-xs text-muted-foreground tabular-nums">
          p. {page}
          {pages !== undefined && ` of ${pages}`}
        </span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Next page"
          disabled={pages === undefined || page >= pages}
          onClick={() => setPage((p) => p + 1)}
        >
          <ChevronRight />
        </Button>
      </footer>
    </>
  );
}

function Message({ children }: { children: React.ReactNode }) {
  return (
    <p className="py-12 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}
