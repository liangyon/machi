"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { fetchAPI } from "@/lib/api";
import { ArrowRight, Download, Sparkles, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { MALSyncStatus } from "@/lib/types";

const features = [
  {
    icon: Download,
    title: "Import your list",
    description:
      "Connect MyAnimeList or AniList in seconds. We sync your full watch history to understand your taste.",
  },
  {
    icon: User,
    title: "Build your taste profile",
    description:
      "Our AI analyzes your ratings, genres, eras, and completion patterns to build a detailed taste fingerprint.",
  },
  {
    icon: Sparkles,
    title: "Get picks with real reasoning",
    description:
      "Every recommendation comes with an explanation of why it fits you — not just a score, but actual insight.",
  },
];

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading || !user) return;

    // Logged-in users skip the landing page
    fetchAPI<MALSyncStatus>("/api/mal/status")
      .then((status) => {
        if (status.sync_status === "completed") {
          router.replace("/discover");
        } else {
          router.replace("/profile?tab=import");
        }
      })
      .catch(() => {
        // No import yet
        router.replace("/profile?tab=import");
      });
  }, [user, loading, router]);

  // While checking auth / redirecting
  if (loading || user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Skeleton className="h-10 w-32" />
      </div>
    );
  }

  // Logged-out landing page
  return (
    <div className="flex min-h-screen flex-col">
      {/* Minimal nav */}
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
          <span className="text-lg font-bold tracking-tight">Machi</span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/login">Sign In</Link>
            </Button>
            <Button size="sm" asChild>
              <Link href="/register">Get Started</Link>
            </Button>
          </div>
        </div>
      </header>

      <main className="flex flex-1 flex-col">
        {/* Hero */}
        <section className="flex flex-1 flex-col items-center justify-center px-4 py-24 text-center">
          <h1 className="max-w-2xl text-5xl font-bold tracking-tight sm:text-6xl">
            Anime recs that actually get your taste
          </h1>
          <p className="mt-6 max-w-lg text-base leading-relaxed text-muted-foreground">
            Import your MyAnimeList or AniList profile. Get personalized recommendations
            with real AI reasoning — not just generic top-10 lists.
          </p>
          <div className="mt-10 flex gap-3">
            <Button size="lg" asChild>
              <Link href="/register">
                Get Started Free
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button size="lg" variant="outline" asChild>
              <Link href="/login">Sign In</Link>
            </Button>
          </div>
        </section>

        {/* Feature strip */}
        <section className="border-t bg-muted/30 px-4 py-16">
          <div className="mx-auto max-w-5xl">
            <h2 className="mb-10 text-center text-lg font-semibold text-muted-foreground uppercase tracking-wider">
              How it works
            </h2>
            <div className="grid gap-6 sm:grid-cols-3">
              {features.map((feature, i) => (
                <Card key={i} className="border-0 bg-background shadow-sm">
                  <CardContent className="pt-6 pb-6 space-y-3">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                        <feature.icon className="h-5 w-5 text-primary" />
                      </div>
                      <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                        Step {i + 1}
                      </span>
                    </div>
                    <h3 className="font-semibold">{feature.title}</h3>
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {feature.description}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* Bottom CTA */}
        <section className="border-t px-4 py-16 text-center">
          <h2 className="text-2xl font-bold">Ready to find your next anime?</h2>
          <p className="mt-3 text-sm text-muted-foreground">
            Free to use. No credit card required.
          </p>
          <Button size="lg" className="mt-6" asChild>
            <Link href="/register">
              Create Free Account
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
        </section>
      </main>
    </div>
  );
}
