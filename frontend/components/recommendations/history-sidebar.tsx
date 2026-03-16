/**
 * Recommendation history components:
 * - HistorySidebar (desktop)
 * - MobileHistoryPanel
 * - SessionItem (shared)
 */

import { Clock } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { SessionSummary } from "@/lib/types";

// ── Session Item ────────────────────────────────────

function SessionItem({
  session,
  isActive,
  onClick,
}: {
  session: SessionSummary;
  isActive: boolean;
  onClick: () => void;
}) {
  const date = new Date(session.generated_at);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);

  let timeStr: string;
  if (diffHours < 1) {
    timeStr = "Just now";
  } else if (diffHours < 24) {
    timeStr = `${Math.floor(diffHours)}h ago`;
  } else if (diffHours < 48) {
    timeStr = "Yesterday";
  } else {
    timeStr = date.toLocaleDateString();
  }

  return (
    <button
      onClick={onClick}
      className={`w-full rounded-lg px-3 py-2 text-left transition ${
        isActive
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">{timeStr}</span>
        <span className="text-xs text-muted-foreground">
          {session.total_count} recs
        </span>
      </div>
      {session.custom_query ? (
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          &quot;{session.custom_query}&quot;
        </p>
      ) : (
        <p className="mt-0.5 text-xs text-muted-foreground/70">
          General recommendations
        </p>
      )}
    </button>
  );
}

// ── Desktop Sidebar ─────────────────────────────────

interface HistoryProps {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
}

export function HistorySidebar({
  sessions,
  activeSessionId,
  onSelectSession,
}: HistoryProps) {
  return (
    <div className="w-64 flex-shrink-0">
      <Card className="sticky top-20">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Clock className="h-4 w-4" />
            History
          </CardTitle>
        </CardHeader>
        <CardContent className="max-h-96 overflow-y-auto p-2">
          {sessions.map((session, index) => (
            <SessionItem
              key={session.id}
              session={session}
              isActive={
                activeSessionId === session.id ||
                (activeSessionId === null && index === 0)
              }
              onClick={() => onSelectSession(session.id)}
            />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Mobile History Panel ────────────────────────────

export function MobileHistoryPanel({
  sessions,
  activeSessionId,
  onSelectSession,
}: HistoryProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Clock className="h-4 w-4" />
          Past Sessions
        </CardTitle>
      </CardHeader>
      <CardContent className="max-h-64 overflow-y-auto p-2">
        {sessions.map((session, index) => (
          <SessionItem
            key={session.id}
            session={session}
            isActive={
              activeSessionId === session.id ||
              (activeSessionId === null && index === 0)
            }
            onClick={() => onSelectSession(session.id)}
          />
        ))}
      </CardContent>
    </Card>
  );
}
