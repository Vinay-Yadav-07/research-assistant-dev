import dagre from "@dagrejs/dagre";

import type { Schemas } from "@/lib/api/client";

type Node = Schemas["KGNodeRead"];
type Edge = Schemas["KGEdgeRead"];

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 56;
const GAP = 24;
const ISOLATED_COLUMNS = 4;

/** Where one node sits on the canvas (top-left corner). */
export type Placed = { node: Node; x: number; y: number };

/** Ids of nodes that take part in at least one edge. */
export function connectedIds(edges: Edge[]): Set<string> {
  return new Set(edges.flatMap((e) => [e.source_node_id, e.target_node_id]));
}

/**
 * Left-to-right positions for the connected nodes (dagre), and, when `showIsolated`, the nodes
 * without an edge in a grid below them. Only nodes and edges from the API are placed; nothing
 * is added.
 */
export function layout(
  nodes: Node[],
  edges: Edge[],
  showIsolated: boolean,
): Placed[] {
  const linked = connectedIds(edges);
  const g = new dagre.graphlib.Graph();
  g.setGraph({
    rankdir: "LR",
    nodesep: GAP,
    ranksep: 80,
    marginx: 8,
    marginy: 8,
  });
  g.setDefaultEdgeLabel(() => ({}));
  const connected = nodes.filter((n) => linked.has(n.id));
  for (const n of connected) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of edges) g.setEdge(e.source_node_id, e.target_node_id);
  dagre.layout(g);
  const placed = connected.map((node) => {
    const { x, y } = g.node(node.id);
    return { node, x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 };
  });
  if (!showIsolated) return placed;
  const top = placed.length
    ? Math.max(...placed.map((p) => p.y)) + NODE_HEIGHT + GAP * 3
    : 0;
  const isolated = nodes.filter((n) => !linked.has(n.id));
  return placed.concat(
    isolated.map((node, i) => ({
      node,
      x: (i % ISOLATED_COLUMNS) * (NODE_WIDTH + GAP),
      y: top + Math.floor(i / ISOLATED_COLUMNS) * (NODE_HEIGHT + GAP),
    })),
  );
}

export type SortKey = "support" | "relation" | "source";

/** Edges whose source, relationship, or target contains `query` (case-insensitive), sorted. */
export function filterEdges(
  edges: Edge[],
  labels: Map<string, string>,
  query: string,
  sort: SortKey,
): Edge[] {
  const q = query.trim().toLowerCase();
  const text = (e: Edge) =>
    `${labels.get(e.source_node_id) ?? ""} ${e.relation_type.replace("_", " ")} ${labels.get(e.target_node_id) ?? ""}`.toLowerCase();
  const source = (e: Edge) => labels.get(e.source_node_id) ?? "";
  const compare: Record<SortKey, (a: Edge, b: Edge) => number> = {
    support: (a, b) =>
      b.document_count - a.document_count || b.mention_count - a.mention_count,
    relation: (a, b) => a.relation_type.localeCompare(b.relation_type),
    source: (a, b) => source(a).localeCompare(source(b)),
  };
  return edges.filter((e) => !q || text(e).includes(q)).sort(compare[sort]);
}
