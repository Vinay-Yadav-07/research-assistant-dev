"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  ExternalLink,
  FileCheck,
  FileQuestion,
  Link2,
} from "lucide-react";
import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { importFailure } from "@/components/discover/import-errors";
import { slowImportNote } from "@/components/discover/import-progress";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useWorkspaces } from "@/components/workspaces/workspace-list";
import { api, ApiError, type Schemas, unwrap } from "@/lib/api/client";

type Paper = Schemas["PaperRecord"];
type Workspace = Schemas["WorkspaceRead"];
type Scope = "all" | "arxiv" | "openalex";

const SCOPES: { value: Scope; label: string }[] = [
  { value: "all", label: "arXiv and OpenAlex" },
  { value: "arxiv", label: "arXiv" },
  { value: "openalex", label: "OpenAlex" },
];

const SOURCE_LABEL: Record<string, string> = {
  arxiv: "arXiv",
  openalex: "OpenAlex",
};

const SELECT =
  "h-10 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

type ImportState =
  | { kind: "busy" }
  | { kind: "done"; message: string; target: Workspace }
  | { kind: "error"; message: string; retryable: boolean; target: Workspace };

type Warning = {
  paper: Paper;
  target: Workspace;
  score: number | null;
  threshold: number | null;
};

const keyOf = (p: Paper) => `${p.source}:${p.external_id}`;

/**
 * Discover (FR-17, D-077): search arXiv and OpenAlex, then import a paper's open-access PDF
 * into a workspace. Imports go through the same compatibility check and duplicate handling
 * as uploads. Everything shown about a result comes from external APIs.
 */
export function Discover({
  initialWorkspaceId,
}: {
  initialWorkspaceId: string | null;
}) {
  const queryClient = useQueryClient();
  const workspaces = useWorkspaces();
  const [draft, setDraft] = useState("");
  const [scope, setScope] = useState<Scope>("all");
  const [importableOnly, setImportableOnly] = useState(false);
  const [search, setSearch] = useState<{
    q: string;
    scope: Scope;
    importableOnly: boolean;
  } | null>(null);
  const [chosen, setChosen] = useState<string | null>(initialWorkspaceId);
  const [imports, setImports] = useState<Record<string, ImportState>>({});
  const [warning, setWarning] = useState<Warning | null>(null);

  const active = (workspaces.data ?? []).filter((w) => !w.archived);
  const target = active.find((w) => w.id === chosen) ?? active[0];

  const results = useQuery({
    queryKey: ["papers", search?.q, search?.scope, search?.importableOnly],
    enabled: search !== null,
    staleTime: 5 * 60_000,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/papers/search", {
          params: {
            query: {
              q: search!.q,
              source: search!.scope,
              importable_only: search!.importableOnly,
            },
          },
        }),
      ),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const q = draft.trim();
    if (q.length >= 2) setSearch({ q, scope, importableOnly });
  }

  const setState = (paper: Paper, state: ImportState) =>
    setImports((all) => ({ ...all, [keyOf(paper)]: state }));

  async function runImport(paper: Paper, into: Workspace, override: boolean) {
    setWarning(null);
    setState(paper, { kind: "busy" });
    try {
      const result = await unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/import", {
          params: { path: { workspace_id: into.id } },
          body: {
            source: paper.source as "arxiv" | "openalex",
            external_id: paper.external_id,
            override,
          },
        }),
      );
      let message = `Imported into “${into.name}”. It's processed in the background.`;
      if (result.duplicate && result.linked)
        message = `Already in “${into.name}”.`;
      else if (result.duplicate) {
        // The user already has this PDF elsewhere: add that copy instead of a second one.
        await unwrap(
          api.PUT("/api/v1/workspaces/{workspace_id}/documents/{document_id}", {
            params: {
              path: { workspace_id: into.id, document_id: result.document.id },
              query: { override },
            },
          }),
        );
        message = `Added your existing copy to “${into.name}”.`;
      }
      void queryClient.invalidateQueries({ queryKey: ["documents", into.id] });
      setState(paper, { kind: "done", message, target: into });
    } catch (e) {
      if (e instanceof ApiError && e.code === "compatibility_warning") {
        setImports((all) => {
          const rest = { ...all };
          delete rest[keyOf(paper)];
          return rest;
        });
        const { score, threshold } = (e.details ?? {}) as {
          score?: number | null;
          threshold?: number;
        };
        return setWarning({
          paper,
          target: into,
          score: score ?? null,
          threshold: threshold ?? null,
        });
      }
      // A plain reason, never the backend's raw message.
      const failure = importFailure(e instanceof ApiError ? e : { status: 0 });
      setState(paper, { kind: "error", ...failure, target: into });
    }
  }

  return (
    <div>
      <p className="text-xs font-medium tracking-[0.08em] text-muted-foreground uppercase">
        Discover
      </p>
      <h1 className="mt-1 text-3xl font-medium">Find papers</h1>
      <p className="mt-2 max-w-prose text-muted-foreground">
        Search arXiv and OpenAlex and import open-access papers into a
        workspace, where you can ask questions about them with cited answers.
        Every result links to its source; papers without a PDF we can download
        are shown with a link only.
      </p>

      <form
        onSubmit={submit}
        role="search"
        className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-end"
      >
        <label className="grid flex-1 gap-1 text-sm">
          <span className="font-medium">Search</span>
          <Input
            type="search"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. hydrogel stiffness stem cell differentiation"
            minLength={2}
            maxLength={300}
            required
            className="h-10"
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Sources</span>
          <select
            value={scope}
            onChange={(e) => {
              const next = e.target.value as Scope;
              setScope(next);
              // Filtering happens on the server, so an active search is run again.
              setSearch((s) => s && { ...s, scope: next });
            }}
            className={SELECT}
          >
            {SCOPES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" className="h-10 px-5">
          Search
        </Button>
      </form>
      <div className="mt-3 flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <button
          type="button"
          role="switch"
          aria-checked={importableOnly}
          aria-labelledby="importable-only-label"
          onClick={() => {
            const next = !importableOnly;
            setImportableOnly(next);
            setSearch((s) => s && { ...s, importableOnly: next });
          }}
          className="group tap-target relative inline-flex h-6 w-10 shrink-0 items-center rounded-full border bg-muted transition-colors aria-checked:bg-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <span
            aria-hidden
            className="ml-0.5 size-4 rounded-full bg-background shadow-sm transition-transform group-aria-checked:translate-x-4"
          />
        </button>
        <span id="importable-only-label">Importable PDFs only</span>
        <span className="text-muted-foreground">
          {importableOnly
            ? "Showing open-access papers with a PDF link."
            : "Showing all papers, including those with a link only."}
        </span>
      </div>

      <div className="mt-4 text-sm">
        {workspaces.isPending ? null : active.length === 0 ? (
          <p className="text-muted-foreground">
            To import papers, first{" "}
            <Link href="/workspaces" className="link-draw underline">
              create a workspace
            </Link>
            .
          </p>
        ) : (
          <label className="flex flex-wrap items-center gap-2">
            <span className="font-medium">Import into</span>
            <select
              value={target?.id}
              onChange={(e) => setChosen(e.target.value)}
              className={`${SELECT} max-w-full min-w-0`}
            >
              {active.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div aria-live="polite" className="mt-8">
        {search === null ? null : results.isPending ? (
          <p className="text-muted-foreground">
            Searching and checking which PDFs can be downloaded…
          </p>
        ) : results.isError ? (
          <p role="alert" className="text-destructive">
            The search failed: arXiv and OpenAlex didn&apos;t respond.{" "}
            <button
              type="button"
              onClick={() => results.refetch()}
              className="tap-target underline"
            >
              Try again
            </button>
          </p>
        ) : (
          <>
            <SourceNotice
              unavailable={results.data.unavailable ?? []}
              exhausted={results.data.quota_exhausted ?? []}
            />
            {results.data.results.length === 0 ? (
              <p className="text-muted-foreground">
                {search.importableOnly
                  ? `No importable papers found for “${search.q}”. Try other words, or turn off “Importable PDFs only” to see papers with a link only.`
                  : `No papers found for “${search.q}”. Try fewer or different words.`}
              </p>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  <Summary papers={results.data.results} />
                </p>
                <ul className="mt-3 divide-y border-y">
                  {results.data.results.map((p) => (
                    <PaperRow
                      key={keyOf(p)}
                      paper={p}
                      target={target}
                      state={imports[keyOf(p)]}
                      onImport={() => target && runImport(p, target, false)}
                      onRetry={(into) => runImport(p, into, false)}
                    />
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>

      <Dialog
        open={warning !== null}
        onOpenChange={(open) => !open && setWarning(null)}
      >
        {warning && (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>This paper looks unrelated</DialogTitle>
              <DialogDescription>
                “{warning.paper.title}” doesn&apos;t match the topic of “
                {warning.target.name}”
                {warning.score !== null && warning.threshold !== null && (
                  <>
                    {" "}
                    (similarity{" "}
                    <span className="font-mono">
                      {warning.score.toFixed(2)}
                    </span>
                    , threshold{" "}
                    <span className="font-mono">
                      {warning.threshold.toFixed(2)}
                    </span>
                    )
                  </>
                )}
                . Unrelated papers can lower answer quality.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose
                render={<Button variant="outline" className="h-10" />}
              >
                Cancel
              </DialogClose>
              <Button
                className="h-10"
                onClick={() => runImport(warning.paper, warning.target, true)}
              >
                Import anyway
              </Button>
            </DialogFooter>
          </DialogContent>
        )}
      </Dialog>
    </div>
  );
}

/** "12 papers: 4 with a verified PDF, 3 with an unverified PDF link." */
function Summary({ papers }: { papers: Paper[] }) {
  const verified = papers.filter((p) => p.pdf_status === "verified").length;
  const unverified = papers.filter((p) => p.pdf_status === "unverified").length;
  const parts = [
    verified > 0 && `${verified} with a verified PDF`,
    unverified > 0 && `${unverified} with an unverified PDF link`,
  ].filter(Boolean);
  return (
    <>
      {papers.length} {papers.length === 1 ? "paper" : "papers"}
      {parts.length > 0 ? `: ${parts.join(", ")}.` : ", none with a PDF."}
    </>
  );
}

const PDF_STATUS = {
  verified: {
    Icon: FileCheck,
    label: "PDF verified",
    hint: "The PDF answered when we checked it.",
    className: "text-status-supported",
  },
  unverified: {
    Icon: FileQuestion,
    label: "PDF link found, not verified",
    hint: "A PDF link is listed but wasn't checked, or the check didn't finish. Import may fail.",
    className: "text-status-partial",
  },
  none: {
    Icon: Link2,
    label: "Link only",
    hint: "No downloadable open-access PDF was found.",
    className: "text-muted-foreground",
  },
} as const;

function PaperRow({
  paper: p,
  target,
  state,
  onImport,
  onRetry,
}: {
  paper: Paper;
  target: Workspace | undefined;
  state: ImportState | undefined;
  onImport: () => void;
  onRetry: (into: Workspace) => void;
}) {
  const names = p.authors ?? [];
  const authors =
    names.length > 3
      ? `${names.slice(0, 3).join(", ")} et al.`
      : names.join(", ");
  const meta = [authors, p.year, p.venue].filter(Boolean).join(" · ");
  const busy = state?.kind === "busy";
  const imported = state?.kind === "done" && state.target.id === target?.id;
  const slowNote = useSlowNote(busy);

  return (
    <li className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <p className="font-serif text-lg leading-snug break-words">{p.title}</p>
        {meta && (
          <p className="mt-0.5 text-sm break-words text-muted-foreground">
            {meta}
          </p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <PdfStatus status={p.pdf_status} />
          <span className="font-mono text-xs text-muted-foreground">
            {SOURCE_LABEL[p.source] ?? p.source}
            {p.source === "arxiv" ? ` ${p.external_id}` : ""}
          </span>
          {p.doi && (
            <span className="font-mono text-xs break-all text-muted-foreground">
              {p.doi}
            </span>
          )}
          {p.citation_count != null && (
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              cited {p.citation_count}
            </span>
          )}
        </div>
        {p.abstract && (
          <details className="mt-2 text-sm">
            <summary className="tap-target cursor-pointer text-muted-foreground">
              Abstract
            </summary>
            <p className="mt-2 max-w-prose leading-relaxed break-words">
              {p.abstract}
            </p>
          </details>
        )}
        {state?.kind === "done" && (
          <p className="mt-2 text-sm">
            {state.message}{" "}
            <Link
              href={`/workspaces/${state.target.id}`}
              className="link-draw underline"
            >
              Open workspace
            </Link>
            {" · "}
            <Link
              href={`/workspaces/${state.target.id}/chat`}
              className="link-draw underline"
            >
              Ask your papers
            </Link>
          </p>
        )}
        {slowNote && (
          <p className="mt-2 text-sm text-muted-foreground">{slowNote}</p>
        )}
        {state?.kind === "error" && (
          <p role="alert" className="mt-2 text-sm">
            <span className="text-destructive">
              Import failed. {state.message}
            </span>{" "}
            {state.retryable && (
              <button
                type="button"
                onClick={() => onRetry(state.target)}
                className="tap-target underline"
              >
                Try again
              </button>
            )}
          </p>
        )}
      </div>
      <div className="flex shrink-0 gap-2 self-start">
        {p.url && (
          <a
            href={p.url}
            target="_blank"
            rel="noopener noreferrer"
            className="tap-target inline-flex h-10 items-center gap-1.5 px-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Open source
            <ExternalLink aria-hidden className="size-3.5" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
        {p.pdf_urls?.[0] && (
          <a
            href={p.pdf_urls[0]}
            target="_blank"
            rel="noopener noreferrer"
            className="tap-target inline-flex h-10 items-center gap-1.5 px-2 text-sm text-muted-foreground hover:text-foreground"
          >
            PDF
            <ExternalLink aria-hidden className="size-3.5" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
        {p.importable && (
          <Button
            variant="outline"
            className="h-10 px-4"
            disabled={!target || busy || imported}
            onClick={onImport}
          >
            {busy ? "Importing…" : imported ? "Imported" : "Import"}
          </Button>
        )}
      </div>
    </li>
  );
}

function PdfStatus({ status }: { status: Paper["pdf_status"] }) {
  const { Icon, label, hint, className } = PDF_STATUS[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 ${className}`}
      title={hint}
    >
      <Icon aria-hidden className="size-4" />
      {label}
      <span className="sr-only">. {hint}</span>
    </span>
  );
}

/** Counts seconds while an import runs; the note for its elapsed time. */
function useSlowNote(active: boolean): string | null {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => {
      clearInterval(timer);
      setSeconds(0);
    };
  }, [active]);
  return active ? slowImportNote(seconds) : null;
}

/** Which sources are missing from the results, and why. */
function SourceNotice({
  unavailable,
  exhausted,
}: {
  unavailable: string[];
  exhausted: string[];
}) {
  if (unavailable.length === 0) return null;
  const names = (sources: string[]) =>
    sources.map((s) => SOURCE_LABEL[s] ?? s).join(" and ");
  const down = unavailable.filter((s) => !exhausted.includes(s));
  return (
    <div className="mb-4 flex items-start gap-2 rounded-lg border p-3 text-sm">
      <CircleAlert
        aria-hidden
        className="mt-0.5 size-4 shrink-0 text-status-partial"
      />
      <div>
        {exhausted.length > 0 && (
          <p>
            {names(exhausted)}&apos;s free daily search limit has been reached,
            so its results are missing. It resets within a day.
          </p>
        )}
        {down.length > 0 && (
          <p>
            {names(down)} didn&apos;t respond, so these results are incomplete.
            Try again shortly.
          </p>
        )}
      </div>
    </div>
  );
}
