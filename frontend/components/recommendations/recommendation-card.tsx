/**
 * Individual recommendation card with cover art, metadata, AI reasoning,
 * watchlist toggle, and feedback buttons.
 */

import {
  ThumbsUp,
  ThumbsDown,
  CheckCircle,
  Zap,
  Bookmark,
  BookmarkCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { AnimeCover } from "@/components/shared/anime-cover";
import { AnimeMetadata } from "@/components/shared/anime-metadata";
import { GenreBadges } from "@/components/shared/genre-badges";
import type { RecommendationItem } from "@/lib/types";

const confidenceVariant: Record<string, "default" | "secondary" | "outline"> = {
  high: "default",
  medium: "secondary",
  low: "outline",
};

interface RecommendationCardProps {
  rec: RecommendationItem;
  index: number;
  feedback?: string;
  onFeedback: (malId: number, feedback: string) => void;
  isOnWatchlist: boolean;
  onToggleWatchlist: (rec: RecommendationItem) => void;
}

export function RecommendationCard({
  rec,
  index,
  feedback,
  onFeedback,
  isOnWatchlist,
  onToggleWatchlist,
}: RecommendationCardProps) {
  return (
    <Card className="group overflow-hidden transition hover:shadow-md">
      <div className="flex">
        {/* Cover art */}
        <div className="relative w-28 flex-shrink-0 sm:w-36">
          <AnimeCover src={rec.image_url} alt={rec.title} />
          {/* Rank badge */}
          <Badge className="absolute left-2 top-2" variant="default">
            #{index + 1}
          </Badge>
        </div>

        {/* Content */}
        <div className="flex flex-1 flex-col p-4">
          {/* Title + badges */}
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-semibold leading-tight">
              {rec.title}
            </h3>
            <Badge variant={confidenceVariant[rec.confidence] || "secondary"}>
              {rec.confidence}
            </Badge>
          </div>

          {/* Metadata */}
          <div className="mt-1">
            <AnimeMetadata
              animeType={rec.anime_type}
              year={rec.year}
              malScore={rec.mal_score}
            />
          </div>

          {/* Genres */}
          <div className="mt-2">
            <GenreBadges genres={rec.genres} />
          </div>

          {/* AI Reasoning */}
          <p className="mt-3 flex-1 text-sm leading-relaxed text-muted-foreground">
            {rec.is_fallback && (
              <Zap className="mr-1 inline h-3.5 w-3.5 text-amber-500" />
            )}
            {rec.reasoning}
          </p>

          {/* Similar to */}
          {rec.similar_to.length > 0 && (
            <div className="mt-2 text-xs text-muted-foreground">
              <span className="font-medium">Similar to:</span>{" "}
              {rec.similar_to.join(", ")}
            </div>
          )}

          {/* Action buttons */}
          <Separator className="my-3" />
          <div className="flex items-center gap-2">
            {/* Watchlist bookmark button */}
            <Button
              variant={isOnWatchlist ? "secondary" : "outline"}
              size="sm"
              onClick={() => onToggleWatchlist(rec)}
              title={isOnWatchlist ? "Remove from watchlist" : "Add to watchlist"}
            >
              {isOnWatchlist ? (
                <BookmarkCheck className="mr-1.5 h-3.5 w-3.5 text-primary" />
              ) : (
                <Bookmark className="mr-1.5 h-3.5 w-3.5" />
              )}
              {isOnWatchlist ? "Saved" : "Watchlist"}
            </Button>

            <div className="mx-1 h-4 w-px bg-border" />

            {/* Feedback buttons */}
            {feedback ? (
              <FeedbackDisplay feedback={feedback} />
            ) : (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onFeedback(rec.mal_id, "liked")}
                  title="Influences future recommendations"
                >
                  <ThumbsUp className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onFeedback(rec.mal_id, "disliked")}
                  title="Influences future recommendations"
                >
                  <ThumbsDown className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onFeedback(rec.mal_id, "watched")}
                  title="Already watched — exclude from future"
                >
                  <CheckCircle className="h-3.5 w-3.5" />
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

function FeedbackDisplay({ feedback }: { feedback: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {feedback === "liked" && (
        <>
          <ThumbsUp className="h-3.5 w-3.5 text-emerald-500" />
          Interested
        </>
      )}
      {feedback === "disliked" && (
        <>
          <ThumbsDown className="h-3.5 w-3.5 text-red-500" />
          Not for me
        </>
      )}
      {feedback === "watched" && (
        <>
          <CheckCircle className="h-3.5 w-3.5 text-blue-500" />
          Watched
        </>
      )}
    </span>
  );
}
