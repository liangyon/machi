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

interface MALSyncStatus {
  sync_status: string;
  total_entries: number;
  mal_username: string;
}

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
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 px-4 font-sans dark:bg-zinc-950">
      <main className="flex flex-col items-center gap-8 text-center">
        <h1 className="text-5xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          Machi
        </h1>
        <p className="max-w-md text-base leading-relaxed text-zinc-500 dark:text-zinc-400">
          AI-powered anime recommendations that actually understand your taste.
          Import your MyAnimeList profile and get personalized suggestions with
          real reasoning.
        </p>

        {loading ? (
          <div className="animate-pulse text-sm text-zinc-400">Loading…</div>
        ) : user ? (
          /* ── Logged in ─────────────────────────────── */
          <div className="flex flex-col items-center gap-4">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Welcome back,{" "}
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                {user.name || user.email}
              </span>
            </p>

            <div className="flex gap-3">
              {malStatus?.sync_status === "completed" ? (
                <>
                  <button
                    onClick={() => router.push("/dashboard")}
                    className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
                  >
                    View Dashboard
                  </button>
                  <button
                    onClick={() => router.push("/import")}
                    className="rounded-lg border border-zinc-300 px-6 py-2.5 text-sm font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  >
                    Re-import
                  </button>
                </>
              ) : (
                <button
                  onClick={() => router.push("/import")}
                  className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
                >
                  Import MAL List →
                </button>
              )}
            </div>

            <button
              onClick={logout}
              className="text-xs text-zinc-400 underline hover:text-zinc-600 dark:hover:text-zinc-300"
            >
              Sign out
            </button>
          </div>
        ) : (
          /* ── Logged out ────────────────────────────── */
          <div className="flex gap-3">
            <button
              onClick={() => router.push("/login")}
              className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
            >
              Sign In
            </button>
            <button
              onClick={() => router.push("/register")}
              className="rounded-lg border border-zinc-300 px-6 py-2.5 text-sm font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              Create Account
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
