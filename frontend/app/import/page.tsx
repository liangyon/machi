"use client";

/**
 * MAL Import Page — /import
 *
 * Lets users enter their MyAnimeList username and kick off an import.
 * Uses polling to track import progress (every 2s while in_progress).
 *
 * Why polling instead of WebSockets?
 * ──────────────────────────────────
 * The import takes 30s–5min depending on list size.  Polling every 2s
 * is perfectly fine for that timescale and much simpler to implement.
 * We can upgrade to WebSockets or SSE later if we want real-time
 * progress bars.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";

// ── Types matching our backend schemas ──────────────

interface MALImportResponse {
  anime_list_id: string;
  mal_username: string;
  sync_status: string;
  message: string;
}

interface MALSyncStatus {
  anime_list_id: string;
  mal_username: string;
  sync_status: string; // pending | in_progress | completed | failed
  total_entries: number;
  last_synced_at: string | null;
}

// ── Status display helpers ──────────────────────────

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; pulse: boolean }
> = {
  pending: {
    label: "Preparing import…",
    color: "bg-yellow-500",
    pulse: true,
  },
  in_progress: {
    label: "Importing your anime list…",
    color: "bg-blue-500",
    pulse: true,
  },
  completed: {
    label: "Import complete!",
    color: "bg-emerald-500",
    pulse: false,
  },
  failed: {
    label: "Import failed. Please try again.",
    color: "bg-red-500",
    pulse: false,
  },
};

export default function ImportPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  const [malUsername, setMalUsername] = useState("");
  const [importing, setImporting] = useState(false);
  const [status, setStatus] = useState<MALSyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Polling interval ref so we can clean it up
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Redirect if not logged in ─────────────────────
  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
    }
  }, [authLoading, user, router]);

  // ── Check for existing import on mount ────────────
  useEffect(() => {
    if (!user) return;

    fetchAPI<MALSyncStatus>("/api/mal/status")
      .then((data) => {
        setStatus(data);
        setMalUsername(data.mal_username);
        // If there's an active import, start polling
        if (data.sync_status === "pending" || data.sync_status === "in_progress") {
          startPolling();
        }
      })
      .catch(() => {
        // 404 = no list yet, that's fine
      });

    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // ── Polling logic ─────────────────────────────────

  function startPolling() {
    stopPolling(); // clear any existing interval
    pollRef.current = setInterval(async () => {
      try {
        const data = await fetchAPI<MALSyncStatus>("/api/mal/status");
        setStatus(data);

        if (data.sync_status === "completed" || data.sync_status === "failed") {
          stopPolling();
          setImporting(false);
        }
      } catch {
        // If polling fails, stop and show error
        stopPolling();
        setImporting(false);
      }
    }, 2000);
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  // ── Import handler ────────────────────────────────

  async function handleImport(e: React.FormEvent) {
    e.preventDefault();
    if (!malUsername.trim()) return;

    setError(null);
    setImporting(true);

    try {
      const data = await fetchAPI<MALImportResponse>("/api/mal/import", {
        method: "POST",
        body: JSON.stringify({ mal_username: malUsername.trim() }),
      });

      setStatus({
        anime_list_id: data.anime_list_id,
        mal_username: data.mal_username,
        sync_status: data.sync_status,
        total_entries: 0,
        last_synced_at: null,
      });

      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setImporting(false);
    }
  }

  // ── Render ────────────────────────────────────────

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <div className="animate-pulse text-zinc-500">Loading…</div>
      </div>
    );
  }

  if (!user) return null; // will redirect

  const statusConfig = status ? STATUS_CONFIG[status.sync_status] : null;
  const isActive =
    status?.sync_status === "pending" || status?.sync_status === "in_progress";
  const isCompleted = status?.sync_status === "completed";

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 px-4 font-sans dark:bg-zinc-950">
      <main className="w-full max-w-md space-y-8">
        {/* Header */}
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
            Import Your MAL List
          </h1>
          <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
            Enter your MyAnimeList username and we&apos;ll analyze your anime
            preferences to generate personalized recommendations.
          </p>
        </div>

        {/* Import Form */}
        <form onSubmit={handleImport} className="space-y-4">
          <div>
            <label
              htmlFor="mal-username"
              className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
            >
              MAL Username
            </label>
            <input
              id="mal-username"
              type="text"
              value={malUsername}
              onChange={(e) => setMalUsername(e.target.value)}
              placeholder="e.g. Zephyrot"
              disabled={isActive}
              className="mt-1 block w-full rounded-lg border border-zinc-300 bg-white px-4 py-2.5 text-sm text-zinc-900 placeholder-zinc-400 shadow-sm transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-500"
            />
          </div>

          <button
            type="submit"
            disabled={importing || isActive || !malUsername.trim()}
            className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isActive
              ? "Importing…"
              : isCompleted
                ? "Re-import List"
                : "Import List"}
          </button>
        </form>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Status Card */}
        {status && statusConfig && (
          <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            {/* Status indicator */}
            <div className="flex items-center gap-3">
              <span
                className={`inline-block h-3 w-3 rounded-full ${statusConfig.color} ${
                  statusConfig.pulse ? "animate-pulse" : ""
                }`}
              />
              <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                {statusConfig.label}
              </span>
            </div>

            {/* Stats */}
            <div className="mt-4 grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  MAL User
                </p>
                <p className="mt-0.5 text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {status.mal_username}
                </p>
              </div>
              <div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Entries Found
                </p>
                <p className="mt-0.5 text-sm font-medium text-zinc-900 dark:text-zinc-100">
                  {status.total_entries}
                </p>
              </div>
            </div>

            {/* Action buttons when completed */}
            {isCompleted && (
              <div className="mt-6 flex gap-3">
                <button
                  onClick={() => router.push("/dashboard")}
                  className="flex-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700"
                >
                  View Dashboard →
                </button>
              </div>
            )}
          </div>
        )}

        {/* Help text */}
        <p className="text-center text-xs text-zinc-400 dark:text-zinc-500">
          Your MAL list must be set to public for the import to work.
          <br />
          Go to{" "}
          <a
            href="https://myanimelist.net/editprofile.php"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-zinc-600 dark:hover:text-zinc-300"
          >
            MAL Settings
          </a>{" "}
          → List → make sure &quot;Public&quot; is checked.
        </p>
      </main>
    </div>
  );
}
