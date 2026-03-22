"use client";

/**
 * Recommendations Page — /recommendations
 *
 * History log of all past recommendation sessions.
 * Browse, review, and give feedback on previously generated picks.
 * To generate new recommendations, go to /discover.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { toast } from "sonner";
import {
  AlertTriangle,
  Clock,
  Compass,
  LayoutList,
  Layers,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { RecommendationCard } from "@/components/recommendations/recommendation-card";
import { SwipeCardDeck } from "@/components/recommendations/swipe-card";
import {
  HistorySidebar,
  MobileHistoryPanel,
} from "@/components/recommendations/history-sidebar";
import type {
  RecommendationResponse,
  FeedbackMapResponse,
  HistoryResponse,
  SessionSummary,
  RecommendationItem,
} from "@/lib/types";

export default function RecommendationsPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, string>>({});
  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [watchlistIds, setWatchlistIds] = useState<Set<number>>(new Set());
  const [viewMode, setViewMode] = useState<"list" | "cards">("cards");

  // ── Fetch most recent session + feedback + history + watchlist ──
  useEffect(() => {
    if (!user) return;

    Promise.all([
      fetchAPI<RecommendationResponse>("/api/recommendations").catch(() => null),
      fetchAPI<FeedbackMapResponse>("/api/recommendations/feedback").catch(() => ({ feedback: {} })),
      fetchAPI<HistoryResponse>("/api/recommendations/history").catch(() => ({ sessions: [], total: 0 })),
      fetchAPI<{ items: { mal_id: number }[] }>("/api/watchlist").catch(() => ({ items: [] })),
    ]).then(([recs, feedback, hist, watchlist]) => {
      if (recs) setData(recs);
      if (feedback) setFeedbackGiven(feedback.feedback);
      if (hist) setHistory(hist.sessions);
      if (watchlist) setWatchlistIds(new Set(watchlist.items.map((i) => i.mal_id)));
      setLoading(false);
    });
  }, [user]);

  // ── Load a specific past session ──────────────────
  const handleLoadSession = async (sessionId: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchAPI<RecommendationResponse>(`/api/recommendations/${sessionId}`);
      setData(result);
      setActiveSessionId(sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session");
    } finally {
      setLoading(false);
    }
  };

  // ── Submit feedback ───────────────────────────────
  const handleFeedback = async (malId: number, feedback: string) => {
    try {
      await fetchAPI("/api/recommendations/feedback", {
        method: "POST",
        body: JSON.stringify({ mal_id: malId, feedback }),
      });
      setFeedbackGiven((prev) => ({ ...prev, [malId]: feedback }));
      const labels: Record<string, string> = {
        liked: "Marked as interested",
        disliked: "Marked as not for you",
        watched: "Marked as watched",
      };
      toast.success(labels[feedback] || "Feedback saved");
    } catch {
      toast.error("Failed to save feedback");
    }
  };

  // ── Toggle watchlist ──────────────────────────────
  const handleToggleWatchlist = async (rec: RecommendationItem) => {
    const isOn = watchlistIds.has(rec.mal_id);
    try {
      if (isOn) {
        await fetchAPI(`/api/watchlist/${rec.mal_id}`, { method: "DELETE" });
        setWatchlistIds((prev) => {
          const next = new Set(prev);
          next.delete(rec.mal_id);
          return next;
        });
        toast.success(`Removed "${rec.title}" from watchlist`);
      } else {
        await fetchAPI("/api/watchlist", {
          method: "POST",
          body: JSON.stringify({
            mal_id: rec.mal_id,
            title: rec.title,
            image_url: rec.image_url,
            genres: rec.genres,
            themes: rec.themes,
            mal_score: rec.mal_score,
            year: rec.year,
            anime_type: rec.anime_type,
            source: "recommendation",
          }),
        });
        setWatchlistIds((prev) => new Set(prev).add(rec.mal_id));
        toast.success(`Added "${rec.title}" to watchlist`);
      }
    } catch {
      toast.error("Failed to update watchlist");
    }
  };

  // ── Loading state ─────────────────────────────────
  if (loading) {
    return (
      <div className="px-4 py-8">
        <div className="mx-auto max-w-7xl space-y-8">
          <div className="flex items-center justify-between">
            <div>
              <Skeleton className="h-8 w-48" />
              <Skeleton className="mt-2 h-4 w-72" />
            </div>
          </div>
          <div className="grid gap-6 md:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-56 rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────
  return (
    <div className="px-4 py-8">
      <div className="mx-auto max-w-7xl">
        <div className="flex gap-6">
          {/* History Sidebar (desktop) */}
          {history.length > 0 && (
            <div className="hidden lg:block">
              <HistorySidebar
                sessions={history}
                activeSessionId={activeSessionId}
                onSelectSession={handleLoadSession}
              />
            </div>
          )}

          {/* Main Content */}
          <div className="flex-1 space-y-8">
            {/* Header */}
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h1 className="text-3xl font-bold tracking-tight">Recommendations</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  Your history of AI-generated picks
                </p>
              </div>

              <div className="flex gap-2">
                {history.length > 0 && (
                  <Button
                    variant="outline"
                    onClick={() => setShowHistory(!showHistory)}
                    className="lg:hidden"
                  >
                    <Clock className="mr-2 h-4 w-4" />
                    History
                  </Button>
                )}
                {/* View mode toggle */}
                {data && (
                  <div className="flex gap-1 rounded-lg border p-1">
                    <Button
                      variant={viewMode === "list" ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => setViewMode("list")}
                      aria-label="List view"
                    >
                      <LayoutList className="h-4 w-4" />
                    </Button>
                    <Button
                      variant={viewMode === "cards" ? "secondary" : "ghost"}
                      size="sm"
                      onClick={() => setViewMode("cards")}
                      aria-label="Card swipe view"
                    >
                      <Layers className="h-4 w-4" />
                    </Button>
                  </div>
                )}
                <Button onClick={() => router.push("/discover")}>
                  <Sparkles className="mr-2 h-4 w-4" />
                  New Session
                </Button>
              </div>
            </div>

            {/* Mobile history panel */}
            {showHistory && history.length > 0 && (
              <div className="lg:hidden">
                <MobileHistoryPanel
                  sessions={history}
                  activeSessionId={activeSessionId}
                  onSelectSession={(id) => {
                    handleLoadSession(id);
                    setShowHistory(false);
                  }}
                />
              </div>
            )}

            {/* Error */}
            {error && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {/* Fallback notice */}
            {data?.used_fallback && (
              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>
                  AI reasoning was unavailable for some recommendations. Showing best matches from
                  your taste profile.
                </AlertDescription>
              </Alert>
            )}

            {/* Empty state */}
            {!data && (
              <Card className="py-20">
                <CardContent className="flex flex-col items-center justify-center text-center">
                  <Compass className="h-16 w-16 text-muted-foreground/50" />
                  <h2 className="mt-4 text-xl font-semibold">No recommendations yet</h2>
                  <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    Head to Discover to generate your first set of picks.
                  </p>
                  <Button className="mt-6" onClick={() => router.push("/discover")}>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Go to Discover
                  </Button>
                </CardContent>
              </Card>
            )}

            {/* Session results */}
            {data && (
              <div className="space-y-6">
                <p className="text-sm text-muted-foreground">
                  {data.total} recommendations ·{" "}
                  {new Date(data.generated_at).toLocaleString()}
                  {data.custom_query && (
                    <Badge variant="secondary" className="ml-2">
                      Query: {data.custom_query}
                    </Badge>
                  )}
                </p>

                {viewMode === "list" ? (
                  <div className="grid gap-6 md:grid-cols-2">
                    {data.recommendations.map((rec, index) => (
                      <RecommendationCard
                        key={rec.mal_id}
                        rec={rec}
                        index={index}
                        feedback={feedbackGiven[rec.mal_id]}
                        onFeedback={handleFeedback}
                        isOnWatchlist={watchlistIds.has(rec.mal_id)}
                        onToggleWatchlist={handleToggleWatchlist}
                      />
                    ))}
                  </div>
                ) : (
                  <SwipeCardDeck
                    recommendations={data.recommendations}
                    feedbackGiven={feedbackGiven}
                    watchlistIds={watchlistIds}
                    onFeedback={handleFeedback}
                    onToggleWatchlist={handleToggleWatchlist}
                  />
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
