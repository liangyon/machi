/**
 * Inline anime metadata row: type, year, MAL score.
 * Used in recommendation cards and watchlist cards.
 */

import { Star } from "lucide-react";

interface AnimeMetadataProps {
  animeType?: string | null;
  year?: number | null;
  malScore?: number | null;
}

export function AnimeMetadata({ animeType, year, malScore }: AnimeMetadataProps) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {animeType && <span>{animeType}</span>}
      {year && <span>{year}</span>}
      {malScore && (
        <span className="flex items-center gap-0.5">
          <Star className="h-3 w-3 fill-current" />
          {malScore}
        </span>
      )}
    </div>
  );
}
