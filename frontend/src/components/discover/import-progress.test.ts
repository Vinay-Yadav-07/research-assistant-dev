import assert from "node:assert/strict";
import { test } from "node:test";

import { slowImportNote } from "./import-progress.ts";

test("a normal import shows no note", () => {
  assert.equal(slowImportNote(0), null);
  assert.equal(slowImportNote(9), null);
});

test("a slow import says so without a fake percentage", () => {
  const note = slowImportNote(12);
  assert.match(note ?? "", /responding slowly/);
  assert.doesNotMatch(note ?? "", /%/);
});

test("a very slow import explains that it stops by itself", () => {
  assert.match(slowImportNote(60) ?? "", /stops by itself/);
});
