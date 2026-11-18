import createClient from "openapi-fetch";

import { SUPABASE_URL, supabase } from "@/lib/supabase/client";

import type { components, paths } from "./schema";

/** Backend base URL, inlined at build time. Defaults to the local uvicorn server. */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Typed client generated from the backend OpenAPI schema (`npm run gen:api`). All API calls go through it. */
export const api = createClient<paths>({ baseUrl: API_BASE_URL });

export type Schemas = components["schemas"];

/** The current Supabase access token (refreshed by supabase-js when expired), if signed in in the browser. */
export async function accessToken(): Promise<string | undefined> {
  // Server-side or Supabase not configured (e.g. local dev without .env.local): send unsigned.
  if (typeof window === "undefined" || !SUPABASE_URL) return undefined;
  const { data } = await supabase().auth.getSession();
  return data.session?.access_token;
}

// Signs every browser request with the current access token.
api.use({
  async onRequest({ request }) {
    const token = await accessToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

/** A failed API call; `code` is the backend's error code (e.g. `compatibility_warning`). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code?: string,
    message?: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message ?? `Request failed (HTTP ${status})`);
  }
}

/** Returns the response data or throws an `ApiError` carrying the backend's message, for TanStack Query. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) {
    const body = (error as Partial<Schemas["ErrorResponse"]> | undefined)
      ?.error;
    throw new ApiError(
      response.status,
      body?.code,
      body?.message,
      body?.details as Record<string, unknown> | undefined,
    );
  }
  return data as T;
}
