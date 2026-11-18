import type { Metadata } from "next";

import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = {
  title: "Create an account · Research Assistant",
};

export default async function SignupPage({
  searchParams,
}: PageProps<"/signup">) {
  const { next } = await searchParams;
  return (
    <AuthForm mode="signup" next={typeof next === "string" ? next : null} />
  );
}
