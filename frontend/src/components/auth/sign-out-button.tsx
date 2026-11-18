"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { supabase } from "@/lib/supabase/client";

/** Ends the session and returns to the landing page. */
export function SignOutButton() {
  const router = useRouter();
  return (
    <Button
      variant="outline"
      className="h-10 px-4"
      onClick={async () => {
        await supabase().auth.signOut();
        router.replace("/");
        router.refresh();
      }}
    >
      Sign out
    </Button>
  );
}
