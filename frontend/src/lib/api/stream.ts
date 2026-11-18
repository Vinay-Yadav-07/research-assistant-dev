import { ApiError, API_BASE_URL, accessToken, type Schemas } from "./client";

/** One event of a QA run's SSE stream (backend `QAEvent`). */
export type RunEvent =
  | Schemas["StatusEvent"]
  | Schemas["ApprovalRequiredEvent"]
  | Schemas["ClaimsEvent"]
  | Schemas["CitationsEvent"]
  | Schemas["ErrorEvent"]
  | Schemas["DoneEvent"];

export type Decision = Schemas["RunResume"]["decision"];

/** Ask a question in a conversation; yields the run's events (`sendMessage`). */
export function sendMessage(
  conversationId: string,
  body: Schemas["MessageCreate"],
  signal?: AbortSignal,
) {
  return streamEvents(
    `/api/v1/conversations/${conversationId}/messages`,
    body,
    signal,
  );
}

/** Answer a paused run's approval request; yields the rest of its events (`resumeRun`). */
export function resumeRun(
  runId: string,
  body: Schemas["RunResume"],
  signal?: AbortSignal,
) {
  return streamEvents(`/api/v1/runs/${runId}/resume`, body, signal);
}

/**
 * POSTs JSON and reads the SSE response. `openapi-fetch` cannot stream, so this is the one call
 * outside the generated client; its types still come from the generated schema.
 * A rejected request (4xx/5xx) throws an `ApiError` before any event.
 */
async function* streamEvents(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<RunEvent> {
  const token = await accessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(token && { Authorization: `Bearer ${token}` }),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    const error = (await response.json().catch(() => undefined)) as
      Partial<Schemas["ErrorResponse"]> | undefined;
    throw new ApiError(
      response.status,
      error?.error?.code,
      error?.error?.message,
    );
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value.replace(/\r\n?/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      // Keepalive comments have no `data:` line and are skipped.
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""));
      if (data.length) yield JSON.parse(data.join("\n")) as RunEvent;
    }
  }
}
