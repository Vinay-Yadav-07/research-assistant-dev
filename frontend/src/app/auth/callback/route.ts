import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

import {
  safeNext,
  SUPABASE_PUBLISHABLE_KEY,
  SUPABASE_URL,
} from "@/lib/supabase/client";

/** Target of the sign-up confirmation email: trades the one-time code for a session cookie. */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  if (code) {
    const store = await cookies();
    const supabase = createServerClient(
      SUPABASE_URL,
      SUPABASE_PUBLISHABLE_KEY,
      {
        cookies: {
          getAll: () => store.getAll(),
          setAll: (cookiesToSet) => {
            for (const { name, value, options } of cookiesToSet)
              store.set(name, value, options);
          },
        },
      },
    );
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error)
      return NextResponse.redirect(
        new URL(safeNext(searchParams.get("next")), origin),
      );
  }
  return NextResponse.redirect(new URL("/login?error=confirm", origin));
}
