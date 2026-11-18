import assert from "node:assert/strict";
import { test } from "node:test";

import { importFailure } from "./import-errors.ts";

const pdf = (reason: string, retryable: boolean) =>
  importFailure({
    status: 502,
    code: "pdf_unavailable",
    details: { reason, retryable, attempts: [] },
  });

test("a timed-out PDF download can be retried", () => {
  assert.deepEqual(pdf("timeout", true), {
    message: "The PDF's host didn't respond in time.",
    retryable: true,
  });
});

test("a publisher 403 explains the block and offers no retry", () => {
  const failure = pdf("access_denied", false);
  assert.match(failure.message, /publisher blocks automated downloads/);
  assert.equal(failure.retryable, false);
});

test("a web page instead of a PDF points to the source", () => {
  assert.match(pdf("not_pdf", false).message, /web page, not a PDF/);
});

test("a source lookup timeout names the source and can be retried", () => {
  assert.deepEqual(
    importFailure({
      status: 502,
      code: "source_unavailable",
      details: { source: "arxiv", reason: "timeout" },
    }),
    {
      message: "arXiv didn't respond while looking up the paper.",
      retryable: true,
    },
  );
});

test("raw backend messages never reach the user", () => {
  const failure = importFailure({
    status: 502,
    code: "external_service_error",
  });
  assert.equal(
    failure.message,
    "The import failed because of a server problem.",
  );
  assert.doesNotMatch(failure.message, /Timed out/);
});

test("an unknown PDF reason falls back to a plain message", () => {
  assert.equal(
    pdf("something_new", false).message,
    "The PDF couldn't be downloaded. Open the source to read it.",
  );
});

test("no response from the server can be retried", () => {
  assert.deepEqual(importFailure({ status: 0 }), {
    message: "Couldn't reach the server.",
    retryable: true,
  });
});

test("a paper without an open-access PDF cannot be retried", () => {
  assert.equal(
    importFailure({ status: 422, code: "not_open_access" }).retryable,
    false,
  );
});

test("a used-up OpenAlex quota is explained and not offered for retry", () => {
  assert.deepEqual(
    importFailure({
      status: 502,
      code: "source_unavailable",
      details: { source: "openalex", reason: "quota_exhausted" },
    }),
    {
      message:
        "OpenAlex's daily request limit has been reached. Try again later.",
      retryable: false,
    },
  );
});
