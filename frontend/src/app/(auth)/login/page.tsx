import type { Metadata } from "next";

import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = { title: "Sign in · Research Assistant" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next, error } = await searchParams;
  return (
    <AuthForm
      mode="login"
      next={typeof next === "string" ? next : null}
      notice={
        error === "confirm"
          ? "That confirmation link is invalid or has expired. Sign in, or sign up again for a new link."
          : undefined
      }
    />
  );
}
