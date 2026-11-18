"use client";

import type { AuthError } from "@supabase/supabase-js";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { safeNext, supabase } from "@/lib/supabase/client";

type Mode = "login" | "signup";

const COPY = {
  login: {
    title: "Sign in",
    submit: "Sign in",
    busy: "Signing in…",
    switchText: "No account yet?",
    switchLabel: "Create one",
    switchHref: "/signup",
  },
  signup: {
    title: "Create an account",
    submit: "Create account",
    busy: "Creating account…",
    switchText: "Already have an account?",
    switchLabel: "Sign in",
    switchHref: "/login",
  },
} as const;

/** Turns Supabase auth error codes into sentences a person can act on. */
function errorMessage(error: AuthError): string {
  switch (error.code) {
    case "invalid_credentials":
      return "That email and password don't match an account.";
    case "email_not_confirmed":
      return "Confirm your email first. The link is in your inbox.";
    case "signup_disabled":
    case "email_provider_disabled":
      return "Sign-up is closed. Ask the team for an account.";
    case "user_already_exists":
      return "An account with this email already exists. Sign in instead.";
    case "weak_password":
      return "Choose a longer password (at least 6 characters).";
    case "over_request_rate_limit":
    case "over_email_send_rate_limit":
      return "Too many attempts. Wait a minute and try again.";
    default:
      return error.message || "Something went wrong. Try again.";
  }
}

const inputClass =
  "h-10 w-full rounded-md border border-input bg-muted px-3 text-base text-foreground placeholder:text-muted-foreground aria-invalid:border-destructive";

/** Email and password form for `/login` and `/signup`; `next` is where to go once signed in. */
export function AuthForm({
  mode,
  next,
  notice,
}: {
  mode: Mode;
  next: string | null;
  notice?: string;
}) {
  const router = useRouter();
  const copy = COPY[mode];
  const destination = safeNext(next);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email"));
    const password = String(form.get("password"));
    setBusy(true);
    setError(null);
    const auth = supabase().auth;
    const result =
      mode === "login"
        ? await auth.signInWithPassword({ email, password })
        : await auth.signUp({
            email,
            password,
            options: {
              emailRedirectTo: `${location.origin}/auth/callback?next=${encodeURIComponent(destination)}`,
            },
          });
    if (result.error) {
      setError(errorMessage(result.error));
      setBusy(false);
      return;
    }
    // Sign-up without a session means the project requires email confirmation.
    if (!result.data.session) {
      setSentTo(email);
      setBusy(false);
      return;
    }
    router.replace(destination);
    router.refresh();
  }

  if (sentTo)
    return (
      <div role="status">
        <h1 className="text-3xl font-medium">Check your email</h1>
        <p className="mt-4 leading-relaxed text-muted-foreground">
          We sent a confirmation link to{" "}
          <span className="break-all text-foreground">{sentTo}</span>. Open it
          on this device to finish creating your account.
        </p>
        <Link
          href="/login"
          className="link-draw tap-target mt-6 inline-block text-sm"
        >
          Back to sign in
        </Link>
      </div>
    );

  return (
    <div>
      <h1 className="text-3xl font-medium">{copy.title}</h1>
      {notice && (
        <p role="status" className="mt-4 text-sm text-muted-foreground">
          {notice}
        </p>
      )}
      <form onSubmit={onSubmit} className="mt-8 space-y-5">
        <div className="space-y-1.5">
          <label htmlFor="email" className="text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "auth-error" : undefined}
            className={inputClass}
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="password" className="text-sm font-medium">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete={
              mode === "login" ? "current-password" : "new-password"
            }
            minLength={mode === "signup" ? 6 : undefined}
            required
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "auth-error" : undefined}
            className={inputClass}
          />
        </div>
        <p
          id="auth-error"
          role="alert"
          className="min-h-5 text-sm text-destructive"
        >
          {error}
        </p>
        <Button type="submit" disabled={busy} className="h-10 w-full">
          {busy ? copy.busy : copy.submit}
        </Button>
      </form>
      <p className="mt-6 text-sm text-muted-foreground">
        {copy.switchText}{" "}
        <Link
          href={
            next
              ? `${copy.switchHref}?next=${encodeURIComponent(next)}`
              : copy.switchHref
          }
          className="link-draw tap-target text-foreground"
        >
          {copy.switchLabel}
        </Link>
      </p>
    </div>
  );
}
