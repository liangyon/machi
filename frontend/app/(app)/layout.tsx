"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { AppNavbar } from "@/components/app-navbar";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * App Shell Layout — wraps all authenticated routes
 * (dashboard, recommendations, import) with the navbar.
 *
 * Handles auth guard: redirects to /login if not authenticated.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
    }
  }, [loading, user, router]);

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col">
        {/* Skeleton navbar */}
        <div className="sticky top-0 z-50 w-full border-b bg-background">
          <div className="mx-auto flex h-14 max-w-7xl items-center px-4 sm:px-6">
            <Skeleton className="h-6 w-20" />
            <div className="ml-6 hidden gap-2 md:flex">
              <Skeleton className="h-8 w-24" />
              <Skeleton className="h-8 w-32" />
              <Skeleton className="h-8 w-20" />
            </div>
            <div className="ml-auto flex gap-2">
              <Skeleton className="h-9 w-9 rounded-lg" />
              <Skeleton className="h-9 w-24 rounded-lg" />
            </div>
          </div>
        </div>
        {/* Skeleton content */}
        <div className="flex-1 px-4 py-8">
          <div className="mx-auto max-w-5xl space-y-6">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-4 w-48" />
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="flex min-h-screen flex-col">
      <AppNavbar />
      <main className="flex-1">{children}</main>
    </div>
  );
}
