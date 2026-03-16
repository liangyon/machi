/**
 * Individual watchlist card with cover art, status selector,
 * rating, reaction, and remove button.
 */

"use client";

import { Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AnimeCover } from "@/components/shared/anime-cover";
import { GenreBadges } from "@/components/shared/genre-badges";
import { RatingSelector } from "@/components/watchlist/rating-selector";
import { ReactionDialog } from "@/components/watchlist/reaction-dialog";
import { STATUS_OPTIONS, STATUS_COLORS } from "@/components/watchlist/constants";
import type { WatchlistItem } from "@/lib/types";

interface WatchlistCardProps {
  item: WatchlistItem;
  onRemove: (malId: number, title: string) => void;
  onUpdate: (
    malId: number,
    updates: { status?: string; user_rating?: number; reaction?: string }
  ) => void;
}

export function WatchlistCard({ item, onRemove, onUpdate }: WatchlistCardProps) {
  const addedDate = new Date(item.added_at).toLocaleDateString();
  const statusOption = STATUS_OPTIONS.find((o) => o.value === item.status);
  const StatusIcon = statusOption?.icon ?? STATUS_OPTIONS[0].icon;

  return (
    <Card className="group overflow-hidden transition hover:shadow-md">
      <div className="flex">
        {/* Cover art */}
        <div className="relative w-24 flex-shrink-0">
          <AnimeCover
            src={item.image_url}
            alt={item.title}
            fallbackClassName="flex h-full min-h-[160px] items-center justify-center bg-muted text-xs text-muted-foreground"
          />
        </div>

        {/* Content */}
        <div className="flex flex-1 flex-col p-3">
          <h3 className="text-sm font-semibold leading-tight line-clamp-2">
            {item.title}
          </h3>

          {/* Metadata */}
          <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
            {item.anime_type && <span>{item.anime_type}</span>}
            {item.year && <span>{item.year}</span>}
            {item.mal_score && (
              <span className="flex items-center gap-0.5">
                <Star className="h-3 w-3 fill-current" />
                {item.mal_score}
              </span>
            )}
          </div>

          {/* Genres */}
          <div className="mt-1.5">
            <GenreBadges genres={item.genres} max={3} />
          </div>

          {/* Status selector */}
          <div className="mt-2">
            <Select
              value={item.status}
              onValueChange={(value) => {
                if (value) onUpdate(item.mal_id, { status: value });
              }}
            >
              <SelectTrigger className="h-7 w-full text-xs">
                <SelectValue>
                  <span className="flex items-center gap-1.5">
                    <StatusIcon
                      className={`h-3 w-3 ${STATUS_COLORS[item.status] || ""}`}
                    />
                    {statusOption?.label || item.status}
                  </span>
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    <span className="flex items-center gap-2">
                      <opt.icon
                        className={`h-3.5 w-3.5 ${STATUS_COLORS[opt.value]}`}
                      />
                      {opt.label}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* User rating (show for completed/watching) */}
          {(item.status === "completed" || item.status === "watching") && (
            <div className="mt-2">
              <RatingSelector
                value={item.user_rating}
                onChange={(rating) =>
                  onUpdate(item.mal_id, { user_rating: rating })
                }
              />
            </div>
          )}

          {/* Reaction display */}
          {item.reaction && (
            <p className="mt-1.5 text-xs italic text-muted-foreground line-clamp-2">
              &ldquo;{item.reaction}&rdquo;
            </p>
          )}

          {/* Footer actions */}
          <Separator className="my-2" />
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              Added {addedDate}
            </span>
            <div className="flex gap-1">
              <ReactionDialog
                currentReaction={item.reaction}
                onSave={(reaction) => onUpdate(item.mal_id, { reaction })}
              />
              <Button
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                onClick={() => onRemove(item.mal_id, item.title)}
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span className="sr-only">Remove</span>
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
