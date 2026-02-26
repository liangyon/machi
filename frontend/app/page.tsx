"use client";

import { useEffect, useState } from "react";
import { fetchAPI } from "@/lib/api";

type Status = "loading" | "connected" | "disconnected";

export default function Home() {
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    fetchAPI<{ status: string }>("/api/health")
      .then((data) => setStatus(data.status === "ok" ? "connected" : "disconnected"))
      .catch(() => setStatus("disconnected"));
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 font-sans dark:bg-zinc-950">
      <main className="flex flex-col items-center gap-8 text-center">
        <h1 className="text-4xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          Machi
        </h1>

        <div className="flex items-center gap-3 rounded-full border border-zinc-200 bg-white px-6 py-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <span
            className={`inline-block h-3 w-3 rounded-full ${
              status === "loading"
                ? "animate-pulse bg-zinc-400"
                : status === "connected"
                  ? "bg-emerald-500"
                  : "bg-red-500"
            }`}
          />
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            {status === "loading"
              ? "Checking backend…"
              : status === "connected"
                ? "Connected to backend ✓"
                : "Backend unreachable ✗"}
          </span>
        </div>

        <p className="max-w-md text-sm leading-6 text-zinc-500 dark:text-zinc-400">
          Start the backend with{" "}
          <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-mono dark:bg-zinc-800">
            make backend
          </code>{" "}
          and the frontend with{" "}
          <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-mono dark:bg-zinc-800">
            make frontend
          </code>
          , or run both together with{" "}
          <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-mono dark:bg-zinc-800">
            make dev
          </code>
          .
        </p>
      </main>
    </div>
  );
}
