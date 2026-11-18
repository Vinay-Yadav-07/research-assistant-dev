import assert from "node:assert/strict";
import { test } from "node:test";

import { asCitation } from "./citations.ts";

test("a snapshot without optional fields becomes a citation with nulls and the given id", () => {
  assert.deepEqual(asCitation({ source_type: "workspace" }, "k1"), {
    id: "k1",
    source_type: "workspace",
    document_id: null,
    chunk_id: null,
    document_title: null,
    page_start: null,
    page_end: null,
    section: null,
    quote: null,
  });
});

test("snapshot fields are kept", () => {
  const c = asCitation(
    {
      source_type: "workspace",
      document_id: "d1",
      page_start: 3,
      page_end: 4,
      quote: "PCL scaffolds",
    },
    "k2",
  );
  assert.equal(c.document_id, "d1");
  assert.equal(c.page_start, 3);
  assert.equal(c.page_end, 4);
  assert.equal(c.quote, "PCL scaffolds");
});
