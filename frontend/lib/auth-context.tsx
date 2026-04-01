"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  fetchMe,
  loginWithEmail,
  logout as logoutApi,
  register as registerApi,
  oauthLoginUrl,
  type OAuthProvider,
  type User,
} from "./auth";

// ── Context shape ───────────────────────────────────

interface AuthContextValue {
  user: User | null;
  loading: boolean;

  /** Redirect to an OAuth provider's login page. */
  loginOAuth: (provider: OAuthProvider) => void;

  /** Log in with email + password. */
  loginEmail: (email: string, password: string) => Promise<void>;

  /** Register a new account with email + password, then log in. */
  register: (
    email: string,
    password: string,
    name?: string
  ) => Promise<void>;

  /** Clear the session. */
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// ── Provider ────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Fetch the current session on mount
  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const loginOAuth = useCallback((provider: OAuthProvider) => {
    window.location.href = oauthLoginUrl(provider);
  }, []);

  const loginEmail = useCallback(async (email: string, password: string) => {
    await loginWithEmail(email, password);
    // Verify the session cookie was actually set by re-fetching from the server.
    // If cross-origin cookies are blocked, this will return null and the caller
    // will stay on the login page rather than redirecting to a broken dashboard.
    const u = await fetchMe();
    if (!u) throw new Error("Login succeeded but session could not be established. Check browser cookie settings.");
    setUser(u);
  }, []);

  const register = useCallback(
    async (email: string, password: string, name?: string) => {
      await registerApi(email, password, name);
      // Auto-login after registration
      await loginWithEmail(email, password);
      const u = await fetchMe();
      if (!u) throw new Error("Registration succeeded but session could not be established. Check browser cookie settings.");
      setUser(u);
    },
    []
  );

  const logout = useCallback(async () => {
    await logoutApi();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, loading, loginOAuth, loginEmail, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ── Hook ────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an <AuthProvider>");
  }
  return ctx;
}
