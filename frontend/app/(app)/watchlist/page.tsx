"use client";

/**
 * Watchlist Page — /watchlist
 *
 * Displays the user's to-watch list with status management, ratings,
 * and reactions. Components extracted to @/components/watchlist/.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { toast } from "sonner";
import { Bookmark, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { WatchlistCard } from "@/components/watchlist/watchlist-card";
import { STATUS_OPTIONS } from "@/components/watchlist/constants";
import { EmptyState } from "@/components/shared/empty-state";
import type { WatchlistItem, WatchlistResponse } from "@/lib/types";

export default function WatchlistPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [data, setData] = useState<WatchlistResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");

  // ── Fetch watchlist on mount ──────────────────────
  useEffect(() => {
    if (!user) return;

    fetchAPI<WatchlistResponse>("/api/watchlist")
      .then(setData)
      .catch(() => setData({ items: [], total: 0 }))
      .finally(() => setLoading(false));
  }, [user]);

  // ── Remove from watchlist ─────────────────────────
  const handleRemove = async (malId: number, title: string) => {
    try {
      await fetchAPI(`/api/watchlist/${malId}`, { method: "DELETE" });
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.filter((item) => item.mal_id !== malId),
              total: prev.total - 1,
            }
          : prev
      );
      toast.success(`Removed "${title}" from watchlist`);
    } catch {
      toast.error("Failed to remove from watchlist");
    }
  };

  // ── Update watchlist entry ────────────────────────
  const handleUpdate = async (
    malId: number,
    updates: { status?: string; user_rating?: number; reaction?: string }
  ) => {
    try {
      const result = await fetchAPI<{ item: WatchlistItem }>(
        `/api/watchlist/${malId}`,
        { method: "PATCH", body: JSON.stringify(updates) }
      );
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((item) =>
                item.mal_id === malId ? result.item : item
              ),
            }
          : prev
      );
      toast.success("Updated!");
    } catch {
      toast.error("Failed to update");
    }
  };

  // ── Loading state ─────────────────────────────────
  if (loading) {
    return (
      <div className="px-4 py-8">
        <div className="mx-auto max-w-5xl space-y-8">
          <div>
            <Skeleton className="h-8 w-48" />
            <Skeleton className="mt-2 h-4 w-72" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-64 rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  const items = data?.items ?? [];
  const filteredItems =
    filter === "all" ? items : items.filter((item) => item.status === filter);

  const statusCounts = items.reduce(
    (acc, item) => {
      acc[item.status] = (acc[item.status] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  // ── Render ────────────────────────────────────────
  return (
    <div className="px-4 py-8">
      <div className="mx-auto max-w-5xl space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Your Watchlist
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {items.length === 0
                ? "Bookmark anime from recommendations to build your list"
                : `${items.length} anime saved`}
            </p>
          </div>
          <Button onClick={() => router.push("/discover")}>
            <Sparkles className="mr-2 h-4 w-4" />
            Get Recommendations
          </Button>
        </div>

        {/* Filter tabs */}
        {items.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant={filter === "all" ? "default" : "outline"}
              size="sm"
              onClick={() => setFilter("all")}
            >
              All ({items.length})
            </Button>
            {STATUS_OPTIONS.map((opt) => {
              const count = statusCounts[opt.value] || 0;
              if (count === 0) return null;
              return (
                <Button
                  key={opt.value}
                  variant={filter === opt.value ? "default" : "outline"}
                  size="sm"
                  onClick={() => setFilter(opt.value)}
                >
                  <opt.icon className="mr-1.5 h-3.5 w-3.5" />
                  {opt.label} ({count})
                </Button>
              );
            })}
          </div>
        )}

        {/* Empty state */}
        {items.length === 0 && (
          <EmptyState
            icon={Bookmark}
            title="Your watchlist is empty"
            description='Use the bookmark button on recommendations to save anime you want to watch. Your watchlist is separate from the feedback system — saving here won&apos;t affect your recommendations.'
            actionLabel="Browse Recommendations"
            actionIcon={Sparkles}
            onAction={() => router.push("/discover")}
          />
        )}

        {/* Watchlist grid */}
        {filteredItems.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filteredItems.map((item) => (
              <WatchlistCard
                key={item.id}
                item={item}
                onRemove={handleRemove}
                onUpdate={handleUpdate}
              />
            ))}
          </div>
        )}

        {/* No results for filter */}
        {items.length > 0 && filteredItems.length === 0 && (
          <p className="py-12 text-center text-sm text-muted-foreground">
            No anime with this status.
          </p>
        )}
      </div>
    </div>
  );
}
