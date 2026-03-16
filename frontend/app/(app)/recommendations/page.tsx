"use client";

/**
 * Recommendations Page — /recommendations
 *
 * AI-powered anime picks based on the user's taste profile.
 * Components extracted to @/components/recommendations/.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { toast } from "sonner";
import {
  AlertTriangle,
  Compass,
  Sparkles,
  RefreshCw,
  LayoutDashboard,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { RecommendationCard } from "@/components/recommendations/recommendation-card";
import {
  HistorySidebar,
  MobileHistoryPanel,
} from "@/components/recommendations/history-sidebar";
import type {
  RecommendationResponse,
  RecommendationGenerateAccepted,
  RecommendationJobStatus,
  FeedbackMapResponse,
  HistoryResponse,
  SessionSummary,
} from "@/lib/types";

export default function RecommendationsPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, string>>(
    {}
  );

  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [generationProgress, setGenerationProgress] = useState(0);
  const [generationStage, setGenerationStage] = useState<string>("queued");

  const [watchlistIds, setWatchlistIds] = useState<Set<number>>(new Set());

  const hasFeedback = Object.keys(feedbackGiven).length > 0;

  const stageLabel = (stage: string) => {
    const labels: Record<string, string> = {
      queued: "Queued",
      validating: "Validating request",
      loading_profile: "Loading your profile",
      retrieving_candidates: "Finding candidate anime",
      generating_recommendations: "Generating AI recommendations",
      persisting: "Saving recommendations",
      completed: "Completed",
      failed: "Failed",
    };
    return labels[stage] ?? stage;
  };

  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  // ── Fetch cached recommendations + feedback + history + watchlist ──
  useEffect(() => {
    if (!user) return;

    Promise.all([
      fetchAPI<RecommendationResponse>("/api/recommendations").catch(
        () => null
      ),
      fetchAPI<FeedbackMapResponse>("/api/recommendations/feedback").catch(
        () => ({ feedback: {} })
      ),
      fetchAPI<HistoryResponse>("/api/recommendations/history").catch(() => ({
        sessions: [],
        total: 0,
      })),
      fetchAPI<{ items: { mal_id: number }[] }>("/api/watchlist").catch(
        () => ({ items: [] })
      ),
    ]).then(([recs, feedback, hist, watchlist]) => {
      if (recs) setData(recs);
      if (feedback) setFeedbackGiven(feedback.feedback);
      if (hist) setHistory(hist.sessions);
      if (watchlist)
        setWatchlistIds(new Set(watchlist.items.map((i) => i.mal_id)));
      setLoading(false);
    });
  }, [user]);

  // ── Generate new recommendations ──────────────────
  const handleGenerate = async (customQuery?: string) => {
    setGenerating(true);
    setError(null);
    setGenerationProgress(0);
    setGenerationStage("queued");

    try {
      const body: Record<string, unknown> = {};
      if (customQuery) body.custom_query = customQuery;

      const accepted = await fetchAPI<RecommendationGenerateAccepted>(
        "/api/recommendations/generate",
        { method: "POST", body: JSON.stringify(body) }
      );

      setGenerationProgress(accepted.progress);
      setGenerationStage(accepted.stage);

      let finalStatus: RecommendationJobStatus | null = null;
      for (let i = 0; i < 180; i += 1) {
        await sleep(1000);
        const status = await fetchAPI<RecommendationJobStatus>(
          `/api/recommendations/status/${accepted.job_id}`
        );

        setGenerationProgress(status.progress);
        setGenerationStage(status.stage);

        if (status.status === "succeeded" || status.status === "failed") {
          finalStatus = status;
          break;
        }
      }

      if (!finalStatus) {
        throw new Error("Recommendation generation timed out. Please try again.");
      }

      if (finalStatus.status === "failed") {
        throw new Error(finalStatus.error || "Failed to generate recommendations");
      }

      const result = finalStatus.session_id
        ? await fetchAPI<RecommendationResponse>(
            `/api/recommendations/${finalStatus.session_id}`
          )
        : await fetchAPI<RecommendationResponse>("/api/recommendations");

      setData(result);
      setActiveSessionId(null);
      toast.success("Recommendations generated successfully");

      fetchAPI<HistoryResponse>("/api/recommendations/history")
        .then((hist) => setHistory(hist.sessions))
        .catch(() => {});
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to generate recommendations"
      );
    } finally {
      setGenerating(false);
    }
  };

  // ── Load a specific past session ──────────────────
  const handleLoadSession = async (sessionId: string) => {
    setLoading(true);
    setError(null);

    try {
      const result = await fetchAPI<RecommendationResponse>(
        `/api/recommendations/${sessionId}`
      );
      setData(result);
      setActiveSessionId(sessionId);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load session"
      );
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
  const handleToggleWatchlist = async (rec: {
    mal_id: number;
    title: string;
    image_url: string | null;
    genres: string;
    themes: string;
    mal_score: number | null;
    year: number | null;
    anime_type: string | null;
  }) => {
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
            <Skeleton className="h-9 w-40" />
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
                <h1 className="text-3xl font-bold tracking-tight">
                  Recommendations
                </h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  AI-powered anime picks based on your taste profile
                  {hasFeedback && (
                    <Badge variant="secondary" className="ml-2">
                      <Sparkles className="mr-1 h-3 w-3" />
                      Feedback incorporated
                    </Badge>
                  )}
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
                <Button
                  variant="outline"
                  onClick={() => router.push("/dashboard")}
                >
                  <LayoutDashboard className="mr-2 h-4 w-4" />
                  View Profile
                </Button>
                <Button
                  onClick={() => handleGenerate()}
                  disabled={generating}
                >
                  {generating ? (
                    <span className="flex items-center gap-2">
                      <RefreshCw className="h-4 w-4 animate-spin" />
                      Generating…
                    </span>
                  ) : data ? (
                    <>
                      <RefreshCw className="mr-2 h-4 w-4" />
                      {hasFeedback ? "Regenerate with Feedback" : "Regenerate"}
                    </>
                  ) : (
                    <>
                      <Sparkles className="mr-2 h-4 w-4" />
                      Generate Recommendations
                    </>
                  )}
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
                  AI reasoning was unavailable for some recommendations. Showing
                  best matches from your taste profile.
                </AlertDescription>
              </Alert>
            )}

            {/* Empty state */}
            {!data && !generating && (
              <Card className="py-20">
                <CardContent className="flex flex-col items-center justify-center text-center">
                  <Compass className="h-16 w-16 text-muted-foreground/50" />
                  <h2 className="mt-4 text-xl font-semibold">
                    Ready for recommendations?
                  </h2>
                  <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    Click &quot;Generate Recommendations&quot; to get
                    personalised anime picks with AI-powered reasoning based on
                    your MAL profile.
                  </p>
                </CardContent>
              </Card>
            )}

            {/* Generating state */}
            {generating && (
              <Card className="py-20">
                <CardContent className="flex flex-col items-center justify-center text-center">
                  <RefreshCw className="h-12 w-12 animate-spin text-primary" />
                  <div className="mt-5 h-2 w-full max-w-md overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full bg-primary transition-all"
                      style={{ width: `${generationProgress}%` }}
                    />
                  </div>
                  <p className="mt-3 text-xs font-medium text-primary">
                    {generationProgress}%
                  </p>
                  <p className="mt-4 text-sm text-muted-foreground">
                    {stageLabel(generationStage)}…
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground/70">
                    {hasFeedback
                      ? "Applying your feedback and finding new matches"
                      : "Analysing your taste profile and finding matches"}
                  </p>
                </CardContent>
              </Card>
            )}

            {/* Recommendation cards */}
            {data && !generating && (
              <div className="space-y-6">
                <p className="text-sm text-muted-foreground">
                  {data.total} recommendations generated ·{" "}
                  {new Date(data.generated_at).toLocaleString()}
                  {data.custom_query && (
                    <Badge variant="secondary" className="ml-2">
                      Query: {data.custom_query}
                    </Badge>
                  )}
                </p>

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
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
