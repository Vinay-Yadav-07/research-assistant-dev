"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Network, RefreshCw, X } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { type Cite, useSourceViewer } from "@/components/analysis/results";
import { citationLabel } from "@/components/chat/answer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDocuments } from "@/components/workspaces/document-library";
import { api, type Schemas, unwrap } from "@/lib/api/client";

import { RELATION_LABEL, type Selection } from "./graph-canvas";
import { connectedIds, filterEdges, layout, type SortKey } from "./layout";

type Graph = Schemas["KnowledgeGraphRead"];
type GraphEdge = Schemas["KGEdgeRead"];

const GraphCanvas = dynamic(() => import("./graph-canvas"), {
  ssr: false,
  loading: () => <p className="p-4 text-muted-foreground">Loading graph…</p>,
});

// States in which the backend is running a job; the page polls until it ends.
const ACTIVE: Graph["state"][] = ["queued", "generating", "updating"];
const EVIDENCE_LIMIT = 20;
const SELECT =
  "h-10 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";
const SORTS: { value: SortKey; label: string }[] = [
  { value: "support", label: "Most supported" },
  { value: "relation", label: "Relationship" },
  { value: "source", label: "Source A–Z" },
];

function graphKey(workspaceId: string) {
  return ["knowledge-graph", workspaceId];
}

/** The workspace knowledge graph: job status, canvas, relationship list, and evidence (FR-33). */
export function KnowledgeGraph({ workspaceId }: { workspaceId: string }) {
  const queryClient = useQueryClient();
  const path = { workspace_id: workspaceId };
  // Status always comes from the backend, so a refresh or a return to the page resumes it.
  const graph = useQuery({
    queryKey: graphKey(workspaceId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/workspaces/{workspace_id}/knowledge-graph", {
          params: { path },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data && ACTIVE.includes(query.state.data.state)
        ? 3000
        : false,
  });
  const start = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/workspaces/{workspace_id}/knowledge-graph/jobs", {
          params: { path },
        }),
      ),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: graphKey(workspaceId) }),
  });
  const documents = useDocuments(workspaceId);
  const docsById = useMemo(
    () => new Map((documents.data ?? []).map((d) => [d.id, d])),
    [documents.data],
  );
  const { cite, viewer } = useSourceViewer(docsById);
  const [selection, setSelection] = useState<Selection>(null);

  return (
    <div>
      <Link
        href={`/workspaces/${workspaceId}`}
        className="link-draw tap-target text-sm text-muted-foreground"
      >
        ← Library
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <h1 className="text-3xl font-medium">Knowledge graph</h1>
        {graph.data && (
          <StartButton
            graph={graph.data}
            pending={start.isPending}
            onStart={() => start.mutate()}
          />
        )}
      </div>
      <p className="mt-2 max-w-[72ch] text-muted-foreground">
        Methods, datasets, findings and how your papers relate them. A model
        extracts each relationship from a quoted passage; open its evidence and
        check the passage before relying on it.
      </p>
      {start.isError && (
        <p role="alert" className="mt-3 text-destructive">
          Couldn&apos;t start: {start.error.message}
        </p>
      )}

      <div className="mt-6">
        {graph.isPending ? (
          <p className="text-muted-foreground">Loading the graph…</p>
        ) : graph.isError ? (
          <p role="alert" className="text-destructive">
            Couldn&apos;t load the graph: {graph.error.message}
          </p>
        ) : (
          <>
            <Status graph={graph.data} />
            {graph.data.nodes.length > 0 ? (
              <GraphView
                workspaceId={workspaceId}
                graph={graph.data}
                selection={selection}
                onSelect={setSelection}
                cite={cite}
              />
            ) : (
              <Empty graph={graph.data} />
            )}
          </>
        )}
      </div>
      {viewer}
    </div>
  );
}

function StartButton({
  graph,
  pending,
  onStart,
}: {
  graph: Graph;
  pending: boolean;
  onStart: () => void;
}) {
  if (ACTIVE.includes(graph.state)) return null;
  const first = graph.built_at === null;
  return (
    <Button
      className="h-10 px-4"
      variant={
        graph.state === "update_available" || first ? "default" : "outline"
      }
      disabled={pending || graph.ready_documents === 0}
      onClick={onStart}
    >
      {first ? <Network aria-hidden /> : <RefreshCw aria-hidden />}
      {first ? "Generate graph" : "Update graph"}
    </Button>
  );
}

/** One quiet line for what the backend reports: job progress, staleness, failure, truncation. */
function Status({ graph }: { graph: Graph }) {
  const job = graph.active_job;
  const failed = graph.state === "failed" ? graph.last_job : null;
  return (
    <div aria-live="polite" className="mb-4 grid gap-2">
      {job && (
        <p className="font-mono text-sm">
          {job.status === "queued"
            ? "Waiting to start"
            : job.phase === "building"
              ? "Building the graph"
              : `Reading papers · ${job.documents_done} of ${job.documents_total}`}
          {graph.state === "updating" && (
            <span className="text-muted-foreground">
              {" "}
              · the current graph stays until it finishes
            </span>
          )}
        </p>
      )}
      {failed && (
        <p role="alert" className="text-destructive">
          {failed.error_message ?? "Graph generation failed."} Papers already
          read are kept; generating again continues from them.
        </p>
      )}
      {(graph.state === "update_available" || (graph.stale && !job)) && (
        <p className="text-muted-foreground">
          The papers in this workspace changed since this graph was built.
          Update it to include them.
        </p>
      )}
      {graph.truncated && (
        <p className="text-muted-foreground">
          Showing the {graph.nodes.length} most-supported of {graph.node_count}{" "}
          entities.
        </p>
      )}
    </div>
  );
}

function Empty({ graph }: { graph: Graph }) {
  if (ACTIVE.includes(graph.state) || graph.state === "failed") return null;
  return (
    <p className="text-muted-foreground">
      {graph.ready_documents === 0
        ? "Add papers to this workspace first; the graph is built from its ready papers."
        : graph.built_at === null
          ? `No graph yet. Generate one to read the workspace's ${graph.ready_documents} ready papers.`
          : "No entities passed the evidence checks in these papers."}
    </p>
  );
}

function GraphView({
  workspaceId,
  graph,
  selection,
  onSelect,
  cite,
}: {
  workspaceId: string;
  graph: Graph;
  selection: Selection;
  onSelect: (s: Selection) => void;
  cite: Cite;
}) {
  const [showIsolated, setShowIsolated] = useState(false);
  const linked = useMemo(() => connectedIds(graph.edges), [graph.edges]);
  const isolated = graph.nodes.filter((n) => !linked.has(n.id));
  const placed = useMemo(
    () => layout(graph.nodes, graph.edges, showIsolated),
    [graph.nodes, graph.edges, showIsolated],
  );
  const labels = useMemo(
    () => new Map(graph.nodes.map((n) => [n.id, n.label])),
    [graph.nodes],
  );

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="font-mono text-muted-foreground tabular-nums">
          {graph.edges.length} relationships · {linked.size} connected entities
          {isolated.length > 0 &&
            !showIsolated &&
            ` · ${isolated.length} isolated hidden`}
        </p>
        {isolated.length > 0 && (
          <Button
            variant="outline"
            className="h-10 px-3"
            aria-pressed={showIsolated}
            onClick={() => setShowIsolated((v) => !v)}
          >
            {showIsolated
              ? `Hide ${isolated.length} isolated entities`
              : `Show ${isolated.length} isolated entities`}
          </Button>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="h-[60vh] min-h-80 overflow-hidden rounded-[10px] border">
          {placed.length > 0 ? (
            <GraphCanvas
              placed={placed}
              edges={graph.edges}
              selection={selection}
              onSelect={onSelect}
            />
          ) : (
            <p className="p-4 text-muted-foreground">
              No relationships passed the evidence checks. Show the{" "}
              {isolated.length} isolated entities to see what was found.
            </p>
          )}
        </div>
        <EvidencePanel
          workspaceId={workspaceId}
          graph={graph}
          labels={labels}
          selection={selection}
          onClose={() => onSelect(null)}
          cite={cite}
        />
      </div>
      <RelationshipList
        edges={graph.edges}
        isolated={showIsolated ? isolated : []}
        labels={labels}
        onSelect={onSelect}
      />
    </>
  );
}

function RelationshipList({
  edges,
  isolated,
  labels,
  onSelect,
}: {
  edges: GraphEdge[];
  isolated: Graph["nodes"];
  labels: Map<string, string>;
  onSelect: (s: Selection) => void;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("support");
  const shown = filterEdges(edges, labels, query, sort);
  return (
    <section className="mt-10" aria-labelledby="relationships">
      <h2 id="relationships" className="text-xl font-medium">
        Relationships
      </h2>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="grid min-w-0 flex-1 gap-1 text-sm">
          <span className="font-medium">Search</span>
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Entity or relationship"
            className="h-10"
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Sort by</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className={SELECT}
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p
        aria-live="polite"
        className="mt-3 font-mono text-xs text-muted-foreground"
      >
        {shown.length} of {edges.length} relationships
      </p>
      <ul className="mt-2 divide-y border-y">
        {shown.map((e) => (
          <li
            key={e.id}
            className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2"
          >
            <span className="min-w-0 break-words">
              {labels.get(e.source_node_id)}{" "}
              <span className="font-mono text-sm text-muted-foreground">
                {RELATION_LABEL[e.relation_type]}
              </span>{" "}
              {labels.get(e.target_node_id)}
            </span>
            <span className="flex items-center gap-3">
              <span className="font-mono text-xs text-muted-foreground tabular-nums">
                {e.document_count} {e.document_count === 1 ? "paper" : "papers"}{" "}
                · {e.mention_count}{" "}
                {e.mention_count === 1 ? "passage" : "passages"}
              </span>
              <Button
                variant="ghost"
                className="h-10 px-3"
                onClick={() => onSelect({ kind: "edge", id: e.id })}
              >
                Evidence
              </Button>
            </span>
          </li>
        ))}
      </ul>
      {isolated.length > 0 && (
        <>
          <h3 className="mt-8 text-lg font-medium">
            Entities without relationships ({isolated.length})
          </h3>
          <ul className="mt-2 divide-y border-y">
            {isolated.map((n) => (
              <li
                key={n.id}
                className="flex flex-wrap items-center justify-between gap-x-4 py-1"
              >
                <span className="min-w-0 break-words">
                  {n.label}{" "}
                  <span className="font-mono text-xs text-muted-foreground">
                    {n.entity_type}
                  </span>
                </span>
                <Button
                  variant="ghost"
                  className="h-10 px-3"
                  onClick={() => onSelect({ kind: "node", id: n.id })}
                >
                  Evidence
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

/** The passages behind the selected entity or relationship, each openable in the source viewer. */
function EvidencePanel({
  workspaceId,
  graph,
  labels,
  selection,
  onClose,
  cite,
}: {
  workspaceId: string;
  graph: Graph;
  labels: Map<string, string>;
  selection: Selection;
  onClose: () => void;
  cite: Cite;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const evidence = useQuery({
    queryKey: ["knowledge-graph-evidence", workspaceId, selection],
    enabled: selection !== null,
    queryFn: () => {
      const { kind, id } = selection!;
      const query = { limit: EVIDENCE_LIMIT };
      return kind === "node"
        ? unwrap(
            api.GET(
              "/api/v1/workspaces/{workspace_id}/knowledge-graph/nodes/{node_id}/evidence",
              {
                params: {
                  path: { workspace_id: workspaceId, node_id: id },
                  query,
                },
              },
            ),
          )
        : unwrap(
            api.GET(
              "/api/v1/workspaces/{workspace_id}/knowledge-graph/edges/{edge_id}/evidence",
              {
                params: {
                  path: { workspace_id: workspaceId, edge_id: id },
                  query,
                },
              },
            ),
          );
    },
  });
  // Move focus to the panel so keyboard and screen-reader users land on what they opened.
  useEffect(() => {
    if (selection) heading.current?.focus();
  }, [selection]);

  if (selection === null) {
    return (
      <aside className="rounded-[10px] border p-4 text-sm text-muted-foreground">
        Select an entity or relationship, in the graph or the list below, to see
        the passages it comes from.
      </aside>
    );
  }
  const node = graph.nodes.find((n) => n.id === selection.id);
  const edge = graph.edges.find((e) => e.id === selection.id);
  const title =
    selection.kind === "edge" && edge
      ? `${labels.get(edge.source_node_id)} ${RELATION_LABEL[edge.relation_type]} ${labels.get(edge.target_node_id)}`
      : (node?.label ?? "");

  return (
    <aside
      aria-labelledby="evidence-title"
      className="min-w-0 rounded-[10px] border bg-card p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-xs tracking-[0.08em] text-muted-foreground uppercase">
            {selection.kind === "edge" ? "Relationship" : node?.entity_type}
          </p>
          <h2
            id="evidence-title"
            ref={heading}
            tabIndex={-1}
            className="mt-1 font-serif text-lg leading-snug break-words outline-none"
          >
            {title}
          </h2>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-10"
          aria-label="Close evidence"
          onClick={onClose}
        >
          <X aria-hidden />
        </Button>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        Extracted from your papers by a model, not checked by a person. Read
        each passage before relying on this{" "}
        {selection.kind === "edge" ? "relationship" : "entity"}.
      </p>
      <div className="mt-4">
        {evidence.isPending ? (
          <p className="text-sm text-muted-foreground">Loading passages…</p>
        ) : evidence.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Couldn&apos;t load the evidence: {evidence.error.message}
          </p>
        ) : evidence.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No passages from the workspace&apos;s current papers.
          </p>
        ) : (
          <ul className="grid gap-4">
            {evidence.data.map((c) => (
              <li key={c.id} className="grid gap-1.5">
                <p className="font-serif text-sm leading-snug break-words">
                  {c.document_title ?? "Untitled paper"}
                </p>
                <p className="font-mono text-xs text-muted-foreground">
                  {citationLabel(c, cite.documents)}
                  {c.section && ` · ${c.section}`}
                </p>
                {c.quote && (
                  <blockquote className="border-l-2 border-border bg-surface-sunk px-3 py-2 text-sm leading-relaxed">
                    <mark className="rounded-[2px] bg-mark px-0.5 text-mark-foreground">
                      {c.quote}
                    </mark>
                  </blockquote>
                )}
                {c.source_type === "workspace" && c.document_id && (
                  <Button
                    variant="outline"
                    className="h-10 w-fit px-3"
                    onClick={() => cite.onOpen(c)}
                  >
                    Open in source
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {evidence.data?.length === EVIDENCE_LIMIT && (
          <p className="mt-3 text-xs text-muted-foreground">
            Showing the first {EVIDENCE_LIMIT} passages.
          </p>
        )}
      </div>
    </aside>
  );
}
