import { createBrowserClient } from "@supabase/ssr";

export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";

/** Browser Supabase client; the session lives in cookies so `proxy.ts` can read it. Singleton in the browser. */
export function supabase() {
  return createBrowserClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
}

/** Only same-site paths, so `?next=` can never redirect off the app. */
export function safeNext(next: string | null, fallback = "/workspaces") {
  return next?.startsWith("/") && !next.startsWith("//") ? next : fallback;
}
