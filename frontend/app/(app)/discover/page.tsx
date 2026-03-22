"use client";

/**
 * Discover Page — /discover
 *
 * Hub for all AI recommendation generators.
 *
 * "For You" tab  — profile-based: 10 picks from your imported list taste profile.
 * "Cauldron" tab — seed-based: pick 1–3 anime, get vibe-matched recommendations.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { toast } from "sonner";
import {
  Compass,
  FlaskConical,
  Sparkles,
  RefreshCw,
  AlertTriangle,
  Search,
  X,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { AnimeCover } from "@/components/shared/anime-cover";
import { SwipeCardDeck } from "@/components/recommendations/swipe-card";
import { useJobPoller } from "@/lib/hooks/useJobPoller";
import type {
  RecommendationResponse,
  RecommendationGenerateAccepted,
  RecommendationJobStatus,
  FeedbackMapResponse,
  PreferenceProfile,
  CauldronSearchResult,
  CauldronSearchResponse,
  CauldronResultsResponse,
  RecommendationItem,
} from "@/lib/types";

// ── Constants ────────────────────────────────────────
const PROFILE_STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  validating: "Validating request",
  loading_profile: "Loading your profile",
  retrieving_candidates: "Finding candidate anime",
  generating_recommendations: "Generating AI recommendations",
  persisting: "Saving recommendations",
  completed: "Completed",
  failed: "Failed",
};

const CAULDRON_STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  validating: "Validating seeds",
  fetching_seeds: "Loading seed anime",
  retrieving_candidates: "Finding vibe matches",
  generating_recommendations: "Brewing recommendations",
  persisting: "Saving results",
  completed: "Done",
  failed: "Failed",
};

const MAX_SEEDS = 3;
const SEARCH_DEBOUNCE_MS = 300;

type Tab = "profile" | "cauldron";

export default function DiscoverPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>("profile");

  // ── Shared state ─────────────────────────────────
  const [watchlistIds, setWatchlistIds] = useState<Set<number>>(new Set());
  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, string>>({});

  // ── "For You" tab state ───────────────────────────
  const [profileData, setProfileData] = useState<RecommendationResponse | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileGenerating, setProfileGenerating] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileProgress, setProfileProgress] = useState(0);
  const [profileStage, setProfileStage] = useState("queued");
  const [listSource, setListSource] = useState<{ source: string; username: string | null } | null>(null);

  // ── Cauldron tab state ────────────────────────────
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<CauldronSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedSeeds, setSelectedSeeds] = useState<CauldronSearchResult[]>([]);
  const [cauldronResults, setCauldronResults] = useState<CauldronResultsResponse | null>(null);
  const [seedTitles, setSeedTitles] = useState<string[]>([]);
  const [cauldronError, setCauldronError] = useState<string | null>(null);

  const { startPolling, isPolling, progress: cauldronProgress, stage: cauldronStage, pollingError } =
    useJobPoller();

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  // ── Load initial data ─────────────────────────────
  useEffect(() => {
    if (!user) return;

    Promise.all([
      fetchAPI<RecommendationResponse>("/api/recommendations").catch(() => null),
      fetchAPI<FeedbackMapResponse>("/api/recommendations/feedback").catch(() => ({ feedback: {} })),
      fetchAPI<{ items: { mal_id: number }[] }>("/api/watchlist").catch(() => ({ items: [] })),
      fetchAPI<PreferenceProfile>("/api/mal/profile").catch(() => null),
    ]).then(([recs, feedback, watchlist, profile]) => {
      if (recs) setProfileData(recs);
      if (feedback) setFeedbackGiven(feedback.feedback);
      if (watchlist) setWatchlistIds(new Set(watchlist.items.map((i) => i.mal_id)));
      if (profile?.source)
        setListSource({ source: profile.source, username: profile.imported_username ?? null });
      setProfileLoading(false);
    });
  }, [user]);

  // ── Close cauldron dropdown on outside click ──────
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ── Shared: feedback ──────────────────────────────
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

  // ── Shared: watchlist toggle ──────────────────────
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

  // ── "For You": generate ───────────────────────────
  const handleGenerate = async () => {
    setProfileGenerating(true);
    setProfileError(null);
    setProfileProgress(0);
    setProfileStage("queued");

    try {
      const accepted = await fetchAPI<RecommendationGenerateAccepted>(
        "/api/recommendations/generate",
        { method: "POST", body: JSON.stringify({}) }
      );

      setProfileProgress(accepted.progress);
      setProfileStage(accepted.stage);

      let finalStatus: RecommendationJobStatus | null = null;
      for (let i = 0; i < 180; i += 1) {
        await sleep(1000);
        const status = await fetchAPI<RecommendationJobStatus>(
          `/api/recommendations/status/${accepted.job_id}`
        );
        setProfileProgress(status.progress);
        setProfileStage(status.stage);
        if (status.status === "succeeded" || status.status === "failed") {
          finalStatus = status;
          break;
        }
      }

      if (!finalStatus) throw new Error("Recommendation generation timed out.");
      if (finalStatus.status === "failed")
        throw new Error(finalStatus.error || "Failed to generate recommendations");

      const result = finalStatus.session_id
        ? await fetchAPI<RecommendationResponse>(`/api/recommendations/${finalStatus.session_id}`)
        : await fetchAPI<RecommendationResponse>("/api/recommendations");

      setProfileData(result);
      toast.success("Recommendations generated successfully");
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Failed to generate recommendations");
    } finally {
      setProfileGenerating(false);
    }
  };

  // ── Cauldron: seed search ─────────────────────────
  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!value.trim() || selectedSeeds.length >= MAX_SEEDS) {
      setSearchResults([]);
      setShowDropdown(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await fetchAPI<CauldronSearchResponse>(
          `/api/cauldron/search?q=${encodeURIComponent(value.trim())}`
        );
        setSearchResults(res.results);
        setShowDropdown(true);
      } catch {
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);
  };

  const addSeed = (seed: CauldronSearchResult) => {
    if (selectedSeeds.length >= MAX_SEEDS) return;
    if (selectedSeeds.some((s) => s.mal_id === seed.mal_id)) return;
    setSelectedSeeds((prev) => [...prev, seed]);
    setSearchQuery("");
    setSearchResults([]);
    setShowDropdown(false);
  };

  const removeSeed = (malId: number) => {
    setSelectedSeeds((prev) => prev.filter((s) => s.mal_id !== malId));
  };

  // ── Cauldron: brew ────────────────────────────────
  const handleBrew = useCallback(async () => {
    if (selectedSeeds.length === 0 || isPolling) return;
    setCauldronError(null);
    setCauldronResults(null);

    try {
      const accepted = await fetchAPI<RecommendationGenerateAccepted>("/api/cauldron/generate", {
        method: "POST",
        body: JSON.stringify({
          seed_mal_ids: selectedSeeds.map((s) => s.mal_id),
          num_recommendations: 5,
        }),
      });

      startPolling({
        pollFn: () =>
          fetchAPI<RecommendationJobStatus>(`/api/cauldron/status/${accepted.job_id}`),
        onSuccess: async (sessionId) => {
          if (!sessionId) {
            setCauldronError("No session ID returned. Please try again.");
            return;
          }
          try {
            const res = await fetchAPI<CauldronResultsResponse>(`/api/cauldron/results/${sessionId}`);
            setCauldronResults(res);
            setSeedTitles(res.seed_titles);
            toast.success("Your brew is ready!");
          } catch {
            setCauldronError("Failed to load cauldron results.");
          }
        },
        onFailure: (err) => {
          setCauldronError(err);
          toast.error("Brew failed. Please try again.");
        },
      });
    } catch (err) {
      setCauldronError(err instanceof Error ? err.message : "Failed to start cauldron.");
    }
  }, [selectedSeeds, isPolling, startPolling]);

  const hasFeedback = Object.keys(feedbackGiven).length > 0;

  // ── Render ────────────────────────────────────────
  return (
    <div className="px-4 py-8">
      <div className="mx-auto max-w-2xl space-y-8">

        {/* Page header */}
        <div>
          <div className="flex items-center gap-2">
            <Compass className="h-7 w-7 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">Discover</h1>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Generate anime recommendations your way.
          </p>
        </div>

        {/* Tab selector */}
        <div className="flex gap-1 rounded-lg border p-1 w-fit">
          <Button
            variant={activeTab === "profile" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("profile")}
            className="gap-2"
          >
            <User className="h-4 w-4" />
            For You
          </Button>
          <Button
            variant={activeTab === "cauldron" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("cauldron")}
            className="gap-2"
          >
            <FlaskConical className="h-4 w-4" />
            Brew
          </Button>
        </div>

        {/* ── For You tab ── */}
        {activeTab === "profile" && (
          <div className="space-y-6">
            {/* Sub-header */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm text-muted-foreground">
                  10 picks from your taste profile.
                </p>
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {listSource && (
                    <Badge variant="outline" className="text-xs">
                      {listSource.source === "anilist" ? "AniList" : "MyAnimeList"}
                      {listSource.username && ` · @${listSource.username}`}
                    </Badge>
                  )}
                  {hasFeedback && (
                    <Badge variant="secondary" className="text-xs">
                      <Sparkles className="mr-1 h-3 w-3" />
                      Feedback incorporated
                    </Badge>
                  )}
                </div>
              </div>
              <Button onClick={handleGenerate} disabled={profileGenerating || profileLoading}>
                {profileGenerating ? (
                  <span className="flex items-center gap-2">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    Generating…
                  </span>
                ) : profileData ? (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4" />
                    {hasFeedback ? "Regenerate with Feedback" : "Regenerate"}
                  </>
                ) : (
                  <>
                    <Sparkles className="mr-2 h-4 w-4" />
                    Generate
                  </>
                )}
              </Button>
            </div>

            {profileError && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{profileError}</AlertDescription>
              </Alert>
            )}

            {profileData?.used_fallback && (
              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>
                  AI reasoning was unavailable for some recommendations. Showing best matches from
                  your taste profile.
                </AlertDescription>
              </Alert>
            )}

            {/* Loading skeleton */}
            {profileLoading && (
              <Card className="py-20">
                <CardContent className="flex flex-col items-center justify-center text-center">
                  <RefreshCw className="h-10 w-10 animate-spin text-muted-foreground/50" />
                </CardContent>
              </Card>
            )}

            {/* Empty state */}
            {!profileLoading && !profileData && !profileGenerating && (
              <Card className="py-20">
                <CardContent className="flex flex-col items-center justify-center text-center">
                  <Compass className="h-16 w-16 text-muted-foreground/50" />
                  <h2 className="mt-4 text-xl font-semibold">Ready for recommendations?</h2>
                  <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    Click &quot;Generate&quot; to get personalised anime picks based on your
                    imported list.
                  </p>
                </CardContent>
              </Card>
            )}

            {/* Generating state */}
            {profileGenerating && (
              <Card className="py-20">
                <CardContent className="flex flex-col items-center justify-center text-center">
                  <RefreshCw className="h-12 w-12 animate-spin text-primary" />
                  <div className="mt-5 h-2 w-full max-w-md overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full bg-primary transition-all"
                      style={{ width: `${profileProgress}%` }}
                    />
                  </div>
                  <p className="mt-3 text-xs font-medium text-primary">{profileProgress}%</p>
                  <p className="mt-4 text-sm text-muted-foreground">
                    {PROFILE_STAGE_LABELS[profileStage] ?? profileStage}…
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground/70">
                    {hasFeedback
                      ? "Applying your feedback and finding new matches"
                      : "Analysing your taste profile and finding matches"}
                  </p>
                </CardContent>
              </Card>
            )}

            {/* Results */}
            {profileData && !profileGenerating && (
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  {profileData.total} recommendations ·{" "}
                  {new Date(profileData.generated_at).toLocaleString()}
                </p>
                <SwipeCardDeck
                  recommendations={profileData.recommendations}
                  feedbackGiven={feedbackGiven}
                  watchlistIds={watchlistIds}
                  onFeedback={handleFeedback}
                  onToggleWatchlist={handleToggleWatchlist}
                />
              </div>
            )}
          </div>
        )}

        {/* ── Cauldron tab ── */}
        {activeTab === "cauldron" && (
          <div className="space-y-6">
            {/* Sub-header */}
            <p className="text-sm text-muted-foreground">
              Pick 1–3 anime that capture the vibe you want. No import needed.
            </p>

            {/* Seed picker */}
            <div className="space-y-4">
              <div className="relative" ref={containerRef}>
                <div className="flex items-center gap-2 rounded-lg border bg-background px-3 py-2 focus-within:ring-2 focus-within:ring-ring">
                  {isSearching ? (
                    <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />
                  ) : (
                    <Search className="h-4 w-4 text-muted-foreground" />
                  )}
                  <Input
                    className="h-auto border-0 p-0 shadow-none focus-visible:ring-0"
                    placeholder={
                      selectedSeeds.length >= MAX_SEEDS
                        ? "3 seeds selected — brew or remove one"
                        : "Search for an anime to use as a seed…"
                    }
                    value={searchQuery}
                    onChange={(e) => handleSearchChange(e.target.value)}
                    onFocus={() => {
                      if (searchResults.length > 0) setShowDropdown(true);
                    }}
                    disabled={selectedSeeds.length >= MAX_SEEDS || isPolling}
                  />
                </div>

                {showDropdown && searchResults.length > 0 && (
                  <div className="absolute z-20 mt-1 w-full rounded-lg border bg-background shadow-lg">
                    {searchResults.map((result) => {
                      const alreadySelected = selectedSeeds.some((s) => s.mal_id === result.mal_id);
                      return (
                        <button
                          key={result.mal_id}
                          className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-muted disabled:opacity-50"
                          onClick={() => addSeed(result)}
                          disabled={alreadySelected}
                        >
                          <div className="h-10 w-8 shrink-0 overflow-hidden rounded">
                            <AnimeCover
                              src={result.image_url}
                              alt={result.title}
                              className="h-full w-full object-cover"
                            />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-medium">{result.title}</p>
                            <p className="truncate text-xs text-muted-foreground">
                              {[result.anime_type, result.year].filter(Boolean).join(" · ")}
                              {result.mal_score ? ` · ★ ${result.mal_score.toFixed(1)}` : ""}
                            </p>
                          </div>
                          {alreadySelected && (
                            <Badge variant="secondary" className="shrink-0 text-xs">
                              Added
                            </Badge>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Seed slots */}
              <div className="grid grid-cols-3 gap-3">
                {Array.from({ length: MAX_SEEDS }).map((_, i) => {
                  const seed = selectedSeeds[i];
                  return seed ? (
                    <div
                      key={seed.mal_id}
                      className="relative overflow-hidden rounded-lg border bg-card shadow-sm"
                    >
                      <div className="h-24 w-full">
                        <AnimeCover
                          src={seed.image_url}
                          alt={seed.title}
                          className="h-full w-full object-cover"
                        />
                      </div>
                      <div className="p-2">
                        <p className="truncate text-xs font-medium">{seed.title}</p>
                      </div>
                      <button
                        className="absolute right-1 top-1 rounded-full bg-background/80 p-0.5 transition-colors hover:bg-background"
                        onClick={() => removeSeed(seed.mal_id)}
                        aria-label={`Remove ${seed.title}`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ) : (
                    <div
                      key={`empty-${i}`}
                      className="flex h-full min-h-[120px] items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground"
                    >
                      Add anime
                    </div>
                  );
                })}
              </div>

              <Button
                className="w-full"
                size="lg"
                onClick={handleBrew}
                disabled={selectedSeeds.length === 0 || isPolling}
              >
                {isPolling ? (
                  <span className="flex items-center gap-2">
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    Brewing…
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <FlaskConical className="h-4 w-4" />
                    Brew
                  </span>
                )}
              </Button>
            </div>

            {(cauldronError || pollingError) && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{cauldronError || pollingError}</AlertDescription>
              </Alert>
            )}

            {isPolling && (
              <Card className="py-10">
                <CardContent className="flex flex-col items-center justify-center text-center">
                  <FlaskConical className="h-10 w-10 animate-pulse text-primary" />
                  <div className="mt-5 h-2 w-full max-w-sm overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full bg-primary transition-all"
                      style={{ width: `${cauldronProgress}%` }}
                    />
                  </div>
                  <p className="mt-3 text-xs font-medium text-primary">{cauldronProgress}%</p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {CAULDRON_STAGE_LABELS[cauldronStage] ?? cauldronStage}…
                  </p>
                </CardContent>
              </Card>
            )}

            {cauldronResults && !isPolling && (
              <div className="space-y-4">
                {seedTitles.length > 0 && (
                  <p className="text-sm text-muted-foreground">
                    <span className="font-medium">Based on:</span> {seedTitles.join(", ")}
                  </p>
                )}
                {cauldronResults.used_fallback && (
                  <Alert>
                    <AlertTriangle className="h-4 w-4" />
                    <AlertDescription>
                      AI reasoning was unavailable. Showing best vibe matches.
                    </AlertDescription>
                  </Alert>
                )}
                <SwipeCardDeck
                  recommendations={cauldronResults.recommendations}
                  feedbackGiven={feedbackGiven}
                  watchlistIds={watchlistIds}
                  onFeedback={handleFeedback}
                  onToggleWatchlist={handleToggleWatchlist}
                />
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  );
}
