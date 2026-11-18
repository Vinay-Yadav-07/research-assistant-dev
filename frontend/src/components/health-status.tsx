"use client";

import { useEffect, useState } from "react";

import { api, API_BASE_URL } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; version: string }
  | { kind: "error"; message: string };

/** Calls `GET /api/v1/health` through the generated client and shows a status dot. */
export function HealthStatus() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    api
      .GET("/api/v1/health")
      .then(({ data, response }) => {
        if (cancelled) return;
        setState(
          data
            ? { kind: "ok", version: data.version }
            : { kind: "error", message: `HTTP ${response.status}` },
        );
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const label = {
    loading: "Checking API…",
    ok: "API online",
    error: "API unreachable",
  }[state.kind];
  const detail =
    state.kind === "ok"
      ? `version ${state.version}`
      : state.kind === "error"
        ? state.message
        : "";

  return (
    <span
      role="status"
      title={`${API_BASE_URL} ${detail}`.trim()}
      className="inline-flex items-center gap-2 text-sm text-muted-foreground"
    >
      <span
        aria-hidden
        className={cn(
          "size-2 rounded-full",
          state.kind === "loading" && "bg-muted-foreground/40",
          state.kind === "ok" && "bg-status-supported",
          state.kind === "error" && "bg-status-unsupported",
        )}
      />
      {label}
    </span>
  );
}
