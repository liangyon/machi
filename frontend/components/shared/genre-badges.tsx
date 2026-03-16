/**
 * Renders a comma-separated genre string as a row of Badge components.
 * Used in recommendation cards and watchlist cards.
 */

import { Badge } from "@/components/ui/badge";

interface GenreBadgesProps {
  genres: string | null;
  /** Max number of badges to show. Defaults to all. */
  max?: number;
}

export function GenreBadges({ genres, max }: GenreBadgesProps) {
  if (!genres) return null;

  const items = genres.split(",").map((g) => g.trim());
  const visible = max ? items.slice(0, max) : items;

  return (
    <div className="flex flex-wrap gap-1">
      {visible.map((genre) => (
        <Badge key={genre} variant="outline" className="text-xs">
          {genre}
        </Badge>
      ))}
    </div>
  );
}
