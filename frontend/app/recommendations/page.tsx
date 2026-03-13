"use client";

/**
 * Recommendations Page — /recommendations
 *
 * Displays AI-generated anime recommendations with reasoning.
 * Each recommendation is a card showing:
 * - Cover art + title + metadata
 * - AI reasoning (why this anime matches the user's taste)
 * - Confidence badge (high/medium/low)
 * - "Similar to" connections to the user's watched anime
 * - Feedback buttons (👍 / 👎)
 *
 * Flow:
 * 1. On page load, try to fetch cached recommendations (GET /api/recommendations)
 * 2. If none exist, show a "Generate" button
 * 3. When user clicks "Generate", call POST /api/recommendations/generate
 * 4. Display results as cards
 * 5. User can give feedback on each recommendation
 *
 * Design decisions:
 * - We separate "Generate" from page load because generation is expensive
 *   (~3-5 seconds, costs money). We don't want to auto-generate on every visit.
 * - The fallback notice tells users when AI reasoning wasn't available.
 * - Feedback buttons are simple for now (Phase 3.5 will add more options).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";

// ── Types matching backend schemas ──────────────────

interface RecommendationItem {
  mal_id: number;
  title: string;
  image_url: string | null;
  genres: string;
  themes: string;
  synopsis: string;
  mal_score: number | null;
  year: number | null;
  anime_type: string | null;
  reasoning: string;
  confidence: "high" | "medium" | "low";
  similar_to: string[];
  similarity_score: number;
  preference_score: number;
  combined_score: number;
  is_fallback: boolean;
}

interface RecommendationResponse {
  recommendations: RecommendationItem[];
  generated_at: string;
  total: number;
  used_fallback: boolean;
  custom_query: string | null;
}

// ── Confidence badge colours ────────────────────────

const confidenceStyles: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400",
  low: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400",
};

export default function RecommendationsPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedbackGiven, setFeedbackGiven] = useState<Record<number, string>>({});

  // ── Auth guard ────────────────────────────────────
  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
    }
  }, [authLoading, user, router]);

  // ── Fetch cached recommendations on mount ─────────
  useEffect(() => {
    if (!user) return;

    fetchAPI<RecommendationResponse>("/api/recommendations")
      .then(setData)
      .catch(() => {
        // 404 = no cached recs, that's fine
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [user]);

  // ── Generate new recommendations ──────────────────
  const handleGenerate = async (customQuery?: string) => {
    setGenerating(true);
    setError(null);

    try {
      const body: Record<string, unknown> = {};
      if (customQuery) body.custom_query = customQuery;

      const result = await fetchAPI<RecommendationResponse>(
        "/api/recommendations/generate",
        {
          method: "POST",
          body: JSON.stringify(body),
        }
      );
      setData(result);
      setFeedbackGiven({}); // reset feedback for new recs
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to generate recommendations"
      );
    } finally {
      setGenerating(false);
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
    } catch {
      // Silently fail — feedback is non-critical
    }
  };

  // ── Loading / error states ────────────────────────

  if (authLoading || loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <div className="animate-pulse text-zinc-500">Loading…</div>
      </div>
    );
  }

  if (!user) return null;

  // ── Render ────────────────────────────────────────

  return (
    <div className="min-h-screen bg-zinc-50 px-4 py-8 font-sans dark:bg-zinc-950">
      <div className="mx-auto max-w-6xl space-y-8">
        {/* Header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
              Recommendations
            </h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              AI-powered anime picks based on your taste profile
            </p>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => router.push("/dashboard")}
              className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              View Profile
            </button>
            <button
              onClick={() => handleGenerate()}
              disabled={generating}
              className="rounded-lg bg-violet-600 px-6 py-2 text-sm font-medium text-white transition hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {generating ? (
                <span className="flex items-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Generating…
                </span>
              ) : data ? (
                "Regenerate"
              ) : (
                "Generate Recommendations"
              )}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Fallback notice */}
        {data?.used_fallback && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400">
            ⚠️ AI reasoning was unavailable for some recommendations. Showing best
            matches from your taste profile.
          </div>
        )}

        {/* Empty state */}
        {!data && !generating && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-zinc-200 bg-white py-20 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="text-6xl">🎯</div>
            <h2 className="mt-4 text-xl font-semibold text-zinc-900 dark:text-zinc-50">
              Ready for recommendations?
            </h2>
            <p className="mt-2 max-w-md text-center text-sm text-zinc-500 dark:text-zinc-400">
              Click &quot;Generate Recommendations&quot; to get personalised anime
              picks with AI-powered reasoning based on your MAL profile.
            </p>
          </div>
        )}

        {/* Generating state */}
        {generating && (
          <div className="flex flex-col items-center justify-center rounded-xl border border-zinc-200 bg-white py-20 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="h-12 w-12 animate-spin rounded-full border-4 border-violet-200 border-t-violet-600" />
            <p className="mt-4 text-sm text-zinc-500 dark:text-zinc-400">
              Analysing your taste profile and finding matches…
            </p>
            <p className="mt-1 text-xs text-zinc-400 dark:text-zinc-500">
              This usually takes 3-5 seconds
            </p>
          </div>
        )}

        {/* Recommendation cards */}
        {data && !generating && (
          <div className="space-y-6">
            {/* Summary */}
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {data.total} recommendations generated •{" "}
              {new Date(data.generated_at).toLocaleString()}
              {data.custom_query && (
                <span className="ml-2 rounded-full bg-violet-100 px-2 py-0.5 text-xs text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
                  Query: {data.custom_query}
                </span>
              )}
            </p>

            {/* Cards */}
            <div className="grid gap-6 md:grid-cols-2">
              {data.recommendations.map((rec, index) => (
                <RecommendationCard
                  key={rec.mal_id}
                  rec={rec}
                  index={index}
                  feedback={feedbackGiven[rec.mal_id]}
                  onFeedback={handleFeedback}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Recommendation Card Component ───────────────────

function RecommendationCard({
  rec,
  index,
  feedback,
  onFeedback,
}: {
  rec: RecommendationItem;
  index: number;
  feedback?: string;
  onFeedback: (malId: number, feedback: string) => void;
}) {
  return (
    <div className="group overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm transition hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex">
        {/* Cover art */}
        <div className="relative w-28 flex-shrink-0 sm:w-36">
          {rec.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={rec.image_url}
              alt={rec.title}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full items-center justify-center bg-zinc-200 text-xs text-zinc-400 dark:bg-zinc-800">
              No image
            </div>
          )}
          {/* Rank badge */}
          <div className="absolute top-2 left-2 rounded-full bg-black/70 px-2 py-0.5 text-xs font-bold text-white">
            #{index + 1}
          </div>
        </div>

        {/* Content */}
        <div className="flex flex-1 flex-col p-4">
          {/* Title + badges */}
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-semibold leading-tight text-zinc-900 dark:text-zinc-50">
              {rec.title}
            </h3>
            <span
              className={`flex-shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                confidenceStyles[rec.confidence] || confidenceStyles.medium
              }`}
            >
              {rec.confidence}
            </span>
          </div>

          {/* Metadata */}
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
            {rec.anime_type && <span>{rec.anime_type}</span>}
            {rec.year && <span>{rec.year}</span>}
            {rec.mal_score && <span>★ {rec.mal_score}</span>}
          </div>

          {/* Genres */}
          {rec.genres && (
            <div className="mt-2 flex flex-wrap gap-1">
              {rec.genres.split(",").map((genre) => (
                <span
                  key={genre.trim()}
                  className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                >
                  {genre.trim()}
                </span>
              ))}
            </div>
          )}

          {/* AI Reasoning */}
          <p className="mt-3 flex-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
            {rec.is_fallback && (
              <span className="mr-1 text-amber-500">⚡</span>
            )}
            {rec.reasoning}
          </p>

          {/* Similar to */}
          {rec.similar_to.length > 0 && (
            <div className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              <span className="font-medium">Similar to:</span>{" "}
              {rec.similar_to.join(", ")}
            </div>
          )}

          {/* Feedback buttons */}
          <div className="mt-3 flex items-center gap-2 border-t border-zinc-100 pt-3 dark:border-zinc-800">
            {feedback ? (
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                {feedback === "liked" && "👍 You liked this"}
                {feedback === "disliked" && "👎 Not for you"}
                {feedback === "watched" && "✅ Already watched"}
              </span>
            ) : (
              <>
                <button
                  onClick={() => onFeedback(rec.mal_id, "liked")}
                  className="rounded-lg border border-zinc-200 px-3 py-1 text-xs text-zinc-600 transition hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-emerald-700 dark:hover:bg-emerald-900/20 dark:hover:text-emerald-400"
                >
                  👍 Interested
                </button>
                <button
                  onClick={() => onFeedback(rec.mal_id, "disliked")}
                  className="rounded-lg border border-zinc-200 px-3 py-1 text-xs text-zinc-600 transition hover:border-red-300 hover:bg-red-50 hover:text-red-700 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-red-700 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                >
                  👎 Not for me
                </button>
                <button
                  onClick={() => onFeedback(rec.mal_id, "watched")}
                  className="rounded-lg border border-zinc-200 px-3 py-1 text-xs text-zinc-600 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 dark:hover:text-blue-400"
                >
                  ✅ Watched
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
