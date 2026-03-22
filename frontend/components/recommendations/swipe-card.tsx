"use client";

/**
 * SwipeCardDeck — Tinder-style swipeable card view for recommendations.
 *
 * Swipe right  → save to watchlist
 * Swipe left   → skip to next card (no feedback)
 * Tap the card → expand synopsis / similar_to details
 * Arrow keys   → navigate cards
 * Prev/Next buttons → navigate cards
 *
 * Gesture implementation uses native Pointer Events (no framer-motion
 * dependency needed).  setPointerCapture() keeps tracking the drag even
 * if the pointer leaves the element, and preventDefault() only fires when
 * horizontal movement dominates — so the page scroll is not blocked on
 * vertical swipes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ThumbsUp,
  ThumbsDown,
  CheckCircle,
  Bookmark,
  BookmarkCheck,
  Zap,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AnimeCover } from "@/components/shared/anime-cover";
import { AnimeMetadata } from "@/components/shared/anime-metadata";
import { GenreBadges } from "@/components/shared/genre-badges";
import type { RecommendationItem } from "@/lib/types";

const SWIPE_THRESHOLD = 100; // px to trigger a swipe action
const SWIPE_OUT_DISTANCE = 600; // px to fly off screen
const ANIMATE_OUT_MS = 300; // ms for the fly-out animation

const confidenceVariant: Record<string, "default" | "secondary" | "outline"> = {
  high: "default",
  medium: "secondary",
  low: "outline",
};

export interface SwipeCardDeckProps {
  recommendations: RecommendationItem[];
  feedbackGiven: Record<number, string>;
  watchlistIds: Set<number>;
  onFeedback: (malId: number, feedback: string) => void;
  onToggleWatchlist: (rec: RecommendationItem) => void;
}

export function SwipeCardDeck({
  recommendations,
  feedbackGiven,
  watchlistIds,
  onFeedback,
  onToggleWatchlist,
}: SwipeCardDeckProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [dragX, setDragX] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isAnimatingOut, setIsAnimatingOut] = useState(false);
  // Track pointer start position
  const startX = useRef(0);
  const startY = useRef(0);
  // Distinguish tap vs drag
  const hasDragged = useRef(false);

  const total = recommendations.length;
  const rec = recommendations[currentIndex];
  const isDone = currentIndex >= total;

  // ── Advance to next card ───────────────────────────
  const advance = useCallback(
    (direction: "right" | "left") => {
      if (isAnimatingOut) return;
      setIsAnimatingOut(true);
      setDragX(direction === "right" ? SWIPE_OUT_DISTANCE : -SWIPE_OUT_DISTANCE);

      setTimeout(() => {
        setCurrentIndex((i) => i + 1);
        setDragX(0);
        setIsAnimatingOut(false);
      }, ANIMATE_OUT_MS);
    },
    [isAnimatingOut]
  );

  // Direct navigation — no fly-out animation. advance() is reserved for swipe gestures only.
  const goNext = useCallback(() => {
    if (currentIndex < total && !isAnimatingOut) {
      setCurrentIndex((i) => i + 1);
    }
  }, [currentIndex, total, isAnimatingOut]);

  const goPrev = useCallback(() => {
    if (currentIndex > 0 && !isAnimatingOut) {
      setCurrentIndex((i) => i - 1);
    }
  }, [currentIndex, isAnimatingOut]);

  // ── Keyboard navigation ────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") goNext();
      if (e.key === "ArrowLeft") goPrev();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goNext, goPrev]);

  // ── Pointer events ────────────────────────────────
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isAnimatingOut || isDone) return;
    startX.current = e.clientX;
    startY.current = e.clientY;
    hasDragged.current = false;
    setIsDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging || isAnimatingOut) return;
    const deltaX = e.clientX - startX.current;
    const deltaY = e.clientY - startY.current;

    // Only block scroll when the gesture is clearly horizontal
    if (Math.abs(deltaX) > Math.abs(deltaY) * 1.5) {
      e.preventDefault();
    }

    if (Math.abs(deltaX) > 5) hasDragged.current = true;
    setDragX(deltaX);
  };

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isDragging) return;
    setIsDragging(false);

    const finalDragX = e.clientX - startX.current;

    if (!hasDragged.current) {
      setDragX(0);
      return;
    }

    if (finalDragX > SWIPE_THRESHOLD) {
      // Swipe right → watchlist
      onToggleWatchlist(rec);
      advance("right");
    } else if (finalDragX < -SWIPE_THRESHOLD) {
      // Swipe left → skip
      advance("left");
    } else {
      // Snap back
      setDragX(0);
    }
  };

  // ── Computed styles ───────────────────────────────
  const rotation = dragX * 0.05;
  const likeOpacity = Math.min(1, Math.max(0, dragX / 150));
  const skipOpacity = Math.min(1, Math.max(0, -dragX / 150));

  const cardStyle: React.CSSProperties = {
    transform: `translateX(${dragX}px) rotate(${rotation}deg)`,
    transition: isDragging || isAnimatingOut ? (isAnimatingOut ? `transform ${ANIMATE_OUT_MS}ms ease` : "none") : "transform 0.3s ease",
    touchAction: "none", // prevent browser default touch gestures
    userSelect: "none",
  };

  // ── End state ─────────────────────────────────────
  if (isDone) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <p className="text-lg font-semibold">You&apos;ve seen all recommendations!</p>
        <p className="mt-2 text-sm text-muted-foreground">
          Generate new recommendations or go back to the start.
        </p>
        <Button
          className="mt-6"
          variant="outline"
          onClick={() => setCurrentIndex(0)}
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          Start over
        </Button>
      </div>
    );
  }

  const isOnWatchlist = watchlistIds.has(rec.mal_id);
  const feedback = feedbackGiven[rec.mal_id];

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Progress */}
      <p className="text-sm text-muted-foreground">
        {currentIndex + 1} / {total}
      </p>

      {/* Card row: outer arrows + card */}
      <div className="flex w-full max-w-lg items-center gap-3">
        {/* Left outer arrow */}
        <button
          onClick={goPrev}
          disabled={currentIndex === 0 || isAnimatingOut}
          className="shrink-0 text-muted-foreground/30 transition-colors hover:text-muted-foreground/60 disabled:pointer-events-none disabled:opacity-0"
          aria-label="Previous card"
        >
          <ChevronLeft className="h-6 w-6" />
        </button>

        {/* Card */}
        <div
          key={rec.mal_id}
          className="group relative flex-1 cursor-grab rounded-xl border bg-card shadow-lg active:cursor-grabbing"
          style={cardStyle}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        >
        {/* LIKE overlay */}
        <div
          className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-green-500/20"
          style={{ opacity: likeOpacity }}
        >
          <span className="rounded-lg border-4 border-green-500 px-4 py-2 text-2xl font-extrabold text-green-500 rotate-[-15deg]">
            SAVE
          </span>
        </div>

        {/* SKIP overlay */}
        <div
          className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-muted/40"
          style={{ opacity: skipOpacity }}
        >
          <span className="rounded-lg border-4 border-muted-foreground px-4 py-2 text-2xl font-extrabold text-muted-foreground rotate-[15deg]">
            SKIP
          </span>
        </div>

        {/* Cover art — top ~45% */}
        <div className="relative h-64 w-full overflow-hidden rounded-t-xl sm:h-72">
          <AnimeCover
            src={rec.image_url}
            alt={rec.title}
            className="h-full w-full object-cover"
          />
          {/* Rank badge */}
          <Badge className="absolute left-2 top-2" variant="default">
            #{currentIndex + 1}
          </Badge>
          {/* Fallback indicator */}
          {rec.is_fallback && (
            <div className="absolute right-2 top-2">
              <Zap className="h-4 w-4 text-yellow-500" />
            </div>
          )}
        </div>

        {/* Content */}
        <div className="flex flex-col gap-2 p-4">
          {/* Title + confidence */}
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-semibold leading-tight">{rec.title}</h3>
            <Badge variant={confidenceVariant[rec.confidence] || "secondary"} className="shrink-0">
              {rec.confidence}
            </Badge>
          </div>

          {/* Metadata */}
          <AnimeMetadata
            animeType={rec.anime_type}
            year={rec.year}
            malScore={rec.mal_score}
          />

          {/* Genres */}
          <GenreBadges genres={rec.genres} />

          {/* Reasoning */}
          <p className="text-sm text-muted-foreground">
            {rec.reasoning}
          </p>

          {/* Similar to */}
          {rec.similar_to && rec.similar_to.length > 0 && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">Similar to:</span>{" "}
              {rec.similar_to.join(", ")}
            </p>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center justify-between border-t px-4 py-3">
          {/* Watchlist */}
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              onToggleWatchlist(rec);
            }}
            className={isOnWatchlist ? "text-primary" : ""}
          >
            {isOnWatchlist ? (
              <BookmarkCheck className="mr-1 h-4 w-4" />
            ) : (
              <Bookmark className="mr-1 h-4 w-4" />
            )}
            {isOnWatchlist ? "Saved" : "Save"}
          </Button>

          {/* Feedback */}
          {!feedback ? (
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onFeedback(rec.mal_id, "liked");
                }}
              >
                <ThumbsUp className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onFeedback(rec.mal_id, "disliked");
                }}
              >
                <ThumbsDown className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onFeedback(rec.mal_id, "watched");
                }}
              >
                <CheckCircle className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <Badge variant="outline" className="text-xs">
              {feedback === "liked" && "👍 Interested"}
              {feedback === "disliked" && "👎 Not for me"}
              {feedback === "watched" && "✓ Watched"}
            </Badge>
          )}
        </div>
        </div>
        {/* end card */}

        {/* Right outer arrow */}
        <button
          onClick={goNext}
          disabled={currentIndex >= total - 1 || isAnimatingOut}
          className="shrink-0 text-muted-foreground/30 transition-colors hover:text-muted-foreground/60 disabled:pointer-events-none disabled:opacity-0"
          aria-label="Next card"
        >
          <ChevronRight className="h-6 w-6" />
        </button>
      </div>
      {/* end card row */}

      {/* Navigation */}
      <div className="flex items-center gap-4">
        <Button
          variant="outline"
          size="icon"
          onClick={goPrev}
          disabled={currentIndex === 0 || isAnimatingOut}
          aria-label="Previous card"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>

        {/* Dot indicators (up to 10 cards) or text counter */}
        {total <= 10 ? (
          <div className="flex gap-1.5">
            {Array.from({ length: total }).map((_, i) => (
              <div
                key={i}
                className={`h-2 w-2 rounded-full transition-colors ${
                  i === currentIndex ? "bg-primary" : "bg-muted"
                }`}
              />
            ))}
          </div>
        ) : (
          <span className="text-sm text-muted-foreground">
            {currentIndex + 1} / {total}
          </span>
        )}

        <Button
          variant="outline"
          size="icon"
          onClick={goNext}
          disabled={currentIndex >= total - 1 || isAnimatingOut}
          aria-label="Next card"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {/* Swipe hint */}
      <p className="text-xs text-muted-foreground/50">
        Swipe right to save · Swipe left to skip · Tap card to expand
      </p>
    </div>
  );
}
