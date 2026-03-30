"use client";

import Image from "next/image";
import { forwardRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { TasteCard } from "@/lib/types";

interface TasteCardDisplayProps {
  card: TasteCard;
}

const TasteCardDisplay = forwardRef<HTMLDivElement, TasteCardDisplayProps>(
  ({ card }, ref) => {
    const sourceLabel =
      card.source === "anilist"
        ? "AniList"
        : card.source === "mal"
          ? "MyAnimeList"
          : null;

    return (
      <div
        ref={ref}
        className="relative w-full max-w-sm mx-auto rounded-2xl overflow-hidden bg-zinc-950 border border-zinc-800 shadow-2xl text-white"
      >
        {/* Top accent bar */}
        <div className="h-1 w-full bg-gradient-to-r from-violet-500 via-pink-500 to-orange-400" />

        <div className="p-6 space-y-5">
          {/* Header: archetype + source badge */}
          <div className="space-y-1">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-2xl font-bold leading-tight tracking-tight text-white">
                  {card.archetype}
                </h2>
                {card.vibe && (
                  <p className="text-sm font-medium text-violet-400 mt-0.5">
                    {card.vibe}
                  </p>
                )}
              </div>
              {sourceLabel && card.imported_username && (
                <Badge
                  variant="outline"
                  className="shrink-0 text-xs border-zinc-700 text-zinc-400"
                >
                  {sourceLabel} · {card.imported_username}
                </Badge>
              )}
            </div>

            {/* Roast */}
            <p className="text-sm italic text-zinc-400 mt-1">&ldquo;{card.roast}&rdquo;</p>
          </div>

          {/* Reasoning */}
          {card.reasoning && (
            <p className="text-sm text-zinc-400 leading-relaxed">{card.reasoning}</p>
          )}

          <Separator className="bg-zinc-800" />

          {/* Stats row */}
          <div className="flex gap-4 text-sm">
            <div className="text-center">
              <p className="text-xl font-bold text-white">{card.entry_count}</p>
              <p className="text-xs text-zinc-500">Watched</p>
            </div>
            <div className="text-center">
              <p className="text-xl font-bold text-white">{card.avg_score.toFixed(1)}</p>
              <p className="text-xs text-zinc-500">Avg Score</p>
            </div>
            <div className="text-center">
              <p className="text-xl font-bold text-white">{card.favorite_era}</p>
              <p className="text-xs text-zinc-500">Fav Era</p>
            </div>
          </div>

          <Separator className="bg-zinc-800" />

          {/* Top genres */}
          {card.top_genres.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
                Top Genres
              </p>
              <div className="flex flex-wrap gap-1.5">
                {card.top_genres.map((g) => (
                  <Badge
                    key={g}
                    className="bg-violet-900/60 text-violet-200 border-violet-700/50 hover:bg-violet-900/60"
                  >
                    {g}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Taste traits */}
          {card.taste_traits.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
                Traits
              </p>
              <div className="flex flex-wrap gap-1.5">
                {card.taste_traits.map((t) => (
                  <Badge
                    key={t}
                    className="bg-pink-900/50 text-pink-200 border-pink-700/50 hover:bg-pink-900/50"
                  >
                    {t}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Dark horse */}
          {card.dark_horse && (
            <>
              <Separator className="bg-zinc-800" />
              <div className="space-y-1.5">
                <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
                  Dark Horse Pick
                </p>
                <div className="flex gap-3 items-center rounded-xl bg-zinc-900 border border-zinc-800 p-3">
                  {card.dark_horse.image_url && (
                    <div className="relative w-10 h-14 shrink-0 rounded overflow-hidden">
                      <Image
                        src={card.dark_horse.image_url}
                        alt={card.dark_horse.title}
                        fill
                        className="object-cover"
                        unoptimized
                      />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-white truncate">
                      {card.dark_horse.title}
                    </p>
                    {card.dark_horse.genres && (
                      <p className="text-xs text-zinc-500 truncate mt-0.5">
                        {card.dark_horse.genres.split(",").slice(0, 2).join(", ")}
                      </p>
                    )}
                    <div className="flex gap-2 mt-1 text-xs">
                      <span className="text-emerald-400 font-semibold">
                        You: {card.dark_horse.user_score}/10
                      </span>
                      {card.dark_horse.mal_score != null && (
                        <span className="text-zinc-500">
                          MAL: {card.dark_horse.mal_score.toFixed(1)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer branding */}
        <div className="px-6 pb-4">
          <p className="text-center text-xs text-zinc-700 tracking-widest uppercase">
            machi
          </p>
        </div>
      </div>
    );
  }
);

TasteCardDisplay.displayName = "TasteCardDisplay";

export { TasteCardDisplay };
