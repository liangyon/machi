/**
 * Thin API client helper.
 *
 * Centralises fetch calls so every component doesn't have to repeat
 * base-URL logic, headers, or error handling.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

interface ApiError {
  detail: string;
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
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });

  if (!res.ok) {
    const body: ApiError = await res.json().catch(() => ({
      detail: res.statusText,
    }));
    throw new Error(body.detail ?? `Request failed: ${res.status}`);
  }

  return res.json() as Promise<T>;
}
