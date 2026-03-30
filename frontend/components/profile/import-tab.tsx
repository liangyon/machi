"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { toast } from "sonner";
import { ArrowRight, ExternalLink, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import type {
  MALImportResponse,
  MALSyncStatus,
  AniListImportResponse,
  AniListSyncStatus,
} from "@/lib/types";

interface CurrentListStatus {
  source: "mal" | "anilist";
  username: string;
  sync_status: string;
  total_entries: number;
  last_synced_at: string | null;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "Preparing import…",
  in_progress: "Importing your anime list…",
  completed: "Import complete",
  failed: "Import failed",
};

function isActive(status: string) {
  return status === "pending" || status === "in_progress";
}

function normaliseMalStatus(data: MALSyncStatus): CurrentListStatus {
  return {
    source: (data.source as "mal" | "anilist") ?? "mal",
    username: data.mal_username ?? "",
    sync_status: data.sync_status,
    total_entries: data.total_entries,
    last_synced_at: data.last_synced_at ?? null,
  };
}

function normaliseAniListStatus(data: AniListSyncStatus): CurrentListStatus {
  return {
    source: "anilist",
    username: data.anilist_username ?? "",
    sync_status: data.sync_status,
    total_entries: data.total_entries,
    last_synced_at: data.last_synced_at ?? null,
  };
}

interface ImportTabProps {
  onImportComplete: () => void;
}

export function ImportTab({ onImportComplete }: ImportTabProps) {
  const { user } = useAuth();

  const [source, setSource] = useState<"mal" | "anilist">("mal");
  const [username, setUsername] = useState("");
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentList, setCurrentList] = useState<CurrentListStatus | null>(null);
  const [liveStatus, setLiveStatus] = useState<CurrentListStatus | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!user) return;

    fetchAPI<MALSyncStatus>("/api/mal/status")
      .then((data) => {
        if (data.source === "anilist") {
          return fetchAPI<AniListSyncStatus>("/api/anilist/status").then((aniData) => {
            const resolved = normaliseAniListStatus(aniData);
            setCurrentList(resolved);
            setSource("anilist");
            setUsername(resolved.username);
            if (isActive(resolved.sync_status)) {
              setLiveStatus(resolved);
              startPolling("anilist");
            }
          });
        }
        const resolved = normaliseMalStatus(data);
        setCurrentList(resolved);
        setSource("mal");
        setUsername(resolved.username);
        if (isActive(resolved.sync_status)) {
          setLiveStatus(resolved);
          startPolling("mal");
        }
      })
      .catch(() => {
        fetchAPI<AniListSyncStatus>("/api/anilist/status")
          .then((data) => {
            const resolved = normaliseAniListStatus(data);
            setCurrentList(resolved);
            setSource("anilist");
            setUsername(resolved.username);
            if (isActive(resolved.sync_status)) {
              setLiveStatus(resolved);
              startPolling("anilist");
            }
          })
          .catch(() => {});
      });

    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  function startPolling(pollSource: "mal" | "anilist") {
    stopPolling();
    const endpoint = pollSource === "mal" ? "/api/mal/status" : "/api/anilist/status";

    pollRef.current = setInterval(async () => {
      try {
        if (pollSource === "mal") {
          const data = await fetchAPI<MALSyncStatus>(endpoint);
          const resolved = normaliseMalStatus(data);
          setLiveStatus(resolved);
          if (resolved.sync_status === "completed") {
            stopPolling();
            setImporting(false);
            setCurrentList(resolved);
            toast.success(`Import complete! ${resolved.total_entries} anime imported.`);
            onImportComplete();
          } else if (resolved.sync_status === "failed") {
            stopPolling();
            setImporting(false);
            toast.error("Import failed. Please try again.");
          }
        } else {
          const data = await fetchAPI<AniListSyncStatus>(endpoint);
          const resolved = normaliseAniListStatus(data);
          setLiveStatus(resolved);
          if (resolved.sync_status === "completed") {
            stopPolling();
            setImporting(false);
            setCurrentList(resolved);
            toast.success(`Import complete! ${resolved.total_entries} anime imported.`);
            onImportComplete();
          } else if (resolved.sync_status === "failed") {
            stopPolling();
            setImporting(false);
            toast.error("Import failed. Please try again.");
          }
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

  async function handleImport(e: React.FormEvent) {
    e.preventDefault();
    if (!username.trim()) return;

    setError(null);
    setImporting(true);
    setLiveStatus(null);

    try {
      if (source === "mal") {
        const data = await fetchAPI<MALImportResponse>("/api/mal/import", {
          method: "POST",
          body: JSON.stringify({ mal_username: username.trim() }),
        });
        setLiveStatus({
          source: "mal",
          username: data.mal_username,
          sync_status: data.sync_status,
          total_entries: 0,
          last_synced_at: null,
        });
      } else {
        const data = await fetchAPI<AniListImportResponse>("/api/anilist/import", {
          method: "POST",
          body: JSON.stringify({ anilist_username: username.trim() }),
        });
        setLiveStatus({
          source: "anilist",
          username: data.anilist_username,
          sync_status: data.sync_status,
          total_entries: 0,
          last_synced_at: null,
        });
      }

      toast.info("Import started — this may take a minute.");
      startPolling(source);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
      setImporting(false);
    }
  }

  const activeStatus = liveStatus ?? currentList;
  const isImporting = isActive(liveStatus?.sync_status ?? "");
  const isCompleted = (liveStatus ?? currentList)?.sync_status === "completed";

  const showReplaceWarning =
    currentList?.sync_status === "completed" && currentList.source !== source;

  const currentSourceLabel = currentList?.source === "anilist" ? "AniList" : "MyAnimeList";
  const selectedSourceLabel = source === "anilist" ? "AniList" : "MyAnimeList";

  const helpLink =
    source === "mal"
      ? { href: "https://myanimelist.net/editprofile.php", label: "MAL Settings" }
      : { href: "https://anilist.co/settings/lists", label: "AniList Settings" };

  return (
    <div className="mx-auto max-w-md space-y-6">
      <p className="text-sm text-muted-foreground">
        Connect MyAnimeList or AniList to power your recommendations.
      </p>

      {/* Source selector + form */}
      <Card>
        <CardContent className="pt-6 space-y-5">
          {/* Source toggle */}
          <div className="flex gap-2">
            <Button
              type="button"
              variant={source === "mal" ? "default" : "outline"}
              className="flex-1"
              onClick={() => {
                setSource("mal");
                setUsername(currentList?.source === "mal" ? (currentList.username ?? "") : "");
                setError(null);
              }}
              disabled={isImporting}
            >
              MyAnimeList
            </Button>
            <Button
              type="button"
              variant={source === "anilist" ? "default" : "outline"}
              className="flex-1"
              onClick={() => {
                setSource("anilist");
                setUsername(currentList?.source === "anilist" ? (currentList.username ?? "") : "");
                setError(null);
              }}
              disabled={isImporting}
            >
              AniList
            </Button>
          </div>

          {/* Replace warning */}
          {showReplaceWarning && (
            <Alert>
              <TriangleAlert className="h-4 w-4" />
              <AlertDescription>
                Importing from {selectedSourceLabel} will replace your current{" "}
                {currentSourceLabel} list.
              </AlertDescription>
            </Alert>
          )}

          {/* Username input + submit */}
          <form onSubmit={handleImport} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="import-username">
                {source === "mal" ? "MAL" : "AniList"} Username
              </Label>
              <Input
                id="import-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={source === "mal" ? "e.g. Zephyrot" : "e.g. Username"}
                disabled={isImporting}
              />
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={importing || isImporting || !username.trim()}
            >
              {isImporting ? "Importing…" : isCompleted ? "Re-import List" : "Import List"}
            </Button>
          </form>

          {/* Error */}
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Public-list help */}
          <p className="text-xs text-muted-foreground">
            Your list must be public.{" "}
            <a
              href={helpLink.href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 underline hover:text-foreground"
            >
              {helpLink.label}
              <ExternalLink className="h-3 w-3" />
            </a>
          </p>
        </CardContent>
      </Card>

      {/* Current list / live status */}
      {activeStatus && (
        <Card>
          <CardContent className="pt-5 space-y-3">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2.5 w-2.5 rounded-full ${
                  activeStatus.sync_status === "failed" ? "bg-destructive" : "bg-primary"
                } ${isActive(activeStatus.sync_status) ? "animate-pulse" : ""}`}
              />
              <span className="text-sm font-medium">
                {STATUS_LABELS[activeStatus.sync_status] ?? activeStatus.sync_status}
              </span>
            </div>

            <div className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Source</p>
                <p className="font-medium">
                  {activeStatus.source === "anilist" ? "AniList" : "MyAnimeList"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Username</p>
                <p className="font-medium truncate">{activeStatus.username || "—"}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Entries</p>
                <p className="font-medium">{activeStatus.total_entries}</p>
              </div>
            </div>

            {activeStatus.sync_status === "completed" &&
              !isActive(liveStatus?.sync_status ?? "") && (
                <Button size="sm" className="w-full" onClick={onImportComplete}>
                  View Overview
                  <ArrowRight className="ml-2 h-3.5 w-3.5" />
                </Button>
              )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
