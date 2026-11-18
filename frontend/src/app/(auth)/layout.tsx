import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

/** Shared frame for the sign-in and sign-up pages. */
export default function AuthLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex flex-1 flex-col">
      <header className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="tap-target font-serif text-lg font-medium">
          Research Assistant
        </Link>
        <ThemeToggle />
      </header>
      <main className="mx-auto w-full max-w-sm flex-1 px-4 pt-12 pb-24 sm:pt-20">
        {children}
      </main>
    </div>
  );
}
