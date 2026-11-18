import assert from "node:assert/strict";
import { test } from "node:test";

import { answerLoaded } from "./live.ts";

const history = [{ id: "q1" }, { id: "a1" }];

test("a new question stays visible while earlier answers are loaded", () => {
  assert.equal(answerLoaded(undefined, history), false);
});

test("the live block waits until its own answer is in the history", () => {
  assert.equal(answerLoaded("a2", history), false);
  assert.equal(
    answerLoaded("a2", [...history, { id: "q2" }, { id: "a2" }]),
    true,
  );
});
