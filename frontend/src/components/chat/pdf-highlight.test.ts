import assert from "node:assert/strict";
import { test } from "node:test";

import { findQuote, markItem } from "./pdf-highlight.ts";

const items = [
  { str: "Hydrogel scaffolds degrade", hasEOL: true },
  { str: "" },
  { str: "too quickly in vivo, which limits", hasEOL: true },
  { str: "load-bearing use. Other text." },
];

test("marks a quote spread over several items, ignoring case and punctuation", () => {
  const found = findQuote(
    items,
    "**hydrogel** scaffolds degrade too quickly in vivo, which limits load-bearing",
  );
  assert.deepEqual(
    [...found],
    [
      [0, [[0, 26]]],
      [2, [[0, 33]]],
      [3, [[0, 12]]],
    ],
  );
});

test("marks the part of a quote that is on this page", () => {
  const found = findQuote(
    items,
    "Earlier page words here. Which limits load-bearing use…",
  );
  assert.deepEqual(
    [...found],
    [
      [2, [[21, 33]]],
      [3, [[0, 16]]],
    ],
  );
});

test("returns nothing when only a few words match", () => {
  assert.equal(findQuote(items, "scaffolds are stiff and brittle").size, 0);
  assert.equal(findQuote(items, "").size, 0);
});

test("a short quote must match in full", () => {
  assert.equal(findQuote(items, "degrade too quickly").size, 2);
});

test("markItem escapes text and wraps ranges", () => {
  assert.equal(
    markItem("a <b> & c", [[2, 5]]),
    "a <mark>&lt;b&gt;</mark> &amp; c",
  );
  assert.equal(markItem("plain"), "plain");
});

test("matches words split over items, line-end hyphens and HTML tags", () => {
  const split = [
    { str: "stiffness is signifi-", hasEOL: true },
    { str: "cantly higher with biodegr" },
    { str: "ad" },
    { str: "ability" },
  ];
  const found = findQuote(
    split,
    "<mark>Stiffness is significantly higher</mark> with biodegradability",
  );
  assert.deepEqual(
    [...found],
    [
      [0, [[0, 21]]],
      [1, [[0, 26]]],
      [2, [[0, 2]]],
      [3, [[0, 7]]],
    ],
  );
});
