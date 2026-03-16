/**
 * Single anime card in the Top-10 grid on the dashboard.
 */

import { Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { AnimeCover } from "@/components/shared/anime-cover";
import type { AnimeEntry } from "@/lib/types";

interface AnimeGridCardProps {
  anime: AnimeEntry;
  rank: number;
}

export function AnimeGridCard({ anime, rank }: AnimeGridCardProps) {
  return (
    <div className="group relative">
      <div className="aspect-[3/4] overflow-hidden rounded-lg bg-muted">
        <AnimeCover
          src={anime.image_url}
          alt={anime.title}
          className="h-full w-full object-cover transition group-hover:scale-105"
        />
        {/* Score badge */}
        <div className="absolute top-2 right-2 flex items-center gap-0.5 rounded-full bg-black/70 px-2 py-0.5 text-xs font-bold text-white">
          <Star className="h-3 w-3 fill-current" />
          {anime.user_score}
        </div>
        {/* Rank badge */}
        <Badge className="absolute top-2 left-2" variant="default">
          #{rank}
        </Badge>
      </div>
      <p className="mt-2 text-xs font-medium leading-tight line-clamp-2">
        {anime.title_english || anime.title}
      </p>
      {anime.genres && (
        <p className="mt-0.5 text-xs text-muted-foreground line-clamp-1">
          {anime.genres}
        </p>
      )}
    </div>
  );
}
