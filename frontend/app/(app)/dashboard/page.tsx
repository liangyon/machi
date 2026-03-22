"use client";

/**
 * Preference Dashboard — /dashboard
 *
 * Displays the user's computed taste profile after a MAL import.
 * Components extracted to @/components/dashboard/.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { StatCard } from "@/components/dashboard/stat-card";
import { AffinityBar } from "@/components/dashboard/affinity-bar";
import { AnimeGridCard } from "@/components/dashboard/anime-grid-card";
import { ScoreDistribution } from "@/components/dashboard/score-distribution";
import type { PreferenceProfile } from "@/lib/types";

export default function DashboardPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [profile, setProfile] = useState<PreferenceProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  // ── Loading state ─────────────────────────────────
  if (loading) {
    return (
      <div className="px-4 py-8">
        <div className="mx-auto max-w-5xl space-y-8">
          <div>
            <Skeleton className="h-8 w-64" />
            <Skeleton className="mt-2 h-4 w-48" />
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
          <div className="grid gap-8 lg:grid-cols-2">
            <Skeleton className="h-80 rounded-xl" />
            <Skeleton className="h-80 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center px-4">
        <div className="text-center space-y-4">
          <Alert variant="destructive" className="max-w-md">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <Button onClick={() => router.push("/import")}>
            Import Your List
          </Button>
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

  const eraEntries = Object.entries(profile.watch_era_preference).sort(
    (a, b) => a[0].localeCompare(b[0])
  );
  const maxEraCount = Math.max(...eraEntries.map(([, c]) => c), 1);

  // ── Render ────────────────────────────────────────
  return (
    <div className="px-4 py-8">
      <div className="mx-auto max-w-5xl space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Your Anime Profile
            </h1>
            <div className="mt-1 flex items-center gap-2">
              {profile.source && profile.imported_username ? (
                <Badge variant="secondary">
                  {profile.source === "anilist" ? "AniList" : "MyAnimeList"} · @{profile.imported_username}
                </Badge>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Based on your anime list data
                </p>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => router.push("/import")}>
              Re-import
            </Button>
            <Button onClick={() => router.push("/recommendations")}>
              <Sparkles className="mr-2 h-4 w-4" />
              Get Recommendations
            </Button>
          </div>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Anime Watched" value={profile.total_watched} />
          <StatCard label="Mean Score" value={profile.mean_score.toFixed(1)} />
          <StatCard
            label="Completion Rate"
            value={`${(profile.completion_rate * 100).toFixed(0)}%`}
          />
          <StatCard label="Scored" value={profile.total_scored} />
        </div>

        {/* Two-column layout: Genre Affinity + Score Distribution */}
        <div className="grid gap-8 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Genre Affinity</CardTitle>
              <CardDescription>
                Weighted by how much you watch and how highly you rate each genre
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {profile.genre_affinity.slice(0, 12).map((g) => (
                <AffinityBar
                  key={g.genre}
                  label={g.genre}
                  value={g.affinity}
                  max={maxGenreAffinity}
                  detail={`${g.count} anime · avg ${g.avg_score.toFixed(1)}`}
                />
              ))}
            </CardContent>
          </Card>

          <ScoreDistribution distribution={profile.score_distribution} />
        </div>

        {/* Top 10 */}
        <Card>
          <CardHeader>
            <CardTitle>Your Top 10</CardTitle>
            <CardDescription>
              Your highest-rated anime — the strongest signal for recommendations
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
              {profile.top_10.map((anime, i) => (
                <AnimeGridCard
                  key={anime.mal_anime_id}
                  anime={anime}
                  rank={i + 1}
                />
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Bottom row: themes, eras, formats */}
        <div className="grid gap-8 lg:grid-cols-3">
          {/* Theme Affinity */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Theme Preferences</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {profile.theme_affinity.slice(0, 8).map((t) => (
                <div
                  key={t.genre}
                  className="flex items-center justify-between text-sm"
                >
                  <span>{t.genre}</span>
                  <span className="text-xs text-muted-foreground">
                    {t.count} · {t.avg_score.toFixed(1)}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Era Preference */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Era Preference</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {eraEntries.map(([era, count]) => (
                <div key={era} className="flex items-center gap-3">
                  <span className="w-12 text-xs font-medium text-muted-foreground">
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
                  <span className="w-6 text-right text-xs text-muted-foreground">
                    {count}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Format Preference */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Format Preference</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {Object.entries(profile.preferred_formats)
                .sort(([, a], [, b]) => b - a)
                .map(([format, count]) => (
                  <div
                    key={format}
                    className="flex items-center justify-between text-sm"
                  >
                    <span>{format}</span>
                    <span className="text-xs text-muted-foreground">
                      {count}
                    </span>
                  </div>
                ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
