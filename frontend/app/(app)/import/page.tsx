"use client";

/**
 * MAL Import Page — /import
 *
 * Lets users enter their MyAnimeList username and kick off an import.
 * Uses polling to track import progress (every 2s while in_progress).
 *
 * Phase 4: shadcn components, Lucide icons, toast notifications.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { toast } from "sonner";
import { ArrowRight, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";

import type { MALImportResponse, MALSyncStatus } from "@/lib/types";

// ── Status display helpers ──────────────────────────

const STATUS_CONFIG: Record<
  string,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline"; pulse: boolean }
> = {
  pending: {
    label: "Preparing import…",
    variant: "secondary",
    pulse: true,
  },
  in_progress: {
    label: "Importing your anime list…",
    variant: "default",
    pulse: true,
  },
  completed: {
    label: "Import complete!",
    variant: "default",
    pulse: false,
  },
  failed: {
    label: "Import failed. Please try again.",
    variant: "destructive",
    pulse: false,
  },
};

export default function ImportPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [malUsername, setMalUsername] = useState("");
  const [importing, setImporting] = useState(false);
  const [status, setStatus] = useState<MALSyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Check for existing import on mount ────────────
  useEffect(() => {
    if (!user) return;

    fetchAPI<MALSyncStatus>("/api/mal/status")
      .then((data) => {
        setStatus(data);
        setMalUsername(data.mal_username);
        if (
          data.sync_status === "pending" ||
          data.sync_status === "in_progress"
        ) {
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
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const data = await fetchAPI<MALSyncStatus>("/api/mal/status");
        setStatus(data);

        if (data.sync_status === "completed") {
          stopPolling();
          setImporting(false);
          toast.success(
            `Import complete! ${data.total_entries} anime entries imported.`
          );
        } else if (data.sync_status === "failed") {
          stopPolling();
          setImporting(false);
          toast.error("Import failed. Please try again.");
        }
      } catch {
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

      toast.info("Import started — this may take a minute.");
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setImporting(false);
    }
  }

  // ── Render ────────────────────────────────────────

  const statusConfig = status ? STATUS_CONFIG[status.sync_status] : null;
  const isActive =
    status?.sync_status === "pending" || status?.sync_status === "in_progress";
  const isCompleted = status?.sync_status === "completed";

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-8">
      <div className="w-full max-w-md space-y-8">
        {/* Header */}
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight">
            Import Your MAL List
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Enter your MyAnimeList username and we&apos;ll analyze your anime
            preferences to generate personalized recommendations.
          </p>
        </div>

        {/* Import Form */}
        <Card>
          <CardContent className="pt-6">
            <form onSubmit={handleImport} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="mal-username">MAL Username</Label>
                <Input
                  id="mal-username"
                  type="text"
                  value={malUsername}
                  onChange={(e) => setMalUsername(e.target.value)}
                  placeholder="e.g. Zephyrot"
                  disabled={isActive}
                />
              </div>

              <Button
                type="submit"
                className="w-full"
                disabled={importing || isActive || !malUsername.trim()}
              >
                {isActive
                  ? "Importing…"
                  : isCompleted
                    ? "Re-import List"
                    : "Import List"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Error */}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Status Card */}
        {status && statusConfig && (
          <Card>
            <CardContent className="pt-6">
              {/* Status indicator */}
              <div className="flex items-center gap-3">
                <span
                  className={`inline-block h-3 w-3 rounded-full ${
                    statusConfig.variant === "destructive"
                      ? "bg-destructive"
                      : statusConfig.variant === "default"
                        ? "bg-primary"
                        : "bg-muted-foreground"
                  } ${statusConfig.pulse ? "animate-pulse" : ""}`}
                />
                <span className="text-sm font-medium">
                  {statusConfig.label}
                </span>
              </div>

              {/* Stats */}
              <div className="mt-4 grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">MAL User</p>
                  <p className="mt-0.5 text-sm font-medium">
                    {status.mal_username}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">
                    Entries Found
                  </p>
                  <p className="mt-0.5 text-sm font-medium">
                    {status.total_entries}
                  </p>
                </div>
              </div>

              {/* Action buttons when completed */}
              {isCompleted && (
                <div className="mt-6 flex gap-3">
                  <Button
                    className="flex-1"
                    onClick={() => router.push("/dashboard")}
                  >
                    View Dashboard
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Help text */}
        <p className="text-center text-xs text-muted-foreground">
          Your MAL list must be set to public for the import to work.
          <br />
          Go to{" "}
          <a
            href="https://myanimelist.net/editprofile.php"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 underline hover:text-foreground"
          >
            MAL Settings
            <ExternalLink className="h-3 w-3" />
          </a>{" "}
          &rarr; List &rarr; make sure &quot;Public&quot; is checked.
        </p>
      </div>
    </div>
  );
}
