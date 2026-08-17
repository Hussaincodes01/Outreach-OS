"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api } from "@/lib/api-client";

export interface AuthUser {
  id: string;
  email: string;
  role: string;
}

interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  refreshToken: string | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (input: {
    email: string;
    password: string;
    tenantName: string;
    tenantSlug?: string;
  }) => Promise<void>;
  signOut: () => void;
  refresh: () => Promise<void>;
  /**
   * Adopt a session minted elsewhere — currently the social sign-in callback,
   * which receives tokens from the API rather than exchanging credentials here.
   */
  adoptSession: (accessToken: string, refreshToken: string) => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const STORAGE_KEY = "outreach-os.auth";

interface PersistedAuth {
  accessToken: string;
  refreshToken: string;
  user: AuthUser;
}

function loadPersisted(): PersistedAuth | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PersistedAuth;
  } catch {
    return null;
  }
}

function savePersisted(value: PersistedAuth | null): void {
  if (typeof window === "undefined") return;
  if (value === null) {
    window.localStorage.removeItem(STORAGE_KEY);
  } else {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Hydrate from localStorage on mount.
  useEffect(() => {
    const persisted = loadPersisted();
    if (persisted) {
      setUser(persisted.user);
      setAccessToken(persisted.accessToken);
      setRefreshToken(persisted.refreshToken);
    }
    setLoading(false);
  }, []);

  const persistAndSet = useCallback(
    (auth: { accessToken: string; refreshToken: string; user: AuthUser } | null) => {
      if (auth === null) {
        setUser(null);
        setAccessToken(null);
        setRefreshToken(null);
        savePersisted(null);
        return;
      }
      setUser(auth.user);
      setAccessToken(auth.accessToken);
      setRefreshToken(auth.refreshToken);
      savePersisted(auth);
    },
    []
  );

  const signIn = useCallback(
    async (email: string, password: string) => {
      const pair = await api.login({ email, password });
      // API returns snake_case (`access_token`, `refresh_token`).
      const access = pair.access_token;
      const refresh = pair.refresh_token;
      api.setAccessToken(access);
      const me = await api.me(access);
      persistAndSet({
        accessToken: access,
        refreshToken: refresh,
        user: { id: me.id, email: me.email, role: me.role },
      });
    },
    [persistAndSet]
  );

  const adoptSession = useCallback(
    async (access: string, refresh: string) => {
      api.setAccessToken(access);
      const me = await api.me(access);
      persistAndSet({
        accessToken: access,
        refreshToken: refresh,
        user: { id: me.id, email: me.email, role: me.role },
      });
    },
    [persistAndSet]
  );

  const signUp = useCallback(
    async (input: {
      email: string;
      password: string;
      tenantName: string;
      tenantSlug?: string;
    }) => {
      const pair = await api.signup(input);
      const access = pair.access_token;
      const refresh = pair.refresh_token;
      api.setAccessToken(access);
      const me = await api.me(access);
      persistAndSet({
        accessToken: access,
        refreshToken: refresh,
        user: { id: me.id, email: me.email, role: me.role },
      });
    },
    [persistAndSet]
  );

  const refresh = useCallback(async () => {
    if (!refreshToken) throw new Error("no refresh token");
    const next = await api.refresh(refreshToken);
    const access = next.access_token;
    setAccessToken(access);
    api.setAccessToken(access);
    setRefreshToken((prev) => prev); // unchanged
    if (user) {
      savePersisted({ accessToken: access, refreshToken, user });
    }
  }, [refreshToken, user]);

  const signOut = useCallback(() => {
    persistAndSet(null);
    api.setAccessToken(null);
  }, [persistAndSet]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      accessToken,
      refreshToken,
      loading,
      signIn,
      signUp,
      signOut,
      refresh,
      adoptSession,
    }),
    [
      user,
      accessToken,
      refreshToken,
      loading,
      signIn,
      signUp,
      signOut,
      refresh,
      adoptSession,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
