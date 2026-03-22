"use client";

import { useCallback, useRef, useState } from "react";
import type { RecommendationJobStatus } from "@/lib/types";

interface JobPollerOptions {
  pollFn: () => Promise<RecommendationJobStatus>;
  onSuccess: (sessionId: string | null) => void;
  onFailure: (error: string) => void;
  maxAttempts?: number;
  intervalMs?: number;
}

interface JobPollerState {
  isPolling: boolean;
  progress: number;
  stage: string;
  error: string | null;
}

/**
 * Shared hook for polling an async generation job.
 *
 * Encapsulates the polling loop that was previously inline in the
 * recommendations page.  Both the recommendations and cauldron pages
 * use this hook via `startPolling()`.
 *
 * Uses a recursive setTimeout approach (not setInterval) to avoid
 * overlapping poll calls on slow networks.
 *
 * Cleanup: an `aborted` ref is set on unmount so orphaned timeouts
 * don't update state after the component is gone.
 */
export function useJobPoller() {
  const [state, setState] = useState<JobPollerState>({
    isPolling: false,
    progress: 0,
    stage: "queued",
    error: null,
  });

  // Used to cancel the loop when the component unmounts or a new
  // poll is started before the previous one finishes.
  const abortRef = useRef(false);

  const startPolling = useCallback((options: JobPollerOptions) => {
    const {
      pollFn,
      onSuccess,
      onFailure,
      maxAttempts = 180,
      intervalMs = 1000,
    } = options;

    // Cancel any previous loop
    abortRef.current = true;
    // Reset for new loop
    abortRef.current = false;

    setState({ isPolling: true, progress: 0, stage: "queued", error: null });

    let attempts = 0;
    const abortSnapshot = abortRef; // capture ref for this closure

    const poll = async () => {
      if (abortSnapshot.current) return;

      try {
        const status = await pollFn();

        if (abortSnapshot.current) return;

        setState((prev) => ({
          ...prev,
          progress: status.progress,
          stage: status.stage,
        }));

        if (status.status === "succeeded") {
          setState((prev) => ({ ...prev, isPolling: false }));
          onSuccess(status.session_id);
          return;
        }

        if (status.status === "failed") {
          const errMsg = status.error || "Generation failed. Please try again.";
          setState((prev) => ({
            ...prev,
            isPolling: false,
            error: errMsg,
          }));
          onFailure(errMsg);
          return;
        }

        attempts += 1;
        if (attempts >= maxAttempts) {
          const timeoutMsg = "Generation timed out. Please try again.";
          setState((prev) => ({
            ...prev,
            isPolling: false,
            error: timeoutMsg,
          }));
          onFailure(timeoutMsg);
          return;
        }

        // Schedule next poll
        setTimeout(poll, intervalMs);
      } catch (err) {
        if (abortSnapshot.current) return;
        const errMsg =
          err instanceof Error ? err.message : "An unexpected error occurred.";
        setState((prev) => ({ ...prev, isPolling: false, error: errMsg }));
        onFailure(errMsg);
      }
    };

    // Start first poll after a short delay
    setTimeout(poll, intervalMs);
  }, []);

  const stopPolling = useCallback(() => {
    abortRef.current = true;
    setState((prev) => ({ ...prev, isPolling: false }));
  }, []);

  return {
    startPolling,
    stopPolling,
    isPolling: state.isPolling,
    progress: state.progress,
    stage: state.stage,
    pollingError: state.error,
  };
}
