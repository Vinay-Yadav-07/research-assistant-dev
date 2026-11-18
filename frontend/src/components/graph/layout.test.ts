import assert from "node:assert/strict";
import { test } from "node:test";

import { connectedIds, filterEdges, layout } from "./layout.ts";

const node = (id: string, label = id) => ({
  id,
  entity_type: "method" as const,
  label,
  aliases: [],
  document_count: 1,
  mention_count: 1,
});
const edge = (
  id: string,
  source: string,
  target: string,
  relation_type: "uses" | "reports" | "compared_with" = "uses",
  document_count = 1,
) => ({
  id,
  source_node_id: source,
  target_node_id: target,
  relation_type,
  document_count,
  mention_count: document_count,
});

const nodes = [
  node("a", "LSTM"),
  node("b", "M4"),
  node("c", "ARIMA"),
  node("x"),
];
const edges = [edge("e1", "a", "b"), edge("e2", "c", "a", "compared_with", 2)];

test("only nodes with an edge are connected", () => {
  assert.deepEqual([...connectedIds(edges)].sort(), ["a", "b", "c"]);
});

test("isolated nodes are hidden by default and placed below when shown", () => {
  const hidden = layout(nodes, edges, false);
  assert.deepEqual(hidden.map((p) => p.node.id).sort(), ["a", "b", "c"]);

  const shown = layout(nodes, edges, true);
  const isolated = shown.find((p) => p.node.id === "x");
  assert.ok(isolated);
  assert.ok(isolated.y > Math.max(...hidden.map((p) => p.y)));
  assert.ok(shown.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)));
});

test("left to right: an edge's source sits left of its target", () => {
  const at = new Map(layout(nodes, edges, false).map((p) => [p.node.id, p]));
  assert.ok(at.get("a")!.x < at.get("b")!.x);
});

test("no edges and isolated hidden places nothing", () => {
  assert.deepEqual(layout(nodes, [], false), []);
  assert.equal(layout(nodes, [], true).length, nodes.length);
});

test("the relationship list filters by any part and sorts", () => {
  const labels = new Map(nodes.map((n) => [n.id, n.label]));
  assert.deepEqual(
    filterEdges(edges, labels, "compared", "support").map((e) => e.id),
    ["e2"],
  );
  assert.deepEqual(
    filterEdges(edges, labels, "m4", "support").map((e) => e.id),
    ["e1"],
  );
  assert.deepEqual(
    filterEdges(edges, labels, "", "support").map((e) => e.id),
    ["e2", "e1"],
  );
  assert.deepEqual(
    filterEdges(edges, labels, "", "source").map((e) => e.id),
    ["e2", "e1"],
  );
});
