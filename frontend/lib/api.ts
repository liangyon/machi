/**
 * Thin API client helper.
 *
 * Centralises fetch calls so every component doesn't have to repeat
 * base-URL logic, headers, or error handling.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string;
  };
  detail?: string;
}

/**
 * Wrapper around `fetch` that:
 * - prepends the API base URL
 * - sets JSON content-type by default
 * - throws with the server error detail on non-2xx responses
 */
export async function fetchAPI<T = unknown>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const url = `${API_BASE}${path}`;

  const res = await fetch(url, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });

  if (!res.ok) {
    const body: ApiErrorEnvelope = await res.json().catch(() => ({
      detail: res.statusText,
    }));

    const requestId = body.error?.request_id ?? res.headers.get("X-Request-ID") ?? undefined;
    const code = body.error?.code ?? "REQUEST_FAILED";
    const message = body.error?.message ?? body.detail ?? `Request failed: ${res.status}`;

    throw new Error(
      requestId ? `[${code}] ${message} (request_id: ${requestId})` : `[${code}] ${message}`
    );
  }

  return res.json() as Promise<T>;
}
