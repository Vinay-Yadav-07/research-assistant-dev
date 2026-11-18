"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  type Edge,
  type EdgeChange,
  Handle,
  MarkerType,
  type Node,
  type NodeChange,
  type NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { type CSSProperties, useMemo } from "react";

import { cn } from "@/lib/utils";
import type { Schemas } from "@/lib/api/client";

import { NODE_HEIGHT, NODE_WIDTH, type Placed } from "./layout";

type GraphEdge = Schemas["KGEdgeRead"];
export type Selection = { kind: "node" | "edge"; id: string } | null;
type EntityData = { label: string; type: string };

export const RELATION_LABEL: Record<GraphEdge["relation_type"], string> = {
  uses: "uses",
  evaluated_on: "evaluated on",
  measured_by: "measured by",
  addresses: "addresses",
  compared_with: "compared with",
  reports: "reports",
};

// React Flow's own colours, mapped to the project tokens so both themes follow DESIGN.md.
const THEME = {
  "--xy-background-color": "var(--card)",
  "--xy-background-pattern-dots-color": "var(--rule)",
  "--xy-edge-stroke": "var(--muted-foreground)",
  "--xy-edge-stroke-selected": "var(--foreground)",
  "--xy-edge-label-background-color": "var(--card)",
  "--xy-edge-label-color": "var(--muted-foreground)",
  "--xy-controls-button-background-color": "var(--card)",
  "--xy-controls-button-background-color-hover": "var(--muted)",
  "--xy-controls-button-color": "var(--foreground)",
  "--xy-controls-button-border-color": "var(--border)",
  "--xy-attribution-background-color": "transparent",
} as CSSProperties;

function EntityNode({ data, selected }: NodeProps<Node<EntityData>>) {
  return (
    <div
      title={data.label}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      className={cn(
        "flex flex-col justify-center rounded-[6px] border bg-card px-3 text-left",
        selected && "border-foreground ring-2 ring-highlight",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        isConnectable={false}
        className="!opacity-0"
      />
      <span className="font-mono text-[10px] tracking-[0.08em] text-muted-foreground uppercase">
        {data.type}
      </span>
      <span className="truncate text-sm">{data.label}</span>
      <Handle
        type="source"
        position={Position.Right}
        isConnectable={false}
        className="!opacity-0"
      />
    </div>
  );
}

const NODE_TYPES = { entity: EntityNode };

/** The graph as placed by `layout`; selecting a node or edge (click, or Enter on focus) opens it. */
export default function GraphCanvas({
  placed,
  edges,
  selection,
  onSelect,
}: {
  placed: Placed[];
  edges: GraphEdge[];
  selection: Selection;
  onSelect: (selection: Selection) => void;
}) {
  const labels = useMemo(
    () => new Map(placed.map((p) => [p.node.id, p.node.label])),
    [placed],
  );
  const nodes = useMemo<Node<EntityData>[]>(
    () =>
      placed.map(({ node, x, y }) => ({
        id: node.id,
        type: "entity",
        position: { x, y },
        data: { label: node.label, type: node.entity_type },
        ariaLabel: `${node.entity_type} ${node.label}`,
        selected: selection?.kind === "node" && selection.id === node.id,
      })),
    [placed, selection],
  );
  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((e) => {
        const relation = RELATION_LABEL[e.relation_type];
        return {
          id: e.id,
          source: e.source_node_id,
          target: e.target_node_id,
          label: relation,
          markerEnd: { type: MarkerType.ArrowClosed },
          ariaLabel: `${labels.get(e.source_node_id)} ${relation} ${labels.get(e.target_node_id)}`,
          selected: selection?.kind === "edge" && selection.id === e.id,
          labelStyle: { fontFamily: "var(--font-plex-mono)", fontSize: 11 },
        };
      }),
    [edges, labels, selection],
  );

  const select = (
    kind: "node" | "edge",
    changes: (NodeChange | EdgeChange)[],
  ) => {
    const picked = changes.find((c) => c.type === "select" && c.selected);
    if (picked && "id" in picked) onSelect({ kind, id: picked.id });
  };

  return (
    <div style={THEME} className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={(changes) => select("node", changes)}
        onEdgesChange={(changes) => select("edge", changes)}
        nodesDraggable={false}
        nodesConnectable={false}
        fitView
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
