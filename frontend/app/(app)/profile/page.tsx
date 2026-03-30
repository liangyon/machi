"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { Download, User } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { OverviewTab } from "@/components/profile/overview-tab";
import { ImportTab } from "@/components/profile/import-tab";
import type { PreferenceProfile } from "@/lib/types";

type Tab = "overview" | "import";

function ProfileShell() {
  const { user } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const rawTab = searchParams.get("tab");
  const activeTab: Tab = rawTab === "import" ? "import" : "overview";

  const [profile, setProfile] = useState<PreferenceProfile | null>(null);

  useEffect(() => {
    if (!user) return;
    fetchAPI<PreferenceProfile>("/api/mal/profile")
      .then(setProfile)
      .catch(() => setProfile(null));
  }, [user]);

  const setTab = (tab: Tab) => {
    const params = new URLSearchParams(searchParams.toString());
    if (tab === "overview") {
      params.delete("tab");
    } else {
      params.set("tab", tab);
    }
    router.replace(`/profile?${params.toString()}`);
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "import", label: "Import" },
  ];

  return (
    <div className="px-4 py-8">
      <div className="mx-auto max-w-5xl space-y-8">
        {/* Page header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
              <User className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Your Profile</h1>
              {profile ? (
                <div className="mt-0.5 flex items-center gap-2">
                  <Badge variant="secondary" className="text-xs">
                    {profile.source === "anilist" ? "AniList" : "MyAnimeList"}
                    {profile.imported_username && ` · @${profile.imported_username}`}
                  </Badge>
                  {profile.total_watched > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {profile.total_watched} anime
                    </span>
                  )}
                </div>
              ) : (
                <Skeleton className="mt-1 h-4 w-40" />
              )}
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setTab("import")}
            className="shrink-0"
          >
            <Download className="mr-2 h-4 w-4" />
            Import List
          </Button>
        </div>

        {/* Tab selector */}
        <div className="flex gap-1 rounded-lg border p-1 w-fit">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setTab(tab.id)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "bg-background shadow-sm text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === "overview" && (
          <OverviewTab onSwitchToImport={() => setTab("import")} />
        )}
        {activeTab === "import" && (
          <ImportTab onImportComplete={() => setTab("overview")} />
        )}
      </div>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <Suspense
      fallback={
        <div className="px-4 py-8">
          <div className="mx-auto max-w-5xl space-y-8">
            <Skeleton className="h-10 w-64" />
            <Skeleton className="h-[520px] w-full max-w-md rounded-2xl" />
          </div>
        </div>
      }
    >
      <ProfileShell />
    </Suspense>
  );
}
