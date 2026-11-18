import Link from "next/link";

import { AppNav } from "@/components/app-nav";
import { SignOutButton } from "@/components/auth/sign-out-button";
import { QueryProvider } from "@/components/query-provider";
import { ThemeToggle } from "@/components/theme-toggle";

/** Frame for signed-in pages (`proxy.ts` guards them). */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <QueryProvider>
      <div className="flex flex-1 flex-col">
        <header className="border-b">
          <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-4">
              <Link
                href="/workspaces"
                className="tap-target hidden font-serif text-lg font-medium sm:inline-flex"
              >
                Research Assistant
              </Link>
              <AppNav />
            </div>
            <div className="flex items-center gap-1">
              <ThemeToggle />
              <SignOutButton />
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
          {children}
        </main>
      </div>
    </QueryProvider>
  );
}
