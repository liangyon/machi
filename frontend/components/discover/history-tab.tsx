"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
  HistoryResponse,
  SessionSummary,
  RecommendationItem,
} from "@/lib/types";

interface HistoryTabProps {
  watchlistIds: Set<number>;
  feedbackGiven: Record<number, string>;
  onFeedback: (malId: number, feedback: string) => Promise<void>;
  onToggleWatchlist: (rec: RecommendationItem) => Promise<void>;
  onSetWatchlistIds: (ids: Set<number>) => void;
}

export function HistoryTab({
  watchlistIds,
  feedbackGiven,
  onFeedback,
  onToggleWatchlist,
  onSetWatchlistIds,
}: HistoryTabProps) {
  const router = useRouter();

  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [viewMode, setViewMode] = useState<"list" | "cards">("cards");

  useEffect(() => {
    Promise.all([
      fetchAPI<RecommendationResponse>("/api/recommendations").catch(() => null),
      fetchAPI<HistoryResponse>("/api/recommendations/history").catch(() => ({ sessions: [], total: 0 })),
      fetchAPI<{ items: { mal_id: number }[] }>("/api/watchlist").catch(() => ({ items: [] })),
    ]).then(([recs, hist, watchlist]) => {
      if (recs) setData(recs);
      if (hist) setHistory(hist.sessions);
      if (watchlist) onSetWatchlistIds(new Set(watchlist.items.map((i) => i.mal_id)));
      setLoading(false);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  if (loading) {
    return (
      <div className="space-y-8">
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
    );
  }

  return (
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
      <div className="flex-1 space-y-6">
        {/* Sub-header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            Your history of AI-generated picks.
          </p>

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
                Generate your first set of picks in the For You or Brew tab.
              </p>
              <Button className="mt-6" onClick={() => router.push("/discover")}>
                <Sparkles className="mr-2 h-4 w-4" />
                Generate Recommendations
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
                    onFeedback={onFeedback}
                    isOnWatchlist={watchlistIds.has(rec.mal_id)}
                    onToggleWatchlist={onToggleWatchlist}
                  />
                ))}
              </div>
            ) : (
              <SwipeCardDeck
                recommendations={data.recommendations}
                feedbackGiven={feedbackGiven}
                watchlistIds={watchlistIds}
                onFeedback={onFeedback}
                onToggleWatchlist={onToggleWatchlist}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
