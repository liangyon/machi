/**
 * Watchlist status options and color mappings.
 */

import { Eye, Play, CheckCircle2, XCircle } from "lucide-react";

export const STATUS_OPTIONS = [
  { value: "to_watch", label: "To Watch", icon: Eye },
  { value: "watching", label: "Watching", icon: Play },
  { value: "completed", label: "Completed", icon: CheckCircle2 },
  { value: "dropped", label: "Dropped", icon: XCircle },
] as const;

export const STATUS_COLORS: Record<string, string> = {
  to_watch: "text-blue-500",
  watching: "text-amber-500",
  completed: "text-emerald-500",
  dropped: "text-red-500",
};
