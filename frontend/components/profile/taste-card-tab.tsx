"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { Download, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { TasteCardDisplay } from "@/components/taste-card/taste-card-display";
import type { TasteCard } from "@/lib/types";

interface TasteCardTabProps {
  onSwitchToImport: () => void;
}

export function TasteCardTab({ onSwitchToImport }: TasteCardTabProps) {
  const { user } = useAuth();
  const cardRef = useRef<HTMLDivElement>(null);

  const [card, setCard] = useState<TasteCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCard = useCallback(async (refresh = false) => {
    const url = refresh ? "/api/taste-card?refresh=true" : "/api/taste-card";
    try {
      const data = await fetchAPI<TasteCard>(url);
      setCard(data);
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      setError(
        msg.includes("404")
          ? "No profile yet. Import your anime list first."
          : msg
      );
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    fetchCard().finally(() => setLoading(false));
  }, [user, fetchCard]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchCard(true);
    setRefreshing(false);
  };

  const handleDownload = async () => {
    if (!cardRef.current) return;
    const { default: html2canvas } = await import("html2canvas");
    const canvas = await html2canvas(cardRef.current, {
      scale: 2,
      backgroundColor: null,
      useCORS: true,
    });
    const url = canvas.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = url;
    a.download = "machi-taste-card.png";
    a.click();
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-lg space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-[520px] w-full rounded-2xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-4 py-16 text-center">
        <Alert variant="destructive" className="max-w-md">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        {error.includes("Import") && (
          <Button onClick={onSwitchToImport}>Import Your List</Button>
        )}
      </div>
    );
  }

  if (!card) return null;

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing}
        >
          <RefreshCw className={`h-4 w-4 mr-1.5 ${refreshing ? "animate-spin" : ""}`} />
          Regenerate
        </Button>
        <Button size="sm" onClick={handleDownload}>
          <Download className="h-4 w-4 mr-1.5" />
          Save PNG
        </Button>
      </div>

      <TasteCardDisplay ref={cardRef} card={card} />
    </div>
  );
}
