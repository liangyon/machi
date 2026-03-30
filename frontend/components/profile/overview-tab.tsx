"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { Download, RefreshCw, Sparkles } from "lucide-react";
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
import { TasteCardDisplay } from "@/components/taste-card/taste-card-display";
import type { PreferenceProfile, TasteCard } from "@/lib/types";

interface OverviewTabProps {
  onSwitchToImport: () => void;
}

export function OverviewTab({ onSwitchToImport }: OverviewTabProps) {
  const { user } = useAuth();
  const router = useRouter();
  const cardRef = useRef<HTMLDivElement>(null);

  const [profile, setProfile] = useState<PreferenceProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [tasteCard, setTasteCard] = useState<TasteCard | null>(null);
  const [cardLoading, setCardLoading] = useState(true);
  const [cardRefreshing, setCardRefreshing] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const fetchTasteCard = useCallback(async (refresh = false) => {
    const url = refresh ? "/api/taste-card?refresh=true" : "/api/taste-card";
    try {
      const data = await fetchAPI<TasteCard>(url);
      setTasteCard(data);
    } catch {
      // Silently fail — no profile yet, taste card just won't show
      setTasteCard(null);
    }
  }, []);

  const handleRefreshCard = async () => {
    setCardRefreshing(true);
    await fetchTasteCard(true);
    setCardRefreshing(false);
  };

  useEffect(() => {
    if (!user) return;

    fetchAPI<PreferenceProfile>("/api/mal/profile")
      .then(setProfile)
      .catch((err) => {
        setProfileError(
          err.message.includes("404")
            ? "No profile yet. Import your anime list first."
            : err.message
        );
      })
      .finally(() => setProfileLoading(false));

    fetchTasteCard().finally(() => setCardLoading(false));
  }, [user, fetchTasteCard]);

  const handleDownload = async () => {
    if (!cardRef.current) return;
    setDownloading(true);
    try {
      const { default: html2canvas } = await import("html2canvas");
      const canvas = await html2canvas(cardRef.current, {
        scale: 2,
        backgroundColor: null,
        useCORS: true,
      });
      const url = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = url;
      a.download = "machi-taste-card.png";
      a.click();
    } finally {
      setDownloading(false);
    }
  };

  if (profileLoading) {
    return (
      <div className="space-y-8">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
          <Skeleton className="h-[480px] lg:w-80 shrink-0 rounded-2xl" />
          <div className="flex-1 space-y-6">
            <div className="grid grid-cols-2 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-10 w-40 rounded-lg" />
            <Skeleton className="h-64 rounded-xl" />
          </div>
        </div>
        <div className="grid gap-8 lg:grid-cols-2">
          <Skeleton className="h-80 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
      </div>
    );
  }

  if (profileError) {
    return (
      <div className="flex flex-col items-center gap-4 py-16 text-center">
        <Alert variant="destructive" className="max-w-md">
          <AlertDescription>{profileError}</AlertDescription>
        </Alert>
        <Button onClick={onSwitchToImport}>Import Your List</Button>
      </div>
    );
  }

  if (!profile) return null;

  const maxGenreAffinity = Math.max(
    ...profile.genre_affinity.map((g) => g.affinity),
    0.01
  );
  const eraEntries = Object.entries(profile.watch_era_preference).sort(
    (a, b) => a[0].localeCompare(b[0])
  );
  const maxEraCount = Math.max(...eraEntries.map(([, c]) => c), 1);

  return (
    <div className="space-y-8">

      {/* ── Top row: taste card + stats side by side ── */}
      <div className="flex flex-col gap-8 lg:flex-row lg:items-start">

        {/* Taste card column */}
        <div className="lg:w-80 shrink-0">
          {cardLoading ? (
            <Skeleton className="h-[480px] w-full rounded-2xl" />
          ) : tasteCard ? (
            <div>
              <TasteCardDisplay ref={cardRef} card={tasteCard} />
              <div className="flex gap-1 mt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleRefreshCard}
                  disabled={cardRefreshing}
                  className="text-muted-foreground text-xs"
                >
                  <RefreshCw className={`h-3 w-3 mr-1 ${cardRefreshing ? "animate-spin" : ""}`} />
                  {cardRefreshing ? "Regenerating…" : "Regenerate"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleDownload}
                  disabled={downloading}
                  className="text-muted-foreground text-xs"
                >
                  <Download className="h-3 w-3 mr-1" />
                  {downloading ? "Saving…" : "Save PNG"}
                </Button>
              </div>
            </div>
          ) : null}
        </div>

        {/* Stats column */}
        <div className="flex-1 space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-2">
            <StatCard label="Anime Watched" value={profile.total_watched} />
            <StatCard label="Mean Score" value={profile.mean_score.toFixed(1)} />
            <StatCard
              label="Completion Rate"
              value={`${(profile.completion_rate * 100).toFixed(0)}%`}
            />
            <StatCard label="Scored" value={profile.total_scored} />
          </div>

          <Button onClick={() => router.push("/discover")} className="w-full sm:w-fit">
            <Sparkles className="mr-2 h-4 w-4" />
            Get Recommendations
          </Button>

          {/* Top 10 */}
          <Card>
            <CardHeader>
              <CardTitle>Your Top 10</CardTitle>
              <CardDescription>
                Your highest-rated anime — the strongest signal for recommendations
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
                {profile.top_10.map((anime, i) => (
                  <AnimeGridCard key={anime.mal_anime_id} anime={anime} rank={i + 1} />
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ── Genre affinity + score distribution ── */}
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

        {/* Themes, eras, formats */}
        <div className="grid gap-8 lg:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Theme Preferences</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {profile.theme_affinity.slice(0, 8).map((t) => (
                <div key={t.genre} className="flex items-center justify-between text-sm">
                  <span>{t.genre}</span>
                  <span className="text-xs text-muted-foreground">
                    {t.count} · {t.avg_score.toFixed(1)}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Era Preference</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {eraEntries.map(([era, count]) => (
                <div key={era} className="flex items-center gap-3">
                  <span className="w-12 text-xs font-medium text-muted-foreground">{era}</span>
                  <div className="flex-1">
                    <div
                      className="h-4 rounded bg-emerald-500/80 transition-all dark:bg-emerald-400/80"
                      style={{ width: `${(count / maxEraCount) * 100}%`, minWidth: "4px" }}
                    />
                  </div>
                  <span className="w-6 text-right text-xs text-muted-foreground">{count}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Format Preference</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {Object.entries(profile.preferred_formats)
                .sort(([, a], [, b]) => b - a)
                .map(([format, count]) => (
                  <div key={format} className="flex items-center justify-between text-sm">
                    <span>{format}</span>
                    <span className="text-xs text-muted-foreground">{count}</span>
                  </div>
                ))}
            </CardContent>
          </Card>
        </div>

      {profile.source && profile.imported_username && (
        <div>
          <Badge variant="secondary">
            {profile.source === "anilist" ? "AniList" : "MyAnimeList"} · @{profile.imported_username}
          </Badge>
        </div>
      )}
    </div>
  );
}
