"use client";

/**
 * Home Page — /
 *
 * Landing page that shows different content based on auth state:
 * - Logged out: welcome message + login/register CTAs
 * - Logged in, no import: prompt to import MAL list
 * - Logged in, imported: quick link to dashboard
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { ArrowRight, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { MALSyncStatus } from "@/lib/types";

export default function Home() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [malStatus, setMalStatus] = useState<MALSyncStatus | null>(null);

  useEffect(() => {
    if (!user) return;
    fetchAPI<MALSyncStatus>("/api/mal/status")
      .then(setMalStatus)
      .catch(() => setMalStatus(null));
  }, [user]);

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <main className="flex flex-col items-center gap-8 text-center">
        <h1 className="text-5xl font-bold tracking-tight">Machi</h1>
        <p className="max-w-md text-base leading-relaxed text-muted-foreground">
          AI-powered anime recommendations that actually understand your taste.
          Import your MyAnimeList profile and get personalized suggestions with
          real reasoning.
        </p>

        {loading ? (
          <div className="flex flex-col items-center gap-3">
            <Skeleton className="h-10 w-32" />
          </div>
        ) : user ? (
          /* ── Logged in ─────────────────────────────── */
          <div className="flex flex-col items-center gap-4">
            <p className="text-sm text-muted-foreground">
              Welcome back,{" "}
              <span className="font-medium text-foreground">
                {user.name || user.email}
              </span>
            </p>

            <div className="flex gap-3">
              {malStatus?.sync_status === "completed" ? (
                <>
                  <Button onClick={() => router.push("/dashboard")}>
                    View Dashboard
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => router.push("/import")}
                  >
                    Re-import
                  </Button>
                </>
              ) : (
                <Button onClick={() => router.push("/import")}>
                  Import MAL List
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              )}
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={logout}
              className="text-muted-foreground"
            >
              <LogOut className="mr-1.5 h-3.5 w-3.5" />
              Sign out
            </Button>
          </div>
        ) : (
          /* ── Logged out ────────────────────────────── */
          <div className="flex gap-3">
            <Button onClick={() => router.push("/login")}>Sign In</Button>
            <Button variant="outline" onClick={() => router.push("/register")}>
              Create Account
            </Button>
          </div>
        )}
      </main>
    </div>
  );
}
