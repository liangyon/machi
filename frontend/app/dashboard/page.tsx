"use client";

/**
 * Preference Dashboard — /dashboard
 *
 * Displays the user's computed taste profile after a MAL import.
 * Shows genre affinities, top anime, score distribution, and more.
 *
 * Uses simple CSS-based bars instead of a charting library to keep
 * dependencies minimal.  We can swap in Recharts or similar when
 * we add shadcn later.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";

// ── Types matching backend PreferenceProfileResponse ─

interface GenreAffinity {
  genre: string;
  count: number;
  avg_score: number;
  affinity: number;
}

interface AnimeEntry {
  mal_anime_id: number;
  title: string;
  title_english: string | null;
  image_url: string | null;
  watch_status: string;
  user_score: number;
  episodes_watched: number;
  total_episodes: number | null;
  anime_type: string | null;
  genres: string | null;
  themes: string | null;
  year: number | null;
  mal_score: number | null;
}

interface PreferenceProfile {
  total_watched: number;
  total_scored: number;
  mean_score: number;
  score_distribution: Record<string, number>;
  genre_affinity: GenreAffinity[];
  theme_affinity: GenreAffinity[];
  studio_affinity: GenreAffinity[];
  preferred_formats: Record<string, number>;
  completion_rate: number;
  top_10: AnimeEntry[];
  watch_era_preference: Record<string, number>;
  generated_at: string;
}

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  const [profile, setProfile] = useState<PreferenceProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Auth guard ────────────────────────────────────
  useEffect(() => {
    if (!authLoading && !user) {
      router.push("/login");
    }
  }, [authLoading, user, router]);

  // ── Fetch profile ─────────────────────────────────
  useEffect(() => {
    if (!user) return;

    fetchAPI<PreferenceProfile>("/api/mal/profile")
      .then(setProfile)
      .catch((err) => {
        setError(
          err.message.includes("404")
            ? "No profile yet. Import your MAL list first."
            : err.message
        );
      })
      .finally(() => setLoading(false));
  }, [user]);

  // ── Loading / error states ────────────────────────

  if (authLoading || loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <div className="animate-pulse text-zinc-500">Loading your profile…</div>
      </div>
    );
  }

  if (!user) return null;

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50 px-4 dark:bg-zinc-950">
        <div className="text-center space-y-4">
          <p className="text-zinc-500 dark:text-zinc-400">{error}</p>
          <button
            onClick={() => router.push("/import")}
            className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Import MAL List
          </button>
        </div>
      </div>
    );
  }

  if (!profile) return null;

  // ── Computed values ───────────────────────────────

  const maxGenreAffinity = Math.max(
    ...profile.genre_affinity.map((g) => g.affinity),
    0.01
  );

  const scoreEntries = Object.entries(profile.score_distribution)
    .map(([score, count]) => ({ score: parseInt(score), count }))
    .sort((a, b) => a.score - b.score);
  const maxScoreCount = Math.max(...scoreEntries.map((s) => s.count), 1);

  const eraEntries = Object.entries(profile.watch_era_preference)
    .sort((a, b) => a[0].localeCompare(b[0]));
  const maxEraCount = Math.max(...eraEntries.map(([, c]) => c), 1);

  // ── Render ────────────────────────────────────────

  return (
    <div className="min-h-screen bg-zinc-50 px-4 py-8 font-sans dark:bg-zinc-950">
      <div className="mx-auto max-w-5xl space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
              Your Anime Profile
            </h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Based on your MyAnimeList data
            </p>
          </div>
          <button
            onClick={() => router.push("/import")}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Re-import
          </button>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Anime Watched" value={profile.total_watched} />
          <StatCard
            label="Mean Score"
            value={profile.mean_score.toFixed(1)}
          />
          <StatCard
            label="Completion Rate"
            value={`${(profile.completion_rate * 100).toFixed(0)}%`}
          />
          <StatCard label="Scored" value={profile.total_scored} />
        </div>

        {/* Two-column layout for affinities */}
        <div className="grid gap-8 lg:grid-cols-2">
          {/* Genre Affinity */}
          <section className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
              Genre Affinity
            </h2>
            <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
              Weighted by how much you watch and how highly you rate each genre
            </p>
            <div className="space-y-3">
              {profile.genre_affinity.slice(0, 12).map((g) => (
                <AffinityBar
                  key={g.genre}
                  label={g.genre}
                  value={g.affinity}
                  max={maxGenreAffinity}
                  detail={`${g.count} anime · avg ${g.avg_score.toFixed(1)}`}
                />
              ))}
            </div>
          </section>

          {/* Score Distribution */}
          <section className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
              Score Distribution
            </h2>
            <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
              How you rate anime — are you generous or harsh?
            </p>
            <div className="space-y-2">
              {scoreEntries.map(({ score, count }) => (
                <div key={score} className="flex items-center gap-3">
                  <span className="w-6 text-right text-xs font-medium text-zinc-500 dark:text-zinc-400">
                    {score}
                  </span>
                  <div className="flex-1">
                    <div
                      className="h-5 rounded bg-blue-500/80 transition-all dark:bg-blue-400/80"
                      style={{
                        width: `${(count / maxScoreCount) * 100}%`,
                        minWidth: count > 0 ? "4px" : "0",
                      }}
                    />
                  </div>
                  <span className="w-8 text-xs text-zinc-500 dark:text-zinc-400">
                    {count}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* Top 10 */}
        <section className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            Your Top 10
          </h2>
          <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
            Your highest-rated anime — the strongest signal for recommendations
          </p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
            {profile.top_10.map((anime, i) => (
              <div key={anime.mal_anime_id} className="group relative">
                <div className="aspect-[3/4] overflow-hidden rounded-lg bg-zinc-200 dark:bg-zinc-800">
                  {anime.image_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={anime.image_url}
                      alt={anime.title}
                      className="h-full w-full object-cover transition group-hover:scale-105"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-zinc-400">
                      No image
                    </div>
                  )}
                  {/* Score badge */}
                  <div className="absolute top-2 right-2 rounded-full bg-black/70 px-2 py-0.5 text-xs font-bold text-white">
                    ★ {anime.user_score}
                  </div>
                  {/* Rank badge */}
                  <div className="absolute top-2 left-2 rounded-full bg-blue-600/90 px-2 py-0.5 text-xs font-bold text-white">
                    #{i + 1}
                  </div>
                </div>
                <p className="mt-2 text-xs font-medium leading-tight text-zinc-700 dark:text-zinc-300 line-clamp-2">
                  {anime.title_english || anime.title}
                </p>
                {anime.genres && (
                  <p className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500 line-clamp-1">
                    {anime.genres}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* Bottom row: themes, eras, formats */}
        <div className="grid gap-8 lg:grid-cols-3">
          {/* Theme Affinity */}
          <section className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
              Theme Preferences
            </h2>
            <div className="mt-3 space-y-2">
              {profile.theme_affinity.slice(0, 8).map((t) => (
                <div
                  key={t.genre}
                  className="flex items-center justify-between text-sm"
                >
                  <span className="text-zinc-700 dark:text-zinc-300">
                    {t.genre}
                  </span>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {t.count} · {t.avg_score.toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Era Preference */}
          <section className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
              Era Preference
            </h2>
            <div className="mt-3 space-y-2">
              {eraEntries.map(([era, count]) => (
                <div key={era} className="flex items-center gap-3">
                  <span className="w-12 text-xs font-medium text-zinc-500 dark:text-zinc-400">
                    {era}
                  </span>
                  <div className="flex-1">
                    <div
                      className="h-4 rounded bg-emerald-500/80 transition-all dark:bg-emerald-400/80"
                      style={{
                        width: `${(count / maxEraCount) * 100}%`,
                        minWidth: "4px",
                      }}
                    />
                  </div>
                  <span className="w-6 text-right text-xs text-zinc-500 dark:text-zinc-400">
                    {count}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* Format Preference */}
          <section className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
              Format Preference
            </h2>
            <div className="mt-3 space-y-2">
              {Object.entries(profile.preferred_formats)
                .sort(([, a], [, b]) => b - a)
                .map(([format, count]) => (
                  <div
                    key={format}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="text-zinc-700 dark:text-zinc-300">
                      {format}
                    </span>
                    <span className="text-xs text-zinc-500 dark:text-zinc-400">
                      {count}
                    </span>
                  </div>
                ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

// ── Reusable components ─────────────────────────────

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-2xl font-bold text-zinc-900 dark:text-zinc-50">
        {value}
      </p>
    </div>
  );
}

function AffinityBar({
  label,
  value,
  max,
  detail,
}: {
  label: string;
  value: number;
  max: number;
  detail: string;
}) {
  const pct = (value / max) * 100;
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          {label}
        </span>
        <span className="text-xs text-zinc-500 dark:text-zinc-400">
          {detail}
        </span>
      </div>
      <div className="mt-1 h-2 w-full rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div
          className="h-2 rounded-full bg-violet-500 transition-all dark:bg-violet-400"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
